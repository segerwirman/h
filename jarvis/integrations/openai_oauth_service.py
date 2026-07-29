"""Non-blocking OpenAI OAuth login orchestration for desktop surfaces."""
from __future__ import annotations

import threading
from collections.abc import Callable

from jarvis.integrations import openai_oauth

_lock = threading.Lock()
_running = False


def _safe_state(state: str, *, error: str = "") -> dict:
    status = openai_oauth.status()
    return {
        "state": state,
        "connected": bool(status.get("connected")),
        "needs_reauth": bool(status.get("needs_reauth")),
        "token_refresh_due": bool(status.get("token_refresh_due")),
        "error": error,
    }


def start(on_update: Callable[[dict], None] | None = None) -> dict:
    """Start browser OAuth in a daemon worker; returns immediately."""
    global _running
    callback = on_update or (lambda _state: None)
    with _lock:
        if _running:
            return _safe_state("callback_pending")
        _running = True

    initial = _safe_state("browser_open")

    def run() -> None:
        global _running
        try:
            # start_login() persists the token and resets provider clients.
            openai_oauth.start_login()
            callback(_safe_state("connected"))
        except Exception:  # OAuth details may contain provider data.
            callback(_safe_state("failed", error="login gagal"))
        finally:
            with _lock:
                _running = False

    threading.Thread(target=run, daemon=True, name="openai-oauth-login").start()
    return initial


def status() -> dict:
    return _safe_state("callback_pending" if _running else "idle")
