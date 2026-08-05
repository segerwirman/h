"""Tool untuk Chrome milik user — TERPISAH dari browser agent (Fase 21).

Dua browser, dua nama tool. `browser_*` menggerakkan browser agent yang
terisolasi; `user_browser_*` menyentuh Chrome yang benar-benar dipakai Takeda.
Menyatukannya akan membuat target ambigu, dan target yang ambigu adalah cara
paling cepat kembali ke "pause youtube" yang memeriksa browser yang salah.
"""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult


class _NoParams(BaseModel):
    pass


class _MediaParams(BaseModel):
    action: str = Field(
        "pause",
        description="status | play | pause | toggle | mute | unmute")
    index: int | None = Field(
        None, description="Index tab dari user_browser_tabs; kosongkan agar "
                          "Jarvis mencari tab yang sedang memutar")


class _OpenParams(BaseModel):
    url: str = Field(description="URL lengkap (http:// atau https://)")


def _fail(result: dict) -> ToolResult:
    return ToolResult.fail(str(result.get("reason") or "gagal"))


class UserBrowserStatus(Tool):
    name = "user_browser_status"
    description = (
        "Periksa apakah Jarvis bisa melihat Chrome milik user (browser yang "
        "dipakai sehari-hari), berikut sebabnya bila tidak. Read-only.")
    params_schema = _NoParams
    read_only = True
    timeout_s = 20

    async def run(self, **_) -> ToolResult:
        from jarvis.integrations import user_browser

        state = await asyncio.to_thread(user_browser.status)
        if not state.get("attached"):
            return _fail(state)
        return ToolResult.success(
            state, display=f"Chrome user terhubung — {state['tabs']} tab.")


class UserBrowserTabs(Tool):
    name = "user_browser_tabs"
    description = (
        "Daftar tab yang sedang terbuka di Chrome milik user, berikut judul "
        "dan URL-nya. Read-only. Pakai ini untuk tahu apa yang sedang dibuka "
        "user — BUKAN browser_tabs, yang hanya melihat browser agent.")
    params_schema = _NoParams
    read_only = True
    timeout_s = 25

    async def run(self, **_) -> ToolResult:
        from jarvis.integrations import user_browser

        result = await asyncio.to_thread(user_browser.list_tabs)
        if not result.get("ok"):
            return _fail(result)
        tabs = result["tabs"]
        lines = [f"[{t['index']}] {t['title']} — {t['url']}" for t in tabs]
        return ToolResult.success(
            {"tabs": tabs},
            display=f"{len(tabs)} tab di Chrome user\n" + "\n".join(lines[:12]))


class UserBrowserMedia(Tool):
    name = "user_browser_media"
    description = (
        "Kendalikan video/audio yang sedang diputar di Chrome milik user "
        "(pause, play, mute). Inilah yang dipakai untuk 'pause youtube' saat "
        "user memutar video di browsernya sendiri. Jarvis mencari sendiri tab "
        "yang memutar; tidak perlu index.")
    params_schema = _MediaParams
    timeout_s = 30

    async def run(self, action: str = "pause", index: int | None = None,
                  **_) -> ToolResult:
        from jarvis.integrations import user_browser

        result = await asyncio.to_thread(user_browser.media, action, index)
        if not result.get("ok"):
            return _fail(result)
        tab = result.get("tab") or {}
        state = result.get("state") or {}
        verb = {"pause": "dijeda", "play": "diputar", "toggle": "dialihkan",
                "mute": "dibisukan", "unmute": "dibunyikan"}.get(
                    result.get("action", ""), "dibaca")
        return ToolResult.success(
            result,
            display=f"{tab.get('title', 'Media')} {verb}"
                    + (" (masih jeda)" if state.get("paused") else ""))


class UserBrowserOpen(Tool):
    name = "user_browser_open"
    description = (
        "Buka satu URL di Chrome milik user sebagai tab baru, sehingga user "
        "benar-benar melihatnya di browser yang ia pakai.")
    params_schema = _OpenParams
    timeout_s = 45

    async def run(self, url: str, **_) -> ToolResult:
        from jarvis.integrations import user_browser

        result = await asyncio.to_thread(user_browser.open_url, url)
        if not result.get("ok"):
            return _fail(result)
        return ToolResult.success(result,
                                  display=f"Dibuka di Chrome Anda: {url}")
