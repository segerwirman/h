"""Voice document seam — resolve FunctionCall paths and keep Live explanation
on the coordinator lifecycle (Fase 43 runtime PDF/video).

The FROZEN ``main.py::JarvisLive._execute_tool`` only fills ``file_path``
from ``ui.current_file`` when the argument is EMPTY.  A Gemini Live
FunctionCall that carries a basename (``Claude-Remotion-Blueprint.pdf``)
therefore reaches ``actions.file_processor`` unresolved and fails with
``File not found``, and an explicit spoken "jelaskan dokumen ini" becomes a
single one-shot analysis instead of the coordinator's segmented,
drain-verified explanation.

This seam is the smallest non-FROZEN interception point:

- ``install()`` wraps ``JarvisLive._execute_tool`` so every ``file_processor``
  call is normalized against the actually-loaded file identity (never a disk
  search, never an ambiguous basename guess).
- Explicit document explanation requests route through
  ``DocumentLifecycle``/``DocumentExplanation`` (the SAME owner seeded at
  upload) and are delivered through the drain-aware speech submitter, so the
  spoken cursor only advances after a verified playback drain.
- Video explanation builds its lifecycle from a real audio transcript and
  fails honestly (never claims to explain visuals) when ffmpeg, an audio
  track, or a transcript is unavailable.
- Structured ``voice.document.*`` telemetry is emitted for generation,
  request, segment delivery, verified drain, cursor before/after,
  interruption, and lane-busy outcomes.

No FROZEN file is touched; everything lives on the editable integration seam.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from jarvis.core.quiet import swallowed

# Document identities the upload worker seeds into the coordinator
# (window_voice._on_file).  Code files are deliberately excluded: they are
# not seeded at upload and belong to a separate follow-up scope.
_DOCUMENT_EXTS = {".pdf", ".docx", ".doc", ".txt", ".md", ".csv"}
_VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v"}

_MARKER = "_jarvis_voice_document_installed"
_LANE_TIMEOUT_S = 30.0

_EXPLANATION_PREFIXES = (
    "jelaskan dokumen",
    "jelaskan file",
    "jelaskan berkas",
    "jelaskan video",
    "bacakan dokumen",
    "bacakan file",
    "lanjutkan penjelasan",
    "lanjutkan membaca",
    "explain document",
    "explain file",
    "explain video",
    "read the document",
    "read this file",
)
_EXPLANATION_ACTIONS = {"explain", "jelaskan", "bacakan"}


def _hint(path: str) -> str:
    """Short, path-safe label for telemetry (basename only)."""
    return str(os.path.basename(str(path or "")))[:80]


def _emit(live: Any, event: str, **fields: Any) -> None:
    trace = getattr(live, "_trace", None)
    if not callable(trace):
        return
    try:
        trace(event, **fields)
    except Exception as exc:  # noqa: BLE001 - telemetry must never break routing
        swallowed("voice.document.trace_failed", exc=exc, event=event)


# ── loaded-file identity (never a disk search) ─────────────────────────────


def loaded_file_candidates(live: Any) -> list[str]:
    """Full paths currently known to be uploaded, in deterministic order."""
    ui = getattr(live, "ui", None)
    win = getattr(ui, "_win", None) or ui
    assistant = getattr(ui, "assistant", None)
    seen: list[str] = []
    for holder in (ui, win, assistant):
        if holder is None:
            continue
        path = getattr(holder, "current_file", None)
        if not isinstance(path, str) or not path:
            path = getattr(holder, "_current_file", None)
        if not isinstance(path, str) or not path:
            path = getattr(getattr(holder, "ctx", None), "uploaded_file", None)
        if isinstance(path, str) and path and path not in seen:
            seen.append(path)
    return seen


def resolve_loaded_path(live: Any, given: str) -> str | None:
    """Resolve a FunctionCall ``file_path`` against loaded identities only.

    Exact-path match wins; then a basename match against EXACTLY ONE loaded
    file.  Ambiguous or unmatched basenames return ``None`` — the caller must
    never fall back to scanning the disk.  An empty ``given`` resolves only
    when exactly one file is loaded (the same identity the FROZEN handler
    fills from ``ui.current_file``).
    """
    given = (given or "").strip()
    candidates = loaded_file_candidates(live)
    if not candidates:
        return None
    if given:
        norm = os.path.normcase
        for cand in candidates:
            if norm(os.path.abspath(cand)) == norm(os.path.abspath(given)):
                return cand
        base = os.path.basename(given).lower()
        matches = [
            c for c in candidates
            if base and os.path.basename(c).lower() == base
        ]
        return matches[0] if len(matches) == 1 else None
    return candidates[0] if len(candidates) == 1 else None


# ── explanation-intent detection ───────────────────────────────────────────


def request_intent(args: dict) -> str:
    """Combine the FunctionCall action + instruction into one lowercase text."""
    action = str(args.get("action") or "").strip().lower()
    instruction = str(args.get("instruction") or "").strip().lower()
    return f"{action} {instruction}".strip()


def looks_explanation(intent: str) -> bool:
    """Whether the combined FunctionCall text asks for a read-aloud."""
    text = " ".join((intent or "").lower().split())
    if not text:
        return False
    if text in _EXPLANATION_ACTIONS:
        return True
    return any(text.startswith(prefix) for prefix in _EXPLANATION_PREFIXES)


# ── drain-aware delivery ───────────────────────────────────────────────────


def _speech_submitter(live: Any) -> Any:
    ui = getattr(live, "ui", None)
    win = getattr(ui, "_win", None) or ui
    return getattr(win, "on_speech_command", None)


async def _await_lane(live: Any, *, timeout_s: float = _LANE_TIMEOUT_S) -> bool:
    """Wait (bounded) for the Live lane to reach an idle turn boundary.

    A segment may only own the lane after the current server turn has drained;
    submitting mid-turn would abort every ticket and advance nothing.
    """
    from jarvis.integrations import voice_speech
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    while time.monotonic() < deadline:
        try:
            if voice_speech.lane_idle(live) and voice_speech.turn_boundary_safe(live):
                return True
        except Exception:  # noqa: BLE001 - fail closed: never deliver blindly
            return False
        await asyncio.sleep(0.05)
    return False


def _tool_response(fc: Any, payload: dict) -> Any:
    from google.genai import types
    return types.FunctionResponse(
        id=str(getattr(fc, "id", "") or ""),
        name=str(getattr(fc, "name", "") or ""),
        response=dict(payload),
    )


# ── document explanation route ─────────────────────────────────────────────


async def route_document_explanation(live: Any, path: str, args: dict) -> dict:
    """Deliver an explicit document explanation on the coordinator lifecycle.

    Returns a FunctionResponse payload dict; the spoken cursor advances only
    after every segment's playback ticket verifies a drain.  All outcomes are
    honest — an unreadable file, a busy lane, or an aborted segment never
    claims the document was fully explained.
    """
    from jarvis.nlp.document_lifecycle import (
        DocumentExplanation,
        lifecycle_for_path,
    )
    lifecycle = await asyncio.to_thread(
        lifecycle_for_path, path, source="voice"
    )
    if lifecycle is None or lifecycle.segment_count() == 0:
        _emit(live, "voice.document.unreadable", path_hint=_hint(path))
        return {
            "result": "Dokumen tidak memiliki konten yang bisa dijelaskan.",
            "silent": True,
        }
    submitter = _speech_submitter(live)
    if not callable(submitter):
        _emit(live, "voice.document.no_submitter", path_hint=_hint(path))
        return {
            "result": "Jalur suara belum siap; penjelasan tidak dibacakan.",
            "silent": True,
        }
    if not await _await_lane(live):
        _emit(live, "voice.document.lane_busy", path_hint=_hint(path))
        return {
            "result": "Jalur suara sedang sibuk; penjelasan belum dibacakan.",
            "silent": True,
        }
    token = lifecycle.begin_request()
    explanation = DocumentExplanation(lifecycle, token)
    _emit(
        live,
        "voice.document.request",
        generation=token,
        path_hint=_hint(path),
        segments=lifecycle.segment_count(),
        cursor_before=lifecycle.resume_point(),
    )
    delivered = await explanation.deliver(submitter)
    if delivered:
        _emit(
            live,
            "voice.document.completed",
            generation=token,
            segments_verified=lifecycle.verified_count(),
            cursor_after=lifecycle.resume_point(),
        )
        return {
            "result": "Penjelasan dokumen selesai dibacakan per bagian.",
            "silent": True,
        }
    point = lifecycle.first_unverified()
    _emit(
        live,
        "voice.document.interrupted",
        generation=token,
        first_unverified=point,
        segments_verified=lifecycle.verified_count(),
        cursor_after=lifecycle.resume_point(),
    )
    report = lifecycle.interrupted_report() or (
        "Penjelasan terputus sebelum playback terverifikasi."
    )
    return {"result": report, "silent": True}


# ── video explanation route ────────────────────────────────────────────────


def _ffmpeg_available() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, timeout=3)
        return True
    except Exception:  # noqa: BLE001
        return False


def _transcribe_video(path: str) -> str:
    """Extract the video's audio track and transcribe it to text.

    Returns ``''`` on any honest failure (no ffmpeg, no audio track, empty
    transcript, or a transcription error) — never a fabricated explanation of
    visual content that was not actually transcribed.
    """
    if not _ffmpeg_available():
        return ""
    import tempfile
    tmp_path = Path(tempfile.mktemp(suffix=".mp3"))
    try:
        run = subprocess.run(
            ["ffmpeg", "-i", str(path), "-q:a", "0", "-map", "a",
             str(tmp_path), "-y"],
            capture_output=True, timeout=300,
        )
        if run.returncode != 0 or not tmp_path.exists() \
                or tmp_path.stat().st_size == 0:
            return ""
        from actions.file_processor import _process_audio
        result = _process_audio(tmp_path, "transcribe", {"save": False}, None)
        text = str(result or "").strip()
        if not text or text.startswith("Transcription failed"):
            return ""
        return text
    except Exception:  # noqa: BLE001
        return ""
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception as exc:  # noqa: BLE001 - temp cleanup is best-effort
            swallowed("voice.document.tmp_cleanup_failed", exc=exc)


async def route_video_explanation(live: Any, path: str, args: dict) -> dict:
    """Explain a video from a REAL audio transcript, failing honestly.

    A video is never pretended to be a text document: the explanation is
    built only from what a transcription actually produced, and a missing
    ffmpeg, missing audio track, or empty transcript yields an honest refusal
    rather than a claim of having explained the visuals.
    """
    from jarvis.nlp.document_lifecycle import (
        DocumentExplanation,
        DocumentLifecycle,
        safe_fingerprint,
    )
    if not _ffmpeg_available():
        _emit(live, "voice.document.video.no_ffmpeg", path_hint=_hint(path))
        return {
            "result": (
                "ffmpeg tidak tersedia, jadi saya tidak bisa mengekstrak "
                "audio video untuk menjelaskannya."
            ),
            "silent": True,
        }
    transcript = await asyncio.to_thread(_transcribe_video, path)
    if not transcript:
        _emit(live, "voice.document.video.no_transcript", path_hint=_hint(path))
        return {
            "result": (
                "Video tidak memiliki audio yang dapat ditranskripsi, jadi "
                "saya tidak mengklaim menjelaskan isi visualnya."
            ),
            "silent": True,
        }
    submitter = _speech_submitter(live)
    if not callable(submitter):
        _emit(live, "voice.document.no_submitter", path_hint=_hint(path))
        return {
            "result": "Jalur suara belum siap; transkrip video tidak dibacakan.",
            "silent": True,
        }
    if not await _await_lane(live):
        _emit(live, "voice.document.lane_busy", path_hint=_hint(path))
        return {
            "result": "Jalur suara sedang sibuk; transkrip video belum dibacakan.",
            "silent": True,
        }
    lifecycle = DocumentLifecycle(
        safe_fingerprint(path),
        str(os.path.basename(path))[:120],
        source="voice",
        _text=transcript,
    )
    token = lifecycle.begin_request()
    explanation = DocumentExplanation(lifecycle, token)
    _emit(
        live,
        "voice.document.video.request",
        generation=token,
        path_hint=_hint(path),
        segments=lifecycle.segment_count(),
        cursor_before=0,
    )
    delivered = await explanation.deliver(submitter)
    if delivered:
        _emit(
            live,
            "voice.document.completed",
            generation=token,
            segments_verified=lifecycle.verified_count(),
            cursor_after=lifecycle.resume_point(),
        )
        return {
            "result": "Penjelasan video selesai dibacakan per bagian.",
            "silent": True,
        }
    point = lifecycle.first_unverified()
    _emit(
        live,
        "voice.document.interrupted",
        generation=token,
        first_unverified=point,
        segments_verified=lifecycle.verified_count(),
        cursor_after=lifecycle.resume_point(),
    )
    return {
        "result": "Penjelasan video terputus sebelum playback terverifikasi.",
        "silent": True,
    }


# ── dispatch + install ─────────────────────────────────────────────────────


async def _route_file_processor(live: Any, fc: Any) -> Any | None:
    """Return a FunctionResponse when the call must be coordinator-owned."""
    args = dict(getattr(fc, "args", None) or {})
    given = str(args.get("file_path") or "").strip()
    resolved = given if (given and Path(given).exists()) else None
    if resolved is None:
        resolved = resolve_loaded_path(live, given)
    if not resolved or not Path(resolved).exists():
        return None
    suffix = Path(resolved).suffix.lower()
    intent = request_intent(args)
    if suffix in _DOCUMENT_EXTS and looks_explanation(intent):
        payload = await route_document_explanation(live, resolved, args)
        return _tool_response(fc, payload)
    if suffix in _VIDEO_EXTS and looks_explanation(intent):
        payload = await route_video_explanation(live, resolved, args)
        return _tool_response(fc, payload)
    return None


def install(legacy_module) -> bool:
    """Wrap ``JarvisLive._execute_tool`` on the editable seam (idempotent).

    - Routes explicit document/video explanation requests to the coordinator.
    - Rewrites a basename ``file_path`` to the resolved loaded path so the
      FROZEN handler and ``actions.file_processor`` see a real file.
    """
    live_cls = getattr(legacy_module, "JarvisLive", None)
    if live_cls is None:
        return False
    if getattr(live_cls, _MARKER, False):
        return False
    original_execute_tool = getattr(live_cls, "_execute_tool", None)
    if not callable(original_execute_tool):
        return False

    async def _execute_tool(self, fc):
        if getattr(fc, "name", None) == "file_processor":
            routed = await _route_file_processor(self, fc)
            if routed is not None:
                return routed
            args = dict(getattr(fc, "args", None) or {})
            given = str(args.get("file_path") or "").strip()
            if given and not Path(given).exists():
                resolved = resolve_loaded_path(self, given)
                if resolved:
                    try:
                        fc.args = {**args, "file_path": resolved}
                    except Exception as exc:  # noqa: BLE001 - immutable FC
                        swallowed("voice.document.args_rewrite_failed", exc=exc)
        return await original_execute_tool(self, fc)

    _execute_tool._jarvis_voice_document = True
    live_cls._execute_tool = _execute_tool
    setattr(live_cls, _MARKER, True)
    return True


__all__ = [
    "install",
    "loaded_file_candidates",
    "looks_explanation",
    "request_intent",
    "resolve_loaded_path",
    "route_document_explanation",
    "route_video_explanation",
]
