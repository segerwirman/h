"""Voice reply flow (Mark L Change 1.5) — fill + send via DOM injection.

State machine: IDLE → COMPOSING (field filled) → CONFIRM (awaiting spoken
"ya/kirim") → SEND. Sending ALWAYS requires explicit confirmation; "batal"
anywhere aborts. Every transition is logged. JS templates live in config.yaml
(notifications.reply) — best-effort selectors, page-dependent.
"""
from __future__ import annotations

import json
from enum import Enum
from typing import Callable

from jarvis.core import config, log

_logger = log.get("browser.reply")

_CONFIRM_WORDS = ("ya", "iya", "kirim", "kirim sekarang", "send", "send now",
                  "yes", "lanjut")
_CANCEL_WORDS = ("batal", "tidak", "jangan", "cancel", "no", "batalkan")


class ReplyState(str, Enum):
    IDLE = "IDLE"
    COMPOSING = "COMPOSING"
    CONFIRM = "CONFIRM"


class ReplyFlow:
    """Drives QWebEnginePage.runJavaScript; owns no widgets."""

    def __init__(self, run_js: Callable, notify: Callable[[str], None]):
        self._run_js = run_js          # (js, callback) → None
        self._notify = notify          # UI/voice feedback line
        self.state = ReplyState.IDLE
        self._text = ""

    # ── entry points (called from the UI thread) ─────────────────────────────

    def begin(self, text: str) -> None:
        """'balas <text>' — fill the reply field, then ask for confirmation."""
        self._text = text.strip()
        if not self._text:
            self._notify("Isi balasan kosong, sir.")
            return
        self.state = ReplyState.COMPOSING
        _logger.info("reply.compose", chars=len(self._text))
        fill = config.get("notifications.reply.fill_js", "")
        js = fill.replace("%TEXT%", json.dumps(self._text))
        self._run_js(js, self._on_filled)

    def handle_utterance(self, text: str) -> bool:
        """Route a user utterance while the flow is active.
        Returns True when the utterance was consumed."""
        if self.state != ReplyState.CONFIRM:
            return False
        t = text.strip().lower().rstrip("?.!,")
        if any(t == w or t.startswith(w + " ") for w in _CANCEL_WORDS):
            self.cancel()
            return True
        if any(t == w or t.startswith(w) for w in _CONFIRM_WORDS):
            self._send()
            return True
        return False

    def cancel(self) -> None:
        if self.state != ReplyState.IDLE:
            _logger.info("reply.cancelled", state=self.state.value)
            self._notify("Balasan dibatalkan, sir.")
        self.state = ReplyState.IDLE
        self._text = ""

    # ── internals ────────────────────────────────────────────────────────────

    def _on_filled(self, result) -> None:
        if result != "filled":
            _logger.warning("reply.fill_failed", result=str(result)[:60])
            self._notify("Saya tidak menemukan kolom balasan di halaman ini.")
            self.state = ReplyState.IDLE
            return
        self.state = ReplyState.CONFIRM
        _logger.info("reply.filled_awaiting_confirm")
        self._notify(f"Balasan tertulis: “{self._text[:120]}”. "
                     "Kirim sekarang, sir?")

    def _send(self) -> None:
        _logger.info("reply.send_confirmed")
        self._run_js(config.get("notifications.reply.send_js", ""),
                     self._on_sent)

    def _on_sent(self, result) -> None:
        if result == "sent":
            _logger.info("reply.sent")
            self._notify("Balasan terkirim, sir.")
        else:
            _logger.warning("reply.send_failed", result=str(result)[:60])
            self._notify("Tombol kirim tidak ditemukan — silakan kirim manual.")
        self.state = ReplyState.IDLE
        self._text = ""
