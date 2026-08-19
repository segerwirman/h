"""Tugas latar untuk sesi Gemini Live — TANPA mengubah main.py (FROZEN).

AUDIT_REPORT §8.4 meminta empat perubahan di ``main.py``. Berkas itu FROZEN
(``config/frozen_manifest.json``), jadi ketiganya dikerjakan lewat seam yang
SUDAH terbukti dipakai ``jarvis.integrations.google_voice``: menyuntik
``TOOL_DECLARATIONS`` in-place dan membungkus method ``JarvisLive``.

    §8.4c  4 tool baru   → declarations() + wrapper _execute_tool
    §8.4b  antrean batas-giliran → BUS ``task.finished`` → flusher asinkron
    §8.4d  aturan [MULTI-TASKING] → wrapper _load_system_prompt

``core/prompt.txt`` **tidak disentuh sama sekali** — persona milik user tetap
byte-identik; aturan multi-tasking ditambahkan di memori saat sesi dibangun.

§8.4a ("cabut gate") sengaja TIDAK dikerjakan: audit putaran 2 membuktikan
gate itu berlaku satu giliran (~2,5 detik), bukan 900 detik, dan dengan
``task_start`` tersedia sebagai tool Live biasa rute berat tidak lagi diklaim
untuk tugas panjang — sehingga gate-nya tidak pernah menyala.
"""
from __future__ import annotations

import asyncio
import re
import threading
from collections import deque

from jarvis.agent.interaction import sanitize_for_speech
from jarvis.core import config, log
from jarvis.core.bus import BUS

_logger = log.get("voice.tasks")

TASK_TOOL_NAMES = frozenset({
    "task_start", "task_status", "task_cancel", "task_result"})

_MULTITASKING_RULES = """

[MULTI-TASKING]
- Apa pun yang butuh lebih dari ~5 detik → task_start, jangan dikerjakan inline.
- Setelah task_start, KONFIRMASI singkat lalu LANJUTKAN percakapan normal.
  Jangan pernah menggantung user dengan "tunggu sebentar" lalu diam.
- Kalau user memberi perintah baru saat ada tugas berjalan: kerjakan yang baru.
  Jangan antre, jangan tolak, jangan minta user menunggu.
- User bertanya "sudah sampai mana" → task_status, jawab dengan progres nyata.
- Tugas selesai di tengah obrolan → sampaikan SATU kalimat, lalu kembali ke
  topik yang sedang dibahas. Jangan bacakan seluruh hasil kecuali diminta.
- Maksimal {max_tasks} tugas bersamaan. Yang berikutnya → beri tahu user dan
  tawarkan antre.
"""

_notices: deque[tuple[str, str]] = deque()
_notices_lock = threading.Lock()
_notice_ids: set[str] = set()
_notice_inflight: tuple[str, str] | None = None
_subscribed = False

_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_ -]?key|authorization|bearer|password|passwd|secret|token|otp|pin|cvv)"
    r"\s*[:=]\s*([^\s,;]+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_SK_SECRET_RE = re.compile(r"(?<!\w)sk-[A-Za-z0-9_-]{8,}")
_PRIVATE_PATH_RE = re.compile(
    r"(?i)(?:file:///|\\\\|(?<!\w)[A-Za-z]:[\\/])[^\s<>|?*\"]+"
)


def _safe_notice_text(value: object, limit: int) -> str:
    """Bound task speech and remove values unsafe for the remote Live lane."""
    text = str(value or "")
    text = _BEARER_RE.sub("credential [REDACTED]", text)
    text = _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", text
    )
    text = _SK_SECRET_RE.sub("[REDACTED]", text)
    text = _PRIVATE_PATH_RE.sub("[private path]", text)
    return sanitize_for_speech(text, limit)


# ── §8.4c — schema tool ke sesi Live ─────────────────────────────────────

def declarations() -> list[dict]:
    """Schema keempat tool, diambil dari registry nyata (bukan salinan manual)."""
    from jarvis.agent import registry, toolgroups
    from jarvis.integrations.google_voice import _gemini_schema

    out: list[dict] = []
    disabled = sorted(toolgroups.disabled_tool_names())
    for schema in registry.schemas(allowed=sorted(TASK_TOOL_NAMES),
                                   exclude=disabled):
        fn = schema.get("function") or {}
        if fn.get("name"):
            out.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": _gemini_schema(fn.get("parameters") or {
                    "type": "object", "properties": {}}),
            })
    return out


def apply_to_prompt(base: str) -> str:
    """Tambahkan aturan multitasking tepat sekali tanpa mengubah persona."""
    if "[MULTI-TASKING]" in base:
        return base
    try:
        from jarvis.agent.tasks import REGISTRY
        max_tasks = REGISTRY.max_concurrent
    except Exception:                                # noqa: BLE001
        max_tasks = 3
    return base + _MULTITASKING_RULES.format(max_tasks=max_tasks)


def ensure_subscribed() -> None:
    """Subscribe completion notices once for the process lifetime."""
    global _subscribed
    if _subscribed:
        return
    BUS.subscribe("task.finished", _on_task_finished)
    _subscribed = True


# ── §8.4b — antrean batas-giliran ────────────────────────────────────────

