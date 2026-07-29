"""Tool agent untuk membuka/menutup aplikasi bernama (DIAGNOSIS_2 MASALAH 3).

``close_app`` sengaja dideklarasikan ``requires_confirmation = False`` namun
**tidak pernah** memaksa: penutupan default-nya anggun (WM_CLOSE/SIGTERM) dan
aplikasi tetap boleh menampilkan dialog "simpan perubahan". Yang berbahaya —
``force`` — dijaga ``needs_confirmation`` per panggilan.

Guard proses-sendiri ada di ``actions/close_app.py``; tool ini tidak boleh
menambah jalur yang melewatinya.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult


class _OpenParams(BaseModel):
    name: str = Field(description="Nama aplikasi yang dibuka, mis. 'WhatsApp'")


class OpenApp(Tool):
    name = "open_app"
    description = (
        "Buka aplikasi desktop berdasarkan nama melalui launcher native OS. "
        "Untuk WhatsApp yang tidak terpasang, buka WhatsApp Web. Gunakan ini "
        "untuk membuka aplikasi; jangan menebak command terminal."
    )
    params_schema = _OpenParams
    timeout_s = 20

    async def run(self, name: str = "", **_) -> ToolResult:
        import asyncio

        from actions.open_app import launch_application

        outcome = await asyncio.to_thread(launch_application, name)
        if outcome.ok:
            return ToolResult.success(
                outcome.message,
                display=outcome.message[:80],
                source=outcome.source,
            )
        return ToolResult.fail(outcome.message)


class _CloseParams(BaseModel):
    name: str = Field(description="Nama aplikasi yang ditutup, mis. 'Instagram'")
    force: bool = Field(
        False, description="Paksa tutup bila cara sopan gagal (buang data)")
    all_windows: bool = Field(
        False, description="Tutup SEMUA jendela aplikasi itu, bukan bertanya")


class CloseApp(Tool):
    name = "close_app"
    description = (
        "Tutup aplikasi lain yang sedang berjalan, berdasarkan NAMANYA. "
        "Selalu menutup dengan anggun lebih dulu. JANGAN pakai ini untuk "
        "mematikan Jarvis — permintaan itu akan ditolak."
    )
    params_schema = _CloseParams
    timeout_s = 30

    def needs_confirmation(self, **kwargs) -> bool:
        # Menutup dengan anggun boleh langsung; MEMAKSA tidak.
        return bool(kwargs.get("force"))

    def confirmation_text(self, **kwargs) -> str:
        return (f"Paksa tutup {kwargs.get('name', '?')}? Data yang belum "
                f"tersimpan akan hilang.")

    async def run(self, name: str = "", force: bool = False,
                  all_windows: bool = False, **_) -> ToolResult:
        import asyncio

        from actions.close_app import STATUS_CLOSED, close_app

        outcome = await asyncio.to_thread(close_app, name, force, all_windows)
        if outcome.status == STATUS_CLOSED:
            return ToolResult.success(outcome.message,
                                      display=outcome.message[:80],
                                      closed=outcome.closed)
        # Bukan sukses, tapi juga bukan error teknis — model perlu tahu
        # bedanya "tidak berjalan" dari "ditolak" agar responsnya tepat.
        return ToolResult.fail(outcome.message, status=outcome.status,
                               candidates=outcome.candidates)


class _RunningParams(BaseModel):
    filter: str = Field("", description="Saring berdasarkan nama (opsional)")


class ListRunningApps(Tool):
    name = "list_running_apps"
    description = ("Daftar aplikasi yang sedang berjalan beserta judul "
                   "jendelanya. Pakai sebelum menutup sesuatu yang ambigu.")
    params_schema = _RunningParams
    read_only = True
    timeout_s = 20

    async def run(self, filter: str = "", **_) -> ToolResult:  # noqa: A002
        import asyncio

        from jarvis.core import app_registry

        apps = await asyncio.to_thread(app_registry.list_running)
        needle = app_registry.normalize(filter)
        if needle:
            apps = [a for a in apps
                    if needle in app_registry.normalize(a.name)
                    or needle in app_registry.normalize(a.window_title)]
        if not apps:
            return ToolResult.success("Tidak ada aplikasi berjendela yang "
                                      "cocok.", display="0 aplikasi")
        lines = sorted({f"{a.name} — {a.window_title}".rstrip(" —")
                        for a in apps})[:40]
        return ToolResult.success("\n".join(lines),
                                  display=f"{len(lines)} aplikasi")
