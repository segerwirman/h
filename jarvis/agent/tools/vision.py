"""vision_analyze (§3.1.Q) — kirim gambar ke vision model provider aktif."""
from __future__ import annotations

import asyncio
import base64
import mimetypes
from pathlib import Path

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult


class _Params(BaseModel):
    image_path: str = Field("", description="Path file gambar")
    image_b64: str = Field("", description="Alternatif: base64 gambar")
    question: str = Field("Deskripsikan gambar ini.",
                          description="Pertanyaan tentang gambar")


class VisionAnalyze(Tool):
    name = "vision_analyze"
    description = ("Analisis gambar (screenshot, foto, frame kamera) memakai "
                   "vision model. Beri image_path/image_b64, atau kosongkan "
                   "keduanya untuk memakai frame kamera live terbaru.")
    params_schema = _Params
    read_only = True
    timeout_s = 120

    async def run(self, image_path: str = "", image_b64: str = "",
                  question: str = "Deskripsikan gambar ini.",
                  **_) -> ToolResult:
        if image_path:
            p = Path(image_path).expanduser()
            if not p.is_file():
                return ToolResult.fail(f"gambar tidak ditemukan: {p}")
            data = await asyncio.to_thread(p.read_bytes)
            mime = mimetypes.guess_type(str(p))[0] or "image/png"
        elif image_b64:
            try:
                data = base64.b64decode(image_b64)
            except Exception:                                # noqa: BLE001
                return ToolResult.fail("image_b64 tidak valid")
            mime = "image/jpeg"
        else:
            data = await asyncio.to_thread(_live_camera_jpeg)
            if not data:
                return ToolResult.fail(
                    "frame kamera live belum tersedia; buka kamera lebih dulu")
            mime = "image/jpeg"
        if len(data) > 12_000_000:
            return ToolResult.fail("gambar terlalu besar (>12 MB)")

        # §7.1 — slot auxiliary 'vision'; default (auto) = vision_client lama
        from jarvis.agent import auxiliary
        cl = auxiliary.client_for("vision")
        if not cl.available():
            return ToolResult.fail("vision provider belum dikonfigurasi "
                                   "(Settings → provider)")
        answer = await asyncio.to_thread(cl.vision, data, mime, question)
        if not answer:
            return ToolResult.fail("vision model tidak memberi jawaban")
        return ToolResult.success(answer, display="analisis vision selesai")


def _live_camera_jpeg() -> bytes | None:
    try:
        from jarvis.agent.adapters import ui as ui_adapter

        vision = ui_adapter.current_vision_system()
        if vision is not None and hasattr(vision, "latest_frame_jpeg"):
            return vision.latest_frame_jpeg(timeout=2.5)
    except Exception:                                        # noqa: BLE001
        pass
    return None
