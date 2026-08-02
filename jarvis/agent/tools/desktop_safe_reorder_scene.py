"""Phase 20 — Intent-specific bounded semantic reorder for Content Studio scene list only.

Exact trusted surface: Content Studio scene timeline cards.
Action: reorder source -> destination within same observed surface.
Schema: {observation_id, source_element_id, destination_element_id} only.
No filesystem, no upload, no coordinate, no generic drag, no path/secret leak.
Requires registry confirmation, session ownership, RuntimeId proof, same-surface recapture.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession, desktop_safe_session


class _Params(BaseModel):
    observation_id: str = Field(min_length=1, description="ID observasi UIA aktif Content Studio")
    source_element_id: str = Field(min_length=1, description="ID elemen scene source semantik")
    destination_element_id: str = Field(min_length=1, description="ID elemen scene destination semantik")


class DesktopSafeReorderScene(Tool):
    name = "desktop_safe_reorder_scene"
    description = (
        "Reorder tepat satu scene card di Content Studio lokal dengan drag semantik "
        "dari source ke destination dalam observasi UIA yang sama. Hanya menerima "
        "observation_id, source_element_id, destination_element_id. Memerlukan konfirmasi "
        "desktop-local, bukti RuntimeId same-surface, dan recapture UIA. Tidak ada "
        "filesystem, upload, atau koordinat generik."
    )
    params_schema = _Params
    requires_confirmation = True
    wants_context = True
    timeout_s = 30

    def __init__(self, *, session: SafeDesktopSession | None = None):
        self._session = session

    def confirmation_text(self, **_) -> str:
        return "Izinkan reorder scene di Content Studio lokal?"

    async def run(
        self,
        observation_id: str,
        source_element_id: str,
        destination_element_id: str,
        _session=None,
        _context=None,
        _desktop_safe_confirmation: bool = False,
        **_,
    ) -> ToolResult:
        from jarvis.agent.policy import desktop_safe_context_error

        context_error = desktop_safe_context_error(
            _context,
            capability="desktop_safe.desktop_safe_reorder_scene",
            runtime_session=_session,
        )
        if context_error:
            return ToolResult.fail(context_error)

        if not _desktop_safe_confirmation:
            return ToolResult.fail("desktop_safe_reorder_scene membutuhkan permit konfirmasi registry")

        if str(source_element_id) == str(destination_element_id):
            return ToolResult.fail("reorder source==destination ditolak")

        authority = self._session or desktop_safe_session()
        owner = str(getattr(_session, "id", "") or "desktop-safe-reorder-scene")

        outcome, error = await asyncio.to_thread(
            authority.reorder_scene,
            str(observation_id),
            str(source_element_id),
            str(destination_element_id),
            session_id=owner,
        )
        if outcome is None:
            return ToolResult.fail(error or "reorder_scene gagal")

        if not outcome.ok:
            return ToolResult.fail(
                outcome.reason,
                executed=outcome.executed,
                verified=outcome.verified,
                after_observation_id=outcome.after.id if outcome.after else "",
            )

        return ToolResult.success(
            "Urutan scene di Content Studio diubah dan diverifikasi melalui recapture UIA.",
            display="reorder scene terverifikasi",
            executed=True,
            verified=True,
            intent="content_studio_scene_reorder",
            source_element_id=str(source_element_id),
            destination_element_id=str(destination_element_id),
            after_observation_id=outcome.after.id if outcome.after else "",
        )


__all__ = ["DesktopSafeReorderScene"]