def _on_task_finished(data: dict) -> None:
    """Dipanggil dari thread worker agent. TIDAK pernah menyela.

    Notice hanya diantre di sini; pengirimannya menunggu batas giliran yang
    aman supaya hasil tugas tidak memotong Jarvis di tengah kalimat.
    """
    task = dict(data.get("task") or {})
    source = str(task.get("source", "") or "")
    if source not in {"voice-native", "voice-task-tool"}:
        return              # never leak typed/remote/headless task into Live
    tid = str(task.get("id", ""))
    if tid:
        from jarvis.agent import conversation_context
        conversation_context.STORE.end_task(
            conversation_context.AUDIO_CONVERSATION_ID, tid
        )
    if not bool(config.get("ui.task_deck.speak_on_complete", True)):
        return
    if str(task.get("completion_owner", "registry")) != "registry":
        return                          # caller callback owns terminal speech
    status = str(task.get("status", ""))
    if status not in ("done", "failed"):
        return                                   # cancelled → user sudah tahu
    title = _safe_notice_text(task.get("title", ""), 160) or "tugas latar"
    if status == "failed":
        body = f"GAGAL: {_safe_notice_text(task.get('error', ''), 600)}"
    else:
        body = _safe_notice_text(task.get("result", ""), 1200)
    notice = (
        f"[TASK_DONE id={tid}] {title}\n{body}\n"
        "Sampaikan hasilnya dalam SATU kalimat singkat, lalu langsung "
        "kembali ke topik yang sedang dibicarakan user."
    )
    with _notices_lock:
        if tid and tid in _notice_ids:
            return
        _notices.append((tid, notice))
        if tid:
            _notice_ids.add(tid)


def pending_notices() -> int:
    with _notices_lock:
        return len(_notices) + int(_notice_inflight is not None)


def clear_notices() -> None:
    global _notice_inflight
    with _notices_lock:
        _notices.clear()
        _notice_ids.clear()
        _notice_inflight = None


def _boundary_is_safe(live) -> bool:
    """Require an authoritative server/text or local audible turn boundary."""
    from jarvis.integrations import voice_speech

    return voice_speech.notice_lane_idle(live)


def _settle_notice(ticket, task_id: str, notice: str) -> None:
    global _notice_inflight
    with _notices_lock:
        if _notice_inflight != (task_id, notice):
            return
        _notice_inflight = None
        if ticket.completed:
            if task_id:
                _notice_ids.discard(task_id)
            return
        # Submission diterima tetapi playback dapat gagal kemudian (reconnect,
        # interrupt, atau output device hilang). Ownership tetap milik task yang
        # sama dan notice kembali ke depan sampai drain benar-benar terverifikasi.
        _notices.appendleft((task_id, notice))


async def flush_notices(live) -> int:
    """Submit at most one completion through the playback-aware Live lane."""
    global _notice_inflight
    from jarvis.integrations import voice_speech

    if not _boundary_is_safe(live):
        return 0
    with _notices_lock:
        if _notice_inflight is not None or not _notices:
            return 0
        task_id, notice = _notices.popleft()
        _notice_inflight = (task_id, notice)

    boundary = int(getattr(live, "_voice_turn_boundary_epoch", 0) or 0)
    if not voice_speech.claim_turn_boundary(live):
        with _notices_lock:
            if _notice_inflight == (task_id, notice):
                _notice_inflight = None
                _notices.appendleft((task_id, notice))
        return 0

    ticket = voice_speech.submit_exact(live, notice, exact=False)
    if ticket.aborted:
        voice_speech.release_turn_boundary(live, boundary)
        _settle_notice(ticket, task_id, notice)
        return 0
    ticket.add_done_callback(
        lambda done: (
            voice_speech.release_turn_boundary(live, boundary)
            if done.aborted else None,
            _settle_notice(done, task_id, notice),
        )
    )
    return 1


async def _notice_loop(live, interval: float = 0.25) -> None:
    while True:
        try:
            await asyncio.sleep(interval)
            # Task completions own the first chance. Generic local-action
            # notices then use the same lane and boundary, so a notification
            # that arrived while PCM was playing is retried automatically after
            # the playback owner records its local drain.
            await flush_notices(live)
            from jarvis.integrations import voice_notices
            await voice_notices.flush_at_turn_boundary(live)
        except asyncio.CancelledError:
            return
        except Exception as exc:                             # noqa: BLE001
            _logger.warning("voice.tasks.loop_error", error=str(exc)[:120])


def compose_run(original_run):
    """Wrap ``JarvisLive.run`` with one task notice flusher."""
    if getattr(original_run, "_jarvis_task_flusher", False):
        return original_run

    async def wrapped_run(self):
        from jarvis.integrations import voice_speech

        flusher = asyncio.create_task(_notice_loop(self),
                                      name="task-notice-flusher")
        try:
            return await original_run(self)
        finally:
            # The frozen run loop owns reconnect and TaskGroup teardown. Its
            # outer composed boundary makes any accepted speech ticket terminal
            # before this flusher disappears.
            voice_speech.abort(self)
            flusher.cancel()

    wrapped_run._jarvis_task_flusher = True
    return wrapped_run


__all__ = [
    "apply_to_prompt", "compose_run", "declarations", "ensure_subscribed",
    "pending_notices", "clear_notices", "flush_notices", "TASK_TOOL_NAMES",
]
