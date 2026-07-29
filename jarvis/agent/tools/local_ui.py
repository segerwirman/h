"""Native agent tools for Jarvis-owned local UI surfaces."""
from __future__ import annotations

from pydantic import BaseModel

from jarvis.agent.base import Tool, ToolResult


class _NoParams(BaseModel):
    pass


class CameraOpen(Tool):
    name = "camera_open"
    description = (
        "Buka panel kamera live milik Jarvis. Setelah terbuka, gunakan "
        "vision_analyze tanpa image_path untuk menganalisis frame terbaru."
    )
    params_schema = _NoParams
    wants_context = True
    timeout_s = 10

    async def run(self, _adapter=None, **_) -> ToolResult:
        if _adapter is None:
            return ToolResult.fail("UI Jarvis tidak tersedia pada sesi ini")
        queued = await _adapter.native_action("camera_open")
        if not queued:
            return ToolResult.fail("adapter sesi tidak memiliki panel kamera")
        return ToolResult.success(
            "Panel kamera Jarvis dibuka.",
            display="kamera dibuka",
        )


class CameraClose(Tool):
    name = "camera_close"
    description = "Tutup panel kamera live milik Jarvis."
    params_schema = _NoParams
    wants_context = True
    timeout_s = 10

    async def run(self, _adapter=None, **_) -> ToolResult:
        if _adapter is None:
            return ToolResult.fail("UI Jarvis tidak tersedia pada sesi ini")
        queued = await _adapter.native_action("camera_close")
        if not queued:
            return ToolResult.fail("adapter sesi tidak memiliki panel kamera")
        return ToolResult.success(
            "Panel kamera Jarvis ditutup.",
            display="kamera ditutup",
        )
