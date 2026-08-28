"""Screen Control-gated semantic right-click with no raw button control."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, ConfigDict, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession, desktop_safe_session


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str = Field(min_length=1, description="ID observasi UIA aktif")
    element_id: str = Field(min_length=1, description="ID elemen semantik")


class DesktopSafeRightClick(Tool):
    name = "desktop_safe_right_click"
    description = (
        "Klik kanan satu target UIA semantik dalam Screen Control aktif. Hanya "
        "menerima observation_id dan element_id; tombol dan koordinat ditentukan "
        "oleh executor tepercaya lalu action wajib diikuti recapture."
    )
    params_schema = _Params
    wants_context = True
    timeout_s = 30

    def __init__(self, *, session: SafeDesktopSession | None = None):
        self._session = session

    async def run(self, observation_id: str, element_id: str, _session=None,
                  _context=None, **_) -> ToolResult:
        from jarvis.agent.policy import screen_control_context_error

        context_error = screen_control_context_error(
            _context,
            capability="desktop_safe.desktop_safe_right_click",
            runtime_session=_session,
        )
        if context_error:
            return ToolResult.fail(context_error)
        authority = self._session or desktop_safe_session()
        owner = str(getattr(_session, "id", "") or "desktop-safe-right-click")
        outcome, error = await asyncio.to_thread(
            authority.right_click,
            str(observation_id),
            str(element_id),
            session_id=owner,
        )
        if outcome is None:
            return ToolResult.fail(error)
        if not outcome.ok:
            return ToolResult.fail(
                outcome.reason,
                executed=outcome.executed,
                verified=outcome.verified,
                after_observation_id=outcome.after.id if outcome.after else "",
            )
        return ToolResult.success(
            "Klik kanan semantik selesai dan recapture terverifikasi.",
            display="klik kanan desktop terverifikasi",
            executed=True,
            verified=True,
            after_observation_id=outcome.after.id if outcome.after else "",
        )


__all__ = ["DesktopSafeRightClick"]
