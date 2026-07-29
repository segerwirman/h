"""Computer use (§3.1.C) — kontrol desktop via pyautogui + mss.

FAILSAFE pyautogui aktif (mouse ke pojok layar = berhenti). Aksi klik/ketik
mengubah state → serial, tidak read-only.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.paths import generated_dir
from jarvis.automation.desktop_service import DESKTOP
from jarvis.automation.cua_driver import DRIVER

_DEFAULT_OBSERVE_QUESTION = (
    "Identifikasi kontrol UI yang relevan dan berikan koordinat pixelnya."
)


def _pg():
    """Compatibility seam retained for tests and older callers."""
    return DRIVER._pg()


def _capture(display: int = 1) -> tuple[str, dict[str, int]]:
    path = generated_dir() / f"screen_{int(time.time() * 1000)}.png"
    bounds = DRIVER.screenshot(path, display)
    return str(path), bounds.as_dict()


def _claim_desktop(session) -> str:
    owner = str(getattr(session, "id", "") or "desktop-direct")
    if not DESKTOP.claim(owner):
        raise RuntimeError("desktop sedang dikendalikan sesi lain")
    return owner


def release_computer_session(session_id: str) -> None:
    DESKTOP.release(str(session_id or ""))


class _ShotParams(BaseModel):
    display: int = Field(1, description="Nomor monitor (1 = utama)")


class ComputerScreenshot(Tool):
    name = "computer_screenshot"
    description = ("Screenshot layar → simpan PNG, kembalikan path. "
                   "Lanjutkan dengan vision_analyze untuk 'melihat' isinya.")
    params_schema = _ShotParams
    read_only = True
    timeout_s = 30

    async def run(self, display: int = 1, **_) -> ToolResult:
        def _shot() -> str:
            return _capture(display)

        path, bounds = await asyncio.to_thread(_shot)
        return ToolResult.success(
            f"screenshot tersimpan: {path}", display="screenshot diambil",
            path=path, bounds=bounds)


class _ObserveParams(BaseModel):
    display: int = Field(1, description="Nomor monitor (1 = utama)")
    question: str = Field(
        _DEFAULT_OBSERVE_QUESTION,
        description="Tujuan pengamatan sebelum click/type",
    )


class ComputerObserve(Tool):
    name = "computer_observe"
    description = (
        "Satu langkah observasi CUA native: screenshot desktop lalu analisis "
        "vision dengan koordinat pixel. Gunakan sebelum computer_click untuk "
        "UI desktop yang tidak punya driver semantik."
    )
    params_schema = _ObserveParams
    read_only = True
    timeout_s = 120

    async def run(self, display: int = 1, question: str = "", **_) -> ToolResult:
        path, bounds = await asyncio.to_thread(_capture, display)
        data = await asyncio.to_thread(Path(path).read_bytes)
        from jarvis.agent import auxiliary

        client = auxiliary.client_for("vision")
        if not client.available():
            return ToolResult.fail(
                "vision provider belum siap untuk observasi CUA",
                path=path,
                bounds=bounds,
            )
        prompt = (
            f"Desktop bounds: {bounds}. "
            f"{question or _DEFAULT_OBSERVE_QUESTION} "
            "Jawab dengan nama elemen, keadaan saat ini, dan koordinat pusat "
            "(x,y) absolut. Jangan menebak elemen yang tidak terlihat."
        )
        answer = await asyncio.to_thread(
            client.vision, data, "image/png", prompt
        )
        if not answer:
            return ToolResult.fail(
                "vision tidak memberi hasil observasi CUA",
                path=path,
                bounds=bounds,
            )
        return ToolResult.success(
            {"analysis": answer, "path": path, "bounds": bounds},
            display="observasi CUA selesai",
            path=path,
            bounds=bounds,
        )


class _ClickParams(BaseModel):
    x: int = Field(description="Koordinat layar X")
    y: int = Field(description="Koordinat layar Y")
    button: str = Field("left", description="left|right|middle")
    double: bool = Field(False)


class ComputerClick(Tool):
    name = "computer_click"
    description = "Klik mouse di koordinat layar."
    params_schema = _ClickParams
    wants_context = True
    timeout_s = 15

    async def run(self, x: int, y: int, button: str = "left",
                  double: bool = False, _session=None, **_) -> ToolResult:
        def _click():
            DRIVER.click(
                int(x), int(y), button=str(button).casefold(), double=double,
                backend=_pg(),
            )

        try:
            owner = _claim_desktop(_session)
        except RuntimeError as exc:
            return ToolResult.fail(str(exc))
        try:
            await asyncio.to_thread(_click)
        finally:
            if _session is None:
                DESKTOP.release(owner)
        return ToolResult.success(f"klik {button} di ({x},{y})"
                                  + (" 2x" if double else ""))


class _TypeParams(BaseModel):
    text: str = Field(description="Teks yang diketik")


class ComputerType(Tool):
    name = "computer_type"
    description = "Ketik teks pada fokus aktif."
    params_schema = _TypeParams
    wants_context = True
    timeout_s = 60

    async def run(self, text: str, _session=None, **_) -> ToolResult:
        try:
            owner = _claim_desktop(_session)
        except RuntimeError as exc:
            return ToolResult.fail(str(exc))
        def _type():
            DRIVER.type_text(text, backend=_pg())
        try:
            await asyncio.to_thread(_type)
        finally:
            if _session is None:
                DESKTOP.release(owner)
        return ToolResult.success(f"mengetik {len(text)} karakter")


class _KeyParams(BaseModel):
    keys: str = Field(description="Tombol/kombinasi, mis. 'enter', "
                                  "'ctrl+shift+t', 'alt+tab'")


class ComputerKey(Tool):
    name = "computer_key"
    description = "Tekan tombol / kombinasi keyboard."
    params_schema = _KeyParams
    wants_context = True
    timeout_s = 15

    async def run(self, keys: str, _session=None, **_) -> ToolResult:
        parts = [k.strip().lower() for k in keys.split("+") if k.strip()]
        if not parts:
            return ToolResult.fail("keys kosong")
        try:
            owner = _claim_desktop(_session)
        except RuntimeError as exc:
            return ToolResult.fail(str(exc))

        def _press():
            DRIVER.key(parts, backend=_pg())
        try:
            await asyncio.to_thread(_press)
        finally:
            if _session is None:
                DESKTOP.release(owner)
        return ToolResult.success(f"tekan {'+'.join(parts)}")


class _ScrollParams(BaseModel):
    x: int = Field(0, description="Posisi X (0 = posisi kursor)")
    y: int = Field(0, description="Posisi Y")
    dy: int = Field(-500, description="Jarak scroll (negatif = ke bawah)")


class ComputerScroll(Tool):
    name = "computer_scroll"
    description = "Scroll di posisi tertentu (dy negatif = ke bawah)."
    params_schema = _ScrollParams
    wants_context = True
    timeout_s = 15

    async def run(self, x: int = 0, y: int = 0, dy: int = -500,
                  _session=None, **_) -> ToolResult:
        try:
            owner = _claim_desktop(_session)
        except RuntimeError as exc:
            return ToolResult.fail(str(exc))
        def _scroll():
            DRIVER.scroll(int(x), int(y), int(dy), backend=_pg())
        try:
            await asyncio.to_thread(_scroll)
        finally:
            if _session is None:
                DESKTOP.release(owner)
        return ToolResult.success(f"scroll {dy}")


class _DragParams(BaseModel):
    from_x: int
    from_y: int
    to_x: int
    to_y: int
    duration: float = Field(0.5, description="Durasi drag (detik)")


class ComputerDrag(Tool):
    name = "computer_drag"
    description = "Drag & drop dari satu titik ke titik lain."
    params_schema = _DragParams
    wants_context = True
    timeout_s = 30

    async def run(self, from_x: int, from_y: int, to_x: int, to_y: int,
                  duration: float = 0.5, _session=None, **_) -> ToolResult:
        try:
            owner = _claim_desktop(_session)
        except RuntimeError as exc:
            return ToolResult.fail(str(exc))
        def _drag():
            DRIVER.drag(
                int(from_x), int(from_y), int(to_x), int(to_y),
                float(duration), backend=_pg(),
            )
        try:
            await asyncio.to_thread(_drag)
        finally:
            if _session is None:
                DESKTOP.release(owner)
        return ToolResult.success(
            f"drag ({from_x},{from_y}) → ({to_x},{to_y})")
