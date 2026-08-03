"""UIAdapter — jembatan agent → UI Jarvis (FROZEN, hanya DIPANGGIL).

Semua keluaran lewat API publik MainWindow yang sudah thread-safe
(``write_log`` → _log_sig) dan BUS. Konfirmasi memakai topik BUS yang sudah
ada: ``confirm`` / ``cancel``.
"""
from __future__ import annotations

import threading
import weakref
from concurrent.futures import Future

from jarvis.core import config, log
from jarvis.core.bus import BUS
from jarvis.agent.adapters.base import Adapter

_logger = log.get("agent.adapter.ui")

_win_ref = None                    # weakref ke MainWindow
_vision_ref = None                 # weakref ke VisionSystem
_pending_lock = threading.Lock()
_pending: Future | None = None
_bus_bound = False


def register_ui(win, vision=None) -> None:
    """Dipanggil sekali dari wiring window — simpan referensi lemah."""
    global _win_ref, _vision_ref, _bus_bound
    _win_ref = weakref.ref(win)
    if vision is not None:
        _vision_ref = weakref.ref(vision)
    if not _bus_bound:
        _bus_bound = True
        BUS.subscribe("confirm", lambda d: _resolve("Lanjut"))
        BUS.subscribe("cancel", lambda d: _resolve("Batal"))
    _logger.info("agent.ui_registered")


def current_window():
    return _win_ref() if _win_ref is not None else None


def current_vision_system():
    v = _vision_ref() if _vision_ref is not None else None
    if v is not None:
        return v
    win = current_window()
    return getattr(win, "vision", None) if win is not None else None


def ask_active() -> bool:
    """True selama agent menunggu jawaban confirm/cancel dari user."""
    with _pending_lock:
        return _pending is not None and not _pending.done()


def _resolve(answer: str) -> None:
    global _pending
    with _pending_lock:
        fut, _pending = _pending, None
    if fut is not None and not fut.done():
        fut.set_result(answer)


class UIAdapter(Adapter):
    name = "ui"
    interactive = True
    desktop_local = True

    def __init__(self, win=None):
        if win is not None:
            register_ui(win)
        from jarvis.agent.progress_narrator import ProgressNarrator
        from jarvis.core import config as _config
        self._narrator = ProgressNarrator(
            min_interval_s=float(_config.get(
                "agent.interaction.progress_min_interval_s", 12.0)),
            max_spoken=int(_config.get(
                "agent.interaction.progress_max_spoken", 4)),
        )

    def _win(self):
        return current_window()

    async def send(self, content: str, **kwargs) -> None:
        win = self._win()
        if win is None:
            return
        text = content if len(content) <= 700 else content[:700] + " …"
        win.write_log(f"Jarvis: {text}")

    async def progress(self, text: str) -> None:
        win = self._win()
        if win is None:
            return
        # Selalu tampilkan di terminal panel supaya user MELIHAT proses.
        win.write_log(f"SYS: {text}")
        # Hadir sebagai lawan bicara: menyela sesekali dengan progres natural,
        # di-throttle agar tidak spam. Diam total dianggap 'menghilang'.
        try:
            from jarvis.agent.progress_narrator import phrase_for
            phrase = phrase_for(text)
            if self._narrator.should_speak(phrase) and hasattr(win, "_speak_line"):
                win._speak_line(phrase)
        except Exception:                                    # noqa: BLE001
            pass

    async def ask(self, question: str,
                  options: list[str] | None = None) -> str | None:
        global _pending
        win = self._win()
        if win is None:
            return None
        fut: Future = Future()
        with _pending_lock:
            _resolve_stale = _pending
            _pending = fut
        if _resolve_stale is not None and not _resolve_stale.done():
            _resolve_stale.set_result(None)

        opts = f" [{' / '.join(options)}]" if options else ""
        win.write_log(f"AGENT ? {question}{opts} — ketik 'confirm' "
                      f"untuk lanjut atau 'cancel' untuk batal.")
        BUS.publish("agent.ask", question=question, options=options or [])
        if hasattr(win, "_speak_line"):
            try:
                win._speak_line("Saya butuh konfirmasi Anda, sir.")
            except Exception:                                # noqa: BLE001
                pass

        import asyncio
        timeout = float(config.get("agent.confirm_timeout_s", 300))
        try:
            return await asyncio.get_event_loop().run_in_executor(
                None, lambda: fut.result(timeout=timeout))
        except Exception:                                    # noqa: BLE001
            with _pending_lock:
                if _pending is fut:
                    _pending = None
            win.write_log("SYS: konfirmasi agent kedaluwarsa — dibatalkan.")
            return None

    async def send_image(self, path: str, caption: str = "") -> None:
        win = self._win()
        if win is None:
            return
        clean = str(path or "").strip()
        # Ingat artefak terakhir agar "buka gambar itu / tampilkan hasilnya"
        # dapat langsung membukanya (desktop-local, tidak masuk memory durable).
        try:
            from jarvis.agent import conversation_context
            kind = "image" if clean.lower().rsplit(".", 1)[-1] in {
                "png", "jpg", "jpeg", "webp", "gif", "bmp"} else "file"
            conversation_context.STORE.remember_artifact(
                "typed-desktop", path=clean, kind=kind)
            conversation_context.STORE.remember_artifact(
                "voice", path=clean, kind=kind)
        except Exception:                                    # noqa: BLE001
            pass
        # Tampilkan gambar di ContentStage bila API tersedia; selalu log path.
        shown = False
        show = getattr(win, "show_image", None)
        if callable(show):
            try:
                show(clean, caption)
                shown = True
            except Exception:                                # noqa: BLE001
                shown = False
        if not shown:
            win.write_log(f"SYS: gambar tersimpan — {clean} {caption}".rstrip())

    async def native_action(self, action: str, **kwargs) -> bool:
        """Marshal agent-owned local actions onto Qt's UI thread."""

        win = self._win()
        if win is None:
            return False
        if action == "camera_open":
            win._vision_sig.emit(True)
            return True
        if action == "camera_close":
            win._vision_sig.emit(False)
            return True
        return False
