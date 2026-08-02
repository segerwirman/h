"""Studio C: local stage toggle with reversible Focus Mode state."""
from __future__ import annotations


class StudioFocusController:
    """Owns Studio-only focus restoration; no generic desktop authority."""

    def __init__(self, stage, focus) -> None:
        self._stage = stage
        self._focus = focus
        self._prior_focus: bool | None = None

    def toggle(self) -> bool:
        opened = bool(self._stage.toggle("studio"))
        if opened:
            self._prior_focus = bool(self._focus.active)
            return True
        self.close()
        return False

    def close(self) -> None:
        """Restore only the Focus Mode state that Studio itself changed."""
        self._restore_focus()

    def set_studio_focus(self, active: bool) -> bool:
        if getattr(self._stage, "current", None) != "studio" or not isinstance(active, bool):
            return False
        if active and not self._focus.active:
            self._focus.activate()
        elif not active and self._focus.active:
            self._focus.deactivate()
        return bool(self._focus.active) is active

    def _restore_focus(self) -> None:
        if self._prior_focus is None:
            return
        if self._prior_focus and not self._focus.active:
            self._focus.activate()
        elif not self._prior_focus and self._focus.active:
            self._focus.deactivate()
        self._prior_focus = None


__all__ = ["StudioFocusController"]
