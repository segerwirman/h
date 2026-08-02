"""Toggle one already-observed binary UIA checkbox."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession, desktop_safe_session


class _Params(BaseModel):
    observation_id: str = Field(min_length=1, description="ID observasi UIA aktif")
    element_id: str = Field(min_length=1, description="ID checkbox UIA semantik")


class DesktopSafeToggle(Tool):
    """Toggle exactly one visible binary checkbox; never clicks or sends keys."""

    name = "desktop_safe_toggle"
    description = (
        "Ubah satu checkbox UIA biner yang sudah terlihat dalam observasi sesi desktop "
        "yang sama. Hanya menerima observation_id dan element_id opaque; tidak menerima "
        "label/state bebas, memakai koordinat, click, atau keyboard."
    )
    params_schema = _Params
    requires_confirmation = True
    wants_context = True
    timeout_s = 30

    def confirmation_text(self, **_) -> str:
        return "Izinkan mengubah satu checkbox desktop yang sudah terlihat?"

    def __init__(self, *, session: SafeDesktopSession | None = None):
        self._session = session

    async def run(self, observation_id: str, element_id: str, _session=None,
                  _context=None, _desktop_safe_confirmation: bool = False,
                  **_) -> ToolResult:
        from jarvis.agent.policy import desktop_safe_context_error

        context_error = desktop_safe_context_error(
            _context, capability="desktop_safe.desktop_safe_toggle",
            runtime_session=_session,
        )
        if context_error:
            return ToolResult.fail(context_error)
        if not _desktop_safe_confirmation:
            return ToolResult.fail("desktop_safe_toggle membutuhkan permit konfirmasi registry")
        authority = self._session or desktop_safe_session()
        owner = str(getattr(_session, "id", "") or "desktop-safe-toggle")
        outcome, error = await asyncio.to_thread(
            authority.toggle, str(observation_id), str(element_id), session_id=owner,
        )
        if outcome is None:
            return ToolResult.fail(error)
        if not outcome.ok:
            return ToolResult.fail(outcome.reason, executed=outcome.executed,
                                   verified=outcome.verified,
                                   after_observation_id=outcome.after.id if outcome.after else "")
        return ToolResult.success(
            "Checkbox desktop diubah dan diverifikasi melalui recapture UIA.",
            display="checkbox desktop terverifikasi", executed=True, verified=True,
            after_observation_id=outcome.after.id if outcome.after else "",
        )


__all__ = ["DesktopSafeToggle"]
