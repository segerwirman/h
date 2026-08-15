"""Bounded, in-memory continuity for immediate Jarvis follow-ups.

This is deliberately separate from durable memory and agent-session archival.
Only the latest user intent and safe spoken delivery are retained per logical
conversation. Raw display reports, tool output, and failure details never
enter this store.

Tasks are tracked per registry task ID: one conversation may run several
background tasks at once, each bound to its own ID after registry submission.
``augment()`` resolves follow-up references deterministically — explicit ID,
unique title, sole active task, unique recent result, then an honest
needs-clarification block — and never guesses when two tasks could match.
"""
from __future__ import annotations

import re
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from jarvis.agent.interaction import ConversationDelivery

_FOLLOW_UPS = {
    "lanjutkan", "lanjut", "teruskan", "yang tadi", "buka hasilnya",
    "buka hasil", "buka itu", "buka tadi", "tampilkan hasilnya",
    "tampilkan hasil", "lihat hasilnya", "lihat hasil",
}
_URL_OR_PATH = re.compile(r"(?:https?://|www\.|[A-Za-z]:[\\/]|/[\w.-]+(?:/[\w.-]+)+)")
# Rujukan follow-up natural: "lanjutkan…", "hasil sebelumnya", "gunakan hasil",
# serta perintah membuka artefak yang baru dibuat: "buka/tampilkan/lihat …
# gambar/file/hasil/berkas … itu/tadi/tersebut/nya/barusan".
_FOLLOW_UP_RE = re.compile(
    r"^(?:lanjutkan|lanjut|teruskan)\b"
    r"|\b(?:hasil(?:nya)?\s+sebelumnya|gunakan\s+hasil)\b"
    r"|\b(?:buka|bukakan|tampilkan|tampilin|lihat|perlihatkan|"
    r"tunjukkan|tunjukan|show|open)\b"
    r"[^.\n]{0,40}?"
    r"\b(?:gambar|foto|image|file|berkas|hasil(?:nya)?|dokumen|itu|tadi|"
    r"tersebut|barusan|yang\s+tadi)\b",
    re.IGNORECASE,
)
# Rujukan artefak: perintah membuka sesuatu yang baru diproduksi JARVIS.
_ARTIFACT_REF_RE = re.compile(
    r"\b(?:buka|bukakan|tampilkan|tampilin|lihat|perlihatkan|tunjukkan|"
    r"tunjukan|show|open|putar|mainkan)\b",
    re.IGNORECASE,
)
_CONTEXT_MARKER = "\n\n[KONTEKS PERCAKAPAN LANGSUNG]"
_LEGACY_TASK_PREFIX = "~"          # synthetic key for title-only legacy binding
_MAX_ACTIVE_TASKS = 4


@dataclass
class _ActiveTask:
    task_id: str                       # registry ID ("" for legacy title binding)
    title: str                         # safe, bounded task/topic descriptor
    source: str = ""
    seq: int = 0                       # recency order within the conversation


@dataclass(frozen=True)
class FollowUpResult:
    """Structured reference resolution so callers act, not guess."""

    kind: str                          # "none" | "recent" | "task" | "ambiguous"
    title: str = ""
    spoken: str = ""
    candidates: tuple[str, ...] = ()


@dataclass
class _ImmediateContext:
    last_intent: str = ""
    last_spoken: str = ""
    active_tasks: OrderedDict[str, _ActiveTask] = field(
        default_factory=OrderedDict)
    last_artifact: str = ""          # desktop-local path/URL artefak terakhir
    last_artifact_kind: str = ""     # "image" | "file" | "url" | ""
    recent_intents: deque[str] = field(default_factory=lambda: deque(maxlen=3))
    recent_template_ids: deque[str] = field(default_factory=lambda: deque(maxlen=4))


