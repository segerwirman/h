"""Fail-open UI teardown bridge for desktop-safe observations.

The UI window source stays untouched. Installation wraps only ``closeEvent``;
when unavailable or failing, the legacy close path always continues.
"""
from __future__ import annotations


def install(window_class) -> bool:
    """Idempotently revoke all desktop-safe refs before legacy window close."""
    if getattr(window_class, "_jarvis_desktop_safe_teardown", False):
        return True
    original = getattr(window_class, "closeEvent", None)
    if not callable(original):
        return False

    def close_event(self, event):
        try:
            desktop_safe_session().clear_all()
        except Exception:
            pass
        return original(self, event)

    window_class.closeEvent = close_event
    window_class._jarvis_desktop_safe_teardown = True
    return True


def desktop_safe_session():
    from jarvis.agent.tools.desktop_safe_click import desktop_safe_session as resolve
    return resolve()


__all__ = ["install"]
