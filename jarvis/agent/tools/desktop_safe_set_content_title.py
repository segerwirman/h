"""Phase 19 — Intent-specific bounded setter for Content Studio Judul Project only."""
from __future__ import annotations
import asyncio
from pydantic import BaseModel, Field
from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession, desktop_safe_session
from jarvis.core.content_title_policy import admit_title

class _Params(BaseModel):
    observation_id: str = Field(min_length=1, description="ID observasi UIA aktif untuk Judul Project")
    element_id: str = Field(min_length=1, description="ID text field Judul Project semantik")
    project_title: str = Field(min_length=1, max_length=120, description="Judul project baru bounded 1-120 tanpa URL/password/OTP/payment/terminal")

class DesktopSafeSetContentTitle(Tool):
    name = "desktop_safe_set_content_title"
    description = (
        "Ubah tepat satu field Judul Project di Content Studio lokal melalui observasi UIA desktop "
        "yang sudah diobservasi. Hanya menerima observation_id, element_id, dan project_title yang sudah "
        "divalidasi bounded (tanpa URL, password, OTP, payment, terminal, chat/email). Konfirmasi "
        "user desktop-local dan recapture UIA wajib. Tidak ada submit atau navigasi generik."
    )
    params_schema = _Params
    requires_confirmation = True
    wants_context = True
    timeout_s = 30

    def __init__(self, *, session: SafeDesktopSession | None = None):
        self._session = session

    def confirmation_text(self, *, project_title: str, **_) -> str:
        preview = str(project_title or "")[:40]
        return f'Izinkan mengubah Judul Project menjadi "{preview}"?'

    async def run(self, observation_id: str, element_id: str, project_title: str, _session=None, _context=None, _desktop_safe_confirmation: bool = False, **_,) -> ToolResult:
        from jarvis.agent.policy import desktop_safe_context_error
        context_error = desktop_safe_context_error(_context, capability="desktop_safe.desktop_safe_set_content_title", runtime_session=_session,)
        if context_error:
            return ToolResult.fail(context_error)
        if not _desktop_safe_confirmation:
            return ToolResult.fail("desktop_safe_set_content_title membutuhkan permit konfirmasi registry")
        policy_res = admit_title(project_title)
        if not policy_res.get("ok"):
            return ToolResult.fail(f"judul ditolak kebijakan: {policy_res.get('reason')}")
        requested = str(policy_res["title"])
        authority = self._session or desktop_safe_session()
        owner = str(getattr(_session, "id", "") or "desktop-safe-set-content-title")
        outcome, error = await asyncio.to_thread(authority.set_content_title, str(observation_id), str(element_id), title=requested, session_id=owner,)
        if outcome is None:
            return ToolResult.fail(error or "set_content_title gagal")
        if not outcome.ok:
            return ToolResult.fail(outcome.reason, executed=outcome.executed, verified=outcome.verified, after_observation_id=outcome.after.id if outcome.after else "",)
        return ToolResult.success("Judul Project diubah dan diverifikasi melalui recapture UIA.", display="judul project terverifikasi", executed=True, verified=True, intent="content_studio_title", title=requested, after_observation_id=outcome.after.id if outcome.after else "",)

__all__ = ["DesktopSafeSetContentTitle"]
