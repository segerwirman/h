"""Eksekutor tunggal aksi L0/L1 untuk voice dan input teks."""
from __future__ import annotations

import asyncio
from typing import Any

from jarvis.core.action_registry import Action
from jarvis.integrations import voice_notices

_SUPPORTED_SYSTEM = frozenset({"volume_up", "volume_down", "volume_mute"})


def can_execute(action: Action) -> bool:
    if action.kind == "app":
        return action.verb in {"open", "close"} and bool(action.args.get("app"))
    return action.kind == "system" and action.target in _SUPPORTED_SYSTEM


def confirmation(action: Action) -> str:
    if action.kind == "app":
        label = str(action.args.get("app") or action.target)
        return f"{'Membuka' if action.verb == 'open' else 'Menutup'} {label}."
    return {
        "volume_up": "Volume dinaikkan.",
        "volume_down": "Volume diturunkan.",
        "volume_mute": "Audio di-mute.",
    }[action.target]


def _work(action: Action) -> str:
    if action.kind == "app" and action.verb == "open":
        from actions.open_app import launch_application

        outcome = launch_application(str(action.args["app"]))
        return outcome.message
    elif action.kind == "app":
        from actions.close_app import close_app

        # "Tutup WhatsApp/Chrome" means the application, not one arbitrary
        # renderer/window.  The named-app guard still prevents Jarvis from
        # closing itself, while graceful WM_CLOSE remains the first attempt.
        outcome = close_app(
            str(action.args["app"]),
            all_windows=bool(action.args.get("all_windows", True)),
        )
        return outcome.message
    else:
        from actions import computer_settings
        getattr(computer_settings, action.target)()
        return confirmation(action)


async def submit(action: Action, _context: Any = None) -> str:
    """Execute bounded OS work and return its real, verified outcome.

    The old fire-and-forget task acknowledged success before the launcher or
    close operation had even run.  Awaiting the worker costs only the bounded
    local action time and prevents Jarvis from saying an app was closed when
    it was still running or waiting on a save dialog.
    """
    if not can_execute(action):
        raise ValueError("unsupported_local_action")
    result = await asyncio.to_thread(_work, action)
    voice_notices.remember_action(action)
    return str(result or confirmation(action))


__all__ = ["can_execute", "confirmation", "submit"]
