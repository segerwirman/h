"""analyze_food_calories — tool agent untuk analisis kalori makanan.

Sumber gambar: path/b64 eksplisit, atau frame kamera live (bila vision
worker Jarvis sedang berjalan — kamera tunggal, tidak buka handle kedua).
"""
from __future__ import annotations

import asyncio
import base64
from pathlib import Path

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.core import quiet


class _Params(BaseModel):
    image_path: str = Field("", description="Path foto makanan (opsional)")
    image_b64: str = Field("", description="Alternatif: base64 JPEG")
    question: str = Field("", description="Fokus analisis, mis. 'berapa "
                                          "proteinnya?'")


class AnalyzeFoodCalories(Tool):
    name = "analyze_food_calories"
    description = ("Analisis kalori + makro makanan dari foto. Tanpa "
                   "image_path/b64, otomatis memakai frame kamera live "
                   "Jarvis (bila kamera aktif).")
    params_schema = _Params
    read_only = True
    timeout_s = 120

    async def run(self, image_path: str = "", image_b64: str = "",
                  question: str = "", **_) -> ToolResult:
        data: bytes | None = None
        if image_path:
            p = Path(image_path).expanduser()
            if not p.is_file():
                return ToolResult.fail(f"foto tidak ditemukan: {p}")
            data = await asyncio.to_thread(p.read_bytes)
        elif image_b64:
            try:
                data = base64.b64decode(image_b64)
            except Exception:                                # noqa: BLE001
                return ToolResult.fail("image_b64 tidak valid")
        else:
            data = await asyncio.to_thread(_live_camera_jpeg)
            if not data:
                return ToolResult.fail(
                    "kamera tidak aktif dan tidak ada foto — buka panel "
                    "kamera dulu atau beri image_path")

        from jarvis.vision import food_calories
        analysis = await asyncio.to_thread(
            food_calories.analyze_jpeg, data, question)
        if analysis.error:
            return ToolResult.fail(analysis.error)
        return ToolResult.success(analysis.detail_text(),
                                  display=analysis.summary_line())


def _live_camera_jpeg() -> bytes | None:
    """Frame terbaru dari vision worker (pemilik kamera tunggal)."""
    try:
        from jarvis.agent.adapters import ui as ui_adapter
        vision = ui_adapter.current_vision_system()
        if vision is not None and vision.alive:
            return vision.latest_frame_jpeg(timeout=2.5)
    except Exception as exc:                                 # noqa: BLE001
        quiet.swallowed("agent.tools.food.live_frame_failed", exc)
    return None