class ConversationContextStore:
    """Small LRU of immediate, non-durable conversation state."""

    def __init__(self, max_sessions: int = 32) -> None:
        self._max_sessions = max(1, int(max_sessions))
        self._sessions: OrderedDict[str, _ImmediateContext] = OrderedDict()
        self._lock = threading.Lock()

    def remember_success(
        self,
        conversation_id: str,
        *,
        task: str,
        delivery: ConversationDelivery,
        task_id: str = "",
    ) -> None:
        """Keep only facts already approved for speech after a success."""

        key = _key(conversation_id)
        if not key:
            return
        spoken = _safe_spoken(delivery.speech_text)
        with self._lock:
            context = self._sessions.pop(key, _ImmediateContext())
            intent = _safe_task(task)[:800]
            context.last_intent = intent
            if intent and (not context.recent_intents or context.recent_intents[-1] != intent):
                context.recent_intents.append(intent)
            context.last_spoken = spoken[:600]
            if task_id:
                # Completion removes ONLY this task's binding; other active
                # tasks in the same conversation stay addressable.
                context.active_tasks.pop(str(task_id).strip(), None)
            else:
                # Legacy title-only binding: clear only the matching legacy
                # key so a completion never empties another active task. A
                # seam-bound ID task whose title matches this completion is
                # cleared too, so a caller that cannot pass task_id (FROZEN
                # voice) still releases its one matching active task.
                legacy_key = _LEGACY_TASK_PREFIX + intent[:48]
                context.active_tasks.pop(legacy_key, None)
                for entry in list(context.active_tasks.values()):
                    if entry.title and intent \
                            and entry.title.casefold() == intent.casefold():
                        context.active_tasks.pop(entry.task_id, None)
            if delivery.mode:
                context.recent_template_ids.append(str(delivery.mode)[:48])
            self._sessions[key] = context
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)

    def remember_artifact(
        self, conversation_id: str, *, path: str, kind: str = "file"
    ) -> None:
        """Ingat artefak terakhir yang JARVIS produksi (mis. gambar hasil
        image_generate) agar follow-up 'buka gambar itu' bisa membukanya.

        Ini SENGAJA tidak masuk blok konteks prompt/remote/ucapan — hanya
        dipakai lokal untuk membuka file yang baru dibuat. Isolasi privacy
        durable memory tetap terjaga.
        """
        key = _key(conversation_id)
        clean = str(path or "").strip()
        if not key or not clean:
            return
        with self._lock:
            context = self._sessions.pop(key, _ImmediateContext())
            context.last_artifact = clean[:600]
            context.last_artifact_kind = str(kind or "file")[:16]
            self._sessions[key] = context
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)

    def last_artifact(self, conversation_id: str) -> tuple[str, str]:
        """(path, kind) artefak terakhir untuk conversation ini; ('','') bila
        belum ada."""
        with self._lock:
            context = self._sessions.get(_key(conversation_id))
            if context is None or not context.last_artifact:
                return "", ""
            return context.last_artifact, context.last_artifact_kind

    def begin_task(
        self,
        conversation_id: str,
        task: str,
        *,
        task_id: str = "",
        source: str = "",
    ) -> None:
        """Bind one bounded in-flight task; completion removes only its ID.

        ``task`` is the safe title/topic descriptor. When ``task_id`` is given,
        the task is keyed by its registry ID; otherwise the legacy title-only
        form stays visible through the compatibility ``active_task()`` view.
        The collection is bounded: the oldest task is evicted at the cap.
        """
        key = _key(conversation_id)
        title = str(task or "").strip()[:800]
        if not key or not title:
            return
        tid = str(task_id or "").strip()[:64]
        with self._lock:
            context = self._sessions.pop(key, _ImmediateContext())
            if tid:
                slot = _ActiveTask(task_id=tid, title=title,
                                   source=str(source or "")[:16])
                if tid in context.active_tasks:
                    context.active_tasks.move_to_end(tid)
                    context.active_tasks[tid].title = title
                else:
                    slot.seq = len(context.active_tasks)
                    context.active_tasks[tid] = slot
                    while len(context.active_tasks) > _MAX_ACTIVE_TASKS:
                        context.active_tasks.popitem(last=False)
            else:
                legacy_key = _LEGACY_TASK_PREFIX + title[:48]
                context.active_tasks[legacy_key] = _ActiveTask(
                    task_id="", title=title,
                    source=str(source or "")[:16],
                    seq=len(context.active_tasks))
                while len(context.active_tasks) > _MAX_ACTIVE_TASKS:
                    context.active_tasks.popitem(last=False)
            self._sessions[key] = context
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)

    def active_tasks(self, conversation_id: str) -> list[dict]:
        """Descriptors of in-flight tasks, most recent first (bounded)."""
        with self._lock:
            context = self._sessions.get(_key(conversation_id))
            if context is None:
                return []
            return [
                {"task_id": entry.task_id, "title": entry.title,
                 "source": entry.source}
                for entry in reversed(list(context.active_tasks.values()))
            ]

    def active_task(self, conversation_id: str) -> str:
        """Compatibility view: the sole title, or "" for multiple tasks."""
        with self._lock:
            context = self._sessions.get(_key(conversation_id))
            if context is None or not context.active_tasks:
                return ""
            titles = {entry.title for entry in context.active_tasks.values()}
            return next(iter(titles)) if len(titles) == 1 else ""

    def fail_task(self, conversation_id: str, task_id: str) -> None:
        """Remove one failed task binding by registry ID (never others).

        The session itself is preserved while it still carries unrelated safe
        continuity (a recent result, artifact, or recent intent). Only a truly
        empty context is evicted, so failing the last active task never erases
        a completed result the user may want to reference.
        """
        key = _key(conversation_id)
        tid = str(task_id or "").strip()
        if not key or not tid:
            return
        with self._lock:
            context = self._sessions.get(key)
            if context is None:
                return
            context.active_tasks.pop(tid, None)
            if not context.active_tasks and not _keeps_session(context):
                self._sessions.pop(key, None)

    def resolve(self, conversation_id: str, reference: str) -> FollowUpResult:
        """Structured resolution so callers can ask rather than dispatch a guess.

        Returns ``FollowUpResult`` with kind:
          * ``"none"``      — no viable target; return the reference untouched;
          * ``"recent"``    — a unique safe recent result (no in-flight task);
          * ``"task"``      — one deterministic in-flight task match;
          * ``"ambiguous"`` — two or more live tasks could match; caller must ask.
        """
        original = str(reference or "").strip()
        if not _is_follow_up(original):
            return FollowUpResult(kind="none")
        with self._lock:
            context = self._sessions.get(_key(conversation_id))
            if context is None:
                return FollowUpResult(kind="none")
            has_context = bool(
                context.last_intent or context.last_spoken
                or context.active_tasks)
            if not has_context:
                return FollowUpResult(kind="none")
            self._sessions.move_to_end(_key(conversation_id))
            return _resolve(context, original)

    def augment(self, conversation_id: str, task: str) -> str:
        """Return a private context block only for exact, unambiguous references.

        No task is bound here: registry ID binding happens only after the
        registry produces the real task ID (dispatch ``on_task`` metadata), so a
        non-follow-up command never creates a synthetic pre-registry task.
        """
        original = str(task or "").strip()
        resolved = self.resolve(conversation_id, original)
        if resolved.kind == "none":
            return original
        key = _key(conversation_id)
        with self._lock:
            context = self._sessions.get(key)
            recent = " | ".join(context.recent_intents)[:800] if context else ""
        if resolved.kind == "ambiguous":
            return (
                f"{original}\n\n[KONTEKS PERCAKAPAN LANGSUNG]\n"
                "Rujukan ini cocok dengan beberapa tugas yang sedang berjalan:\n"
                + "\n".join(f"- {title}" for title in resolved.candidates)
                + "\nMinta user menyebutkan id/nomor tugas yang dimaksud."
            )
        return (
            f"{original}\n\n[KONTEKS PERCAKAPAN LANGSUNG]\n"
            f"Tugas sebelumnya: {resolved.title}\n"
            f"Riwayat tugas ringkas: {recent}\n"
            f"Hasil terakhir (brief aman): {resolved.spoken}\n"
            "Gunakan konteks ini hanya untuk menyelesaikan rujukan pengguna."
        )

    def context_block(self, conversation_id: str) -> str:
        """Safe, compact block for optional naturalization only."""

        with self._lock:
            context = self._sessions.get(_key(conversation_id))
            if context is None or not context.last_spoken:
                return ""
            return (
                "Konteks percakapan langsung (jangan menambah fakta baru): "
                f"tugas terakhir={context.last_intent}; "
                f"brief terakhir={context.last_spoken}"
            )


