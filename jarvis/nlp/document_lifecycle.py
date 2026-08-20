"""One owner per document explanation: generation tokens and a verified cursor.

The document explanation path had several independent producers — the upload
worker in ``window_voice``, ``DocumentAnalysis``, and the legacy
``file_processor`` — each able to publish a result, checkpoint, or spoken line
without any shared generation token or playback-verified cursor.

This coordinator gives one lifecycle per document identity (a safe content
fingerprint).  A request is owned by exactly one generation token; a newer
request supersedes the older one, so stale LLM output can never publish, move
the cursor, or speak.  The explanation is segmented deterministically on the
same chunk planner ``doc_extract.summarize_long`` uses, and the spoken cursor
advances only after a segment's playback ticket reaches a verified drain.

Nothing here stores raw document paths, credentials, tool results, or content
into durable state; the fingerprint is path-independent and opaque.
"""
from __future__ import annotations

import hashlib
import threading
import uuid
from dataclasses import dataclass, field

from jarvis.nlp.doc_extract import plan_chunks

_SEGMENT_MAX_CHARS = 900
_MAX_LIFECYCLES = 32
_SEGMENT_OVERLAP = 0            # explanations never overlap; segments are exact


def segmentation(text: str, max_chars: int = _SEGMENT_MAX_CHARS) -> list[str]:
    """Deterministic explanation segments on the shared chunk planner.

    Segments are exact (no overlap) so the spoken cursor is a simple index
    over the same coordinate space the checkpoint persists.
    """
    return plan_chunks(text, max_chunk=max(200, int(max_chars)))


@dataclass
class _Segment:
    index: int
    text: str
    verified: bool = False


@dataclass
class _Generation:
    token: str
    segments: list[_Segment] = field(default_factory=list)
    request: int = 0


class DocumentLifecycle:
    """State for ONE document identity in ONE logical conversation."""

    def __init__(
        self,
        fingerprint: str,
        title: str,
        *,
        source: str = "",
        _text: str = "",
        max_chars: int = _SEGMENT_MAX_CHARS,
    ) -> None:
        self.fingerprint = str(fingerprint or "")[:96]
        self.title = str(title or "")[:120]
        self.source = str(source or "")[:16]
        self._max_chars = max(200, int(max_chars or _SEGMENT_MAX_CHARS))
        self._generation: _Generation | None = None
        self._segments: list[_Segment] | None = None
        self._lock = threading.Lock()
        if _text:
            self._seed(_text)

    # ── planning ────────────────────────────────────────────────────────────

    def _seed(self, text: str) -> None:
        """Deterministically plan segments from raw text (no LLM calls)."""
        chunks = plan_chunks(text, max_chunk=self._max_chars)
        if not chunks:
            chunks = ["(dokumen kosong)"]
        self._segments = [
            _Segment(index=i, text=chunk[: self._max_chars])
            for i, chunk in enumerate(chunks)
        ]

    def plan_explanation(self) -> list[str]:
        """Return the deterministic segment texts for this document.

        Planning happens once per document identity; the segment list is stable
        across generations so the cursor has a fixed coordinate space.
        """
        with self._lock:
            if self._segments is None:
                return []
            return [seg.text for seg in self._segments]

    def segment_count(self) -> int:
        with self._lock:
            return len(self._segments) if self._segments is not None else 0

    # ── request ownership ───────────────────────────────────────────────────

    def begin_request(self) -> str:
        """Open a new explanation request; supersedes any older generation.

        Returns the opaque request token that owns every side effect of this
        generation (model output, UI publish, checkpoint, speech).
        """
        token = uuid.uuid4().hex[:12]
        with self._lock:
            segments = list(self._segments) if self._segments is not None else []
            self._generation = _Generation(
                token=token,
                segments=[_Segment(index=seg.index, text=seg.text,
                                   verified=seg.verified)
                          for seg in segments],
                request=(self._generation.request if self._generation else 0) + 1,
            )
        return token

    def is_active(self, token: str) -> bool:
        with self._lock:
            return bool(self._generation and self._generation.token == token)

    @property
    def generation_token(self) -> str:
        with self._lock:
            return self._generation.token if self._generation else ""

    # ── cursor ──────────────────────────────────────────────────────────────

    def mark_segment_done(self, index: int, token: str) -> bool:
        """Advance the verified cursor for one segment of THIS generation.

        A stale token never moves the cursor; a segment already verified is
        never re-verified (cursor only moves forward).
        """
        with self._lock:
            if not (self._generation and self._generation.token == token):
                return False
            if index < 0 or index >= len(self._generation.segments):
                return False
            seg = self._generation.segments[index]
            if seg.verified:
                return False
            seg.verified = True
            return True

    def first_unverified(self) -> int | None:
        """Index of the first segment not yet verified, or None when done."""
        with self._lock:
            if self._generation is None:
                return 0 if self._segments else None
            for seg in self._generation.segments:
                if not seg.verified:
                    return seg.index
            return None

    def verified_count(self) -> int:
        with self._lock:
            if self._generation is None:
                return 0
            return sum(1 for seg in self._generation.segments if seg.verified)

    def resume_point(self) -> int:
        point = self.first_unverified()
        return point if point is not None else self.segment_count()

    def has_verified_drain(self) -> bool:
        """Whether the cursor reached the FINAL segment of this generation."""
        with self._lock:
            if self._generation is None:
                return False
            return bool(self._generation.segments) and all(
                seg.verified for seg in self._generation.segments
            )

    def interrupted_report(self) -> str:
        """Honest interruption text; never claims a last spoken word."""
        point = self.first_unverified()
        if point is None:
            return ""
        return (
            "Penjelasan dokumen terputus sebelum selesai dibacakan. "
            f"Bagian {point + 1} belum terverifikasi terdengar. "
            "Katakan 'lanjutkan' untuk memulai dari bagian itu, atau minta "
            "saya mengulang dari awal."
        )


