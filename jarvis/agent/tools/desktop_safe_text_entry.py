"""Bounded Screen Control text entry for one admitted semantic UIA field."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, ConfigDict, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession, desktop_safe_session


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str = Field(min_length=1, description="ID observasi UIA aktif")
    element_id: str = Field(min_length=1, description="ID text field semantik")
    text: str = Field(min_length=1, max_length=500, description="Text bounded 1-500 karakter")


class DesktopSafeTextEntry(Tool):
    name = "desktop_safe_text_entry"
    description = (
        "Isi satu text field UIA non-sensitif dalam Screen Control aktif dengan "
        "text bounded. Password, PIN, OTP, login, payment/card, credential, browser "
        "address, control characters, dan input lebih dari 500 karakter ditolak."
    )
    params_schema = _Params
    requires_confirmation = True
    wants_context = True
    timeout_s = 30

    def __init__(self, *, session: SafeDesktopSession | None = None):
        self._session = session

    def confirmation_text(self, **_) -> str:
        return "Izinkan mengisi satu text field desktop non-sensitif?"

    async def run(self, observation_id: str, element_id: str, text: str,
                  _session=None, _context=None,
                  _desktop_safe_confirmation: bool = False, **_) -> ToolResult:
        from jarvis.agent.policy import screen_control_context_error

        context_error = screen_control_context_error(
            _context,
            capability="desktop_safe.desktop_safe_text_entry",
            runtime_session=_session,
        )
        if context_error:
            return ToolResult.fail(context_error)
        if not _desktop_safe_confirmation:
            return ToolResult.fail(
                "desktop_safe_text_entry membutuhkan permit konfirmasi registry"
            )
        authority = self._session or desktop_safe_session()
        owner = str(getattr(_session, "id", "") or "desktop-safe-text-entry")
        outcome, error = await asyncio.to_thread(
            authority.text_entry,
            str(observation_id),
            str(element_id),
            text=str(text),
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
            "Text field desktop diisi dan diverifikasi melalui recapture UIA.",
            display="text entry desktop terverifikasi",
            executed=True,
            verified=True,
            after_observation_id=outcome.after.id if outcome.after else "",
        )


__all__ = ["DesktopSafeTextEntry"]