def _keeps_session(context: _ImmediateContext) -> bool:
    """Whether a session still holds safe continuity worth preserving."""
    return bool(context.last_intent or context.last_spoken
                or context.last_artifact or context.recent_intents)


def _resolve(
    context: _ImmediateContext,
    reference: str,
) -> FollowUpResult:
    """Deterministic reference resolution; None = ambiguous or unmatched."""
    ref = _normalise_reference(reference)
    active = list(context.active_tasks.values())

    if not active:
        # No in-flight task: the only viable target is a unique recent safe
        # result. Without one there is nothing to continue.
        if context.last_intent and context.last_spoken:
            return FollowUpResult(kind="recent", title=context.last_intent,
                                  spoken=context.last_spoken)
        return FollowUpResult(kind="none")

    # 1. Explicit task ID.
    for entry in active:
        if entry.task_id and entry.task_id.casefold() in ref:
            return FollowUpResult(kind="task", title=entry.title,
                                  candidates=(entry.title,))

    # 2. Unique title/topic match.
    matches = [entry for entry in active
               if entry.title.casefold() in ref]
    if len(matches) == 1:
        entry = matches[0]
        return FollowUpResult(kind="task", title=entry.title,
                              candidates=(entry.title,))
    if len(matches) > 1:
        # Several live tasks share this topic — ask, never guess.
        return FollowUpResult(
            kind="ambiguous",
            candidates=tuple(entry.title for entry in matches[:4]))

    # 3. Sole active task.
    if len(active) == 1:
        entry = active[0]
        return FollowUpResult(kind="task", title=entry.title,
                              candidates=(entry.title,))

    # Two or more live tasks exist and none matched explicitly. A previous
    # completed result must NOT override that ambiguity: "lanjutkan" could
    # mean any of them, so the caller must ask.
    return FollowUpResult(
        kind="ambiguous",
        candidates=tuple(entry.title for entry in active[:4]))