class DocumentExplanation:
    """Deterministic, cursor-checked producer for a segmented explanation.

    One ``DocumentExplanation`` instance owns one generation request.  It
    yields segments in order, and a segment's spoken cursor advances ONLY when
    the caller reports a verified playback drain for that submission.  A stale
    generation token, an aborted submission, or a silent drop never advances
    the cursor, so an interrupted explanation resumes at the first segment
    whose audio is genuinely known to have been heard.
    """

    def __init__(self, lifecycle: DocumentLifecycle, token: str) -> None:
        self._lc = lifecycle
        self._token = token
        self._segments = lifecycle.plan_explanation()

    def pending_segments(self) -> list[str]:
        """Segments after the verified cursor, in order (nothing is spoken)."""
        start = self._lc.resume_point()
        return list(self._segments[start:])

    def next_submission(self) -> tuple[int, str, callable] | None:
        """Next (index, text, mark_verified) to submit, or None when done.

        ``mark_verified(verified=True)`` records a real audible drain for this
        segment; ``mark_verified(verified=False)`` (aborted/silent/interrupted)
        leaves the cursor untouched so the segment is the first unverified.
        """
        index = self._lc.first_unverified()
        if index is None or index >= len(self._segments):
            return None
        text = self._segments[index]

        def mark_verified(*, verified: bool) -> bool:
            if not verified:
                return False
            return self._lc.mark_segment_done(index, self._token)

        return index, text, mark_verified


class DocumentCoordinator:
    """Small LRU of per-document lifecycles, keyed by safe fingerprint."""

    def __init__(self, max_lifecycles: int = _MAX_LIFECYCLES) -> None:
        self._max = max(1, int(max_lifecycles))
        self._lifecycles: dict[str, DocumentLifecycle] = {}
        self._lock = threading.Lock()

    def open_text(
        self,
        fingerprint: str,
        text: str,
        *,
        source: str = "",
        title: str = "",
    ) -> DocumentLifecycle:
        """Get or create the lifecycle for a document identity.

        A later open of the SAME fingerprint reuses the existing lifecycle, so
        upload + explain + summarize all share one generation owner.
        """
        key = safe_fingerprint(fingerprint)
        with self._lock:
            existing = self._lifecycles.get(key)
            if existing is not None:
                return existing
            lifecycle = DocumentLifecycle(
                key, title or "dokumen", source=source, _text=text)
            self._lifecycles[key] = lifecycle
            while len(self._lifecycles) > self._max:
                self._lifecycles.pop(next(iter(self._lifecycles)))
            return lifecycle

    def get(self, fingerprint: str) -> DocumentLifecycle | None:
        with self._lock:
            return self._lifecycles.get(safe_fingerprint(fingerprint))

    def clear(self) -> None:
        with self._lock:
            self._lifecycles.clear()


def safe_fingerprint(value: object) -> str:
    """Opaque, path-independent content identity.

    The raw path or text never appears in the fingerprint, so no local path,
    secret, or credential leaks into logs, speech, or prompt context.
    """
    raw = str(value or "")
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]


COORDINATOR = DocumentCoordinator()


def lifecycle_for_path(path: str, *, source: str = "") -> DocumentLifecycle | None:
    """Resolve the coordinator lifecycle for a document path (or None)."""
    if not path:
        return None
    fp = safe_fingerprint(path)
    lifecycle = COORDINATOR.get(fp)
    if lifecycle is not None:
        return lifecycle
    from jarvis.nlp.document import read_document
    try:
        text = read_document(str(path))
    except Exception:  # noqa: BLE001 - failed reads have no lifecycle owner
        return None
    if not text.strip():
        return None
    return COORDINATOR.open_text(fp, text, source=source)


__all__ = [
    "COORDINATOR",
    "DocumentCoordinator",
    "DocumentExplanation",
    "DocumentLifecycle",
    "lifecycle_for_path",
    "safe_fingerprint",
]
