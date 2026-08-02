"""Bounded semantic scroll for desktop-local safe UIA sessions only."""
from __future__ import annotations

import asyncio
from typing import Literal

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession, desktop_safe_session


class _Params(BaseModel):
    observation_id: str = Field(min_length=1, description="ID observasi UIA aktif")
    element_id: str = Field(min_length=1, description="ID scroll container semantik")
    direction: Literal["down", "up"] = Field(description="Arah bounded scroll")


class DesktopSafeScroll(Tool):
    name = "desktop_safe_scroll"
    description = (
        "Scroll satu langkah kecil pada scrollbar UIA semantik dari observasi sesi "
        "desktop yang sama. Hanya menerima observation_id, element_id, dan arah; "
        "tanpa koordinat atau delta mentah. Recapture harus membuktikan state berubah."
    )
    params_schema = _Params
    wants_context = True
    timeout_s = 30

    def __init__(self, *, session: SafeDesktopSession | None = None):
        self._session = session

    async def run(self, observation_id: str, element_id: str,
                  direction: Literal["down", "up"], _session=None,
                  _context=None, **_) -> ToolResult:
        from jarvis.agent.policy import desktop_safe_context_error

        context_error = desktop_safe_context_error(
            _context, capability="desktop_safe.desktop_safe_scroll",
            runtime_session=_session,
        )
        if context_error:
            return ToolResult.fail(context_error)
        authority = self._session or desktop_safe_session()
        owner = str(getattr(_session, "id", "") or "desktop-safe-click")
        outcome, error = await asyncio.to_thread(
            authority.scroll,
            str(observation_id),
            str(element_id),
            direction=str(direction),
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
            "Scroll semantik selesai dan state UI terverifikasi berubah.",
            display="scroll desktop terverifikasi",
            executed=True,
            verified=True,
            after_observation_id=outcome.after.id if outcome.after else "",
        )


__all__ = ["DesktopSafeScroll"]