def _spoken_for(context: _ImmediateContext, title: str) -> str:
    """The safe brief for an in-flight task, which has none yet."""
    return ""


def _key(value: object) -> str:
    return str(value or "").strip()[:96]


def _normalise_reference(value: str) -> str:
    return value.casefold().strip().rstrip(".?!")


def _is_follow_up(value: str) -> bool:
    return _normalise_reference(value) in _FOLLOW_UPS or bool(_FOLLOW_UP_RE.search(value))


def is_follow_up(value: str) -> bool:
    """Public: apakah teks user merujuk hasil/tugas sebelumnya."""
    return _is_follow_up(str(value or ""))


def is_artifact_reference(value: str) -> bool:
    """Apakah user meminta MEMBUKA artefak yang baru dibuat (bukan sekadar
    melanjutkan tugas). Contoh: 'buka gambar itu', 'tampilkan hasilnya',
    'lihat file tadi'. Dipakai UI untuk membuka file terakhir secara langsung.
    """
    text = str(value or "")
    if not _ARTIFACT_REF_RE.search(text):
        return False
    return bool(_FOLLOW_UP_RE.search(text)) or _normalise_reference(text) in _FOLLOW_UPS


def _safe_task(value: object) -> str:
    return str(value or "").split(_CONTEXT_MARKER, 1)[0].strip()


def _safe_spoken(value: object) -> str:
    text = " ".join(str(value or "").split())
    return _URL_OR_PATH.sub("", text).strip()


STORE = ConversationContextStore()
