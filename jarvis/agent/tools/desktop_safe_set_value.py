"""One confirmed, bounded slider value change for a desktop-local UIA session."""
from __future__ import annotations

import asyncio
import math

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession, desktop_safe_session


class _Params(BaseModel):
    observation_id: str = Field(min_length=1, description="ID observasi UIA aktif")
    element_id: str = Field(min_length=1, description="ID slider UIA semantik")
    value: float = Field(
        allow_inf_nan=False,
        description="Nilai numerik finite dalam domain slider yang diterbitkan",
    )


class DesktopSafeSetValue(Tool):
    """Set one observed slider value; registry confirmation is always required."""

    name = "desktop_safe_set_value"
    description = (
        "Ubah tepat satu nilai slider UIA semantik dari observasi sesi desktop yang sama. "
        "Hanya menerima observation_id, element_id, dan nilai numerik; nilai harus berada "
        "dalam domain slider yang diterbitkan. Konfirmasi user dan recapture UIA wajib."
    )
    params_schema = _Params
    requires_confirmation = True
    wants_context = True
    timeout_s = 30

    def __init__(self, *, session: SafeDesktopSession | None = None):
        self._session = session

    def confirmation_text(self, *, value: float, **_) -> str:
        return f"Izinkan mengubah satu nilai slider desktop menjadi {float(value):g}?"

    async def run(self, observation_id: str, element_id: str, value: float,
                  _session=None, _context=None,
                  _desktop_safe_confirmation: bool = False, **_) -> ToolResult:
        from jarvis.agent.policy import desktop_safe_context_error

        context_error = desktop_safe_context_error(
            _context, capability="desktop_safe.desktop_safe_set_value",
            runtime_session=_session,
        )
        if context_error:
            return ToolResult.fail(context_error)
        if not _desktop_safe_confirmation:
            return ToolResult.fail("desktop_safe_set_value membutuhkan permit konfirmasi registry")
        try:
            requested = float(value)
        except (TypeError, ValueError):
            return ToolResult.fail("nilai slider harus numerik finite")
        if not math.isfinite(requested):
            return ToolResult.fail("nilai slider harus numerik finite")
        authority = self._session or desktop_safe_session()
        owner = str(getattr(_session, "id", "") or "desktop-safe-set-value")
        outcome, error = await asyncio.to_thread(
            authority.set_value,
            str(observation_id),
            str(element_id),
            requested,
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
            "Nilai slider desktop diubah dan diverifikasi melalui recapture UIA.",
            display="nilai slider desktop terverifikasi",
            executed=True,
            verified=True,
            after_observation_id=outcome.after.id if outcome.after else "",
        )


__all__ = ["DesktopSafeSetValue"]
