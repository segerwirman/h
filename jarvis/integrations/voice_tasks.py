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
import threading
from collections import deque

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

_legacy = None
_notices: deque[str] = deque()
_notices_lock = threading.Lock()
_subscribed = False


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


def sync_installed_declarations() -> None:
    if _legacy is None:
        return
    current = [item for item in _legacy.TOOL_DECLARATIONS
               if item.get("name") not in TASK_TOOL_NAMES]
    _legacy.TOOL_DECLARATIONS[:] = [*current, *declarations()]


# ── §8.4b — antrean batas-giliran ────────────────────────────────────────

def _on_task_finished(data: dict) -> None:
    """Dipanggil dari thread worker agent. TIDAK pernah menyela.

    Notice hanya diantre di sini; pengirimannya menunggu batas giliran yang
    aman supaya hasil tugas tidak memotong Jarvis di tengah kalimat.
    """
    if not bool(config.get("ui.task_deck.speak_on_complete", True)):
        return
    task = dict(data.get("task") or {})
    status = str(task.get("status", ""))
    if status not in ("done", "failed"):
        return                                   # cancelled → user sudah tahu
    tid = str(task.get("id", ""))
    title = str(task.get("title", "")) or "tugas latar"
    if status == "failed":
        body = f"GAGAL: {str(task.get('error', ''))[:600]}"
    else:
        body = str(task.get("result", ""))[:1200]
    notice = (
        f"[TASK_DONE id={tid}] {title}\n{body}\n"
        "Sampaikan hasilnya dalam SATU kalimat singkat, lalu langsung "
        "kembali ke topik yang sedang dibicarakan user."
    )
    with _notices_lock:
        _notices.append(notice)


def pending_notices() -> int:
    with _notices_lock:
        return len(_notices)


def clear_notices() -> None:
    with _notices_lock:
        _notices.clear()


def _boundary_is_safe(live) -> bool:
    """Aman = giliran model sudah selesai DAN Jarvis tidak sedang bicara."""
    if getattr(live, "session", None) is None:
        return False
    event = getattr(live, "_turn_done_event", None)
    if event is None or not event.is_set():
        return False
    lock = getattr(live, "_speaking_lock", None)
    if lock is None:
        return not getattr(live, "_is_speaking", False)
    with lock:
        return not live._is_speaking


async def flush_notices(live) -> int:
    """Kirim notice yang tertunda bila batas giliran aman. Return jumlahnya."""
    sent = 0
    while True:
        if not _boundary_is_safe(live):
            return sent
        with _notices_lock:
            if not _notices:
                return sent
            notice = _notices.popleft()
        try:
            await live.session.send_client_content(
                turns={"parts": [{"text": notice}]}, turn_complete=True)
            sent += 1
        except Exception as exc:                             # noqa: BLE001
            _logger.warning("voice.tasks.notice_failed", error=str(exc)[:120])
            return sent


async def _notice_loop(live, interval: float = 0.25) -> None:
    while True:
        try:
            await asyncio.sleep(interval)
            await flush_notices(live)
        except asyncio.CancelledError:
            return
        except Exception as exc:                             # noqa: BLE001
            _logger.warning("voice.tasks.loop_error", error=str(exc)[:120])


# ── pemasangan ───────────────────────────────────────────────────────────

def install(legacy_module) -> None:
    """Pasang sekali pada modul root ``main`` yang diimpor READ/WRAP only."""
    global _legacy, _subscribed
    _legacy = legacy_module
    sync_installed_declarations()

    if not _subscribed:
        BUS.subscribe("task.finished", _on_task_finished)
        _subscribed = True

    # §8.4d — aturan multi-tasking tanpa menyentuh core/prompt.txt
    original_prompt = getattr(legacy_module, "_load_system_prompt", None)
    if original_prompt is not None and not getattr(
            original_prompt, "_jarvis_tasks_wrapper", False):
        def _with_rules() -> str:
            base = original_prompt()
            if "[MULTI-TASKING]" in base:
                return base
            try:
                from jarvis.agent.tasks import REGISTRY
                max_tasks = REGISTRY.max_concurrent
            except Exception:                                # noqa: BLE001
                max_tasks = 3
            return base + _MULTITASKING_RULES.format(max_tasks=max_tasks)

        _with_rules._jarvis_tasks_wrapper = True
        legacy_module._load_system_prompt = _with_rules

    cls = legacy_module.JarvisLive

    # §8.4c — eksekusi tool task_* lewat registry
    original_exec = cls._execute_tool
    if not getattr(original_exec, "_jarvis_tasks_wrapper", False):
        async def wrapped_exec(self, fc):
            name = str(getattr(fc, "name", ""))
            if name not in TASK_TOOL_NAMES:
                return await original_exec(self, fc)
            from jarvis.agent import registry

            args = dict(getattr(fc, "args", None) or {})
            result = await registry.execute(name, args)
            return legacy_module.types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": result.for_llm(), "ok": result.ok,
                          "error": result.error or ""},
            )

        wrapped_exec._jarvis_tasks_wrapper = True
        cls._execute_tool = wrapped_exec

    # §8.4b — flusher hidup selama sesi Live hidup
    original_run = cls.run
    if not getattr(original_run, "_jarvis_tasks_wrapper", False):
        async def wrapped_run(self):
            flusher = asyncio.create_task(_notice_loop(self),
                                          name="task-notice-flusher")
            try:
                return await original_run(self)
            finally:
                flusher.cancel()

        wrapped_run._jarvis_tasks_wrapper = True
        cls.run = wrapped_run
