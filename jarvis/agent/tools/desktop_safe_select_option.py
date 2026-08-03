"""Select one already-observed visible UIA dropdown option."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession, desktop_safe_session


class _Params(BaseModel):
    observation_id: str = Field(min_length=1, description="ID observasi UIA aktif")
    element_id: str = Field(min_length=1, description="ID option dropdown UIA semantik")


class DesktopSafeSelectOption(Tool):
    """Select exactly one visible option; never opens dropdowns or sends keys."""

    name = "desktop_safe_select_option"
    description = (
        "Pilih tepat satu option dropdown UIA yang sudah terlihat dalam observasi sesi "
        "desktop yang sama. Hanya menerima observation_id dan element_id opaque; tidak "
        "membuka dropdown, menerima label/index, memakai koordinat, atau mengirim keyboard."
    )
    params_schema = _Params
    requires_confirmation = True
    wants_context = True
    timeout_s = 30

    def confirmation_text(self, **_) -> str:
        return "Izinkan memilih satu option dropdown desktop yang sudah terlihat?"

    def __init__(self, *, session: SafeDesktopSession | None = None):
        self._session = session

    async def run(self, observation_id: str, element_id: str, _session=None,
                  _context=None, _desktop_safe_confirmation: bool = False,
                  **_) -> ToolResult:
        from jarvis.agent.policy import desktop_safe_context_error

        context_error = desktop_safe_context_error(
            _context, capability="desktop_safe.desktop_safe_select_option",
            runtime_session=_session,
        )
        if context_error:
            return ToolResult.fail(context_error)
        if not _desktop_safe_confirmation:
            return ToolResult.fail(
                "desktop_safe_select_option membutuhkan permit konfirmasi registry")
        authority = self._session or desktop_safe_session()
        owner = str(getattr(_session, "id", "") or "desktop-safe-select-option")
        outcome, error = await asyncio.to_thread(
            authority.select_option, str(observation_id), str(element_id), session_id=owner,
        )
        if outcome is None:
            return ToolResult.fail(error)
        if not outcome.ok:
            return ToolResult.fail(
                outcome.reason, executed=outcome.executed, verified=outcome.verified,
                after_observation_id=outcome.after.id if outcome.after else "",
            )
        return ToolResult.success(
            "Option dropdown desktop dipilih dan diverifikasi melalui recapture UIA.",
            display="pilihan dropdown desktop terverifikasi", executed=True, verified=True,
            after_observation_id=outcome.after.id if outcome.after else "",
        )


__all__ = ["DesktopSafeSelectOption"]
