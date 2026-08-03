"""Bounded native weather, reminder, and system-reflex tools for voice.

No legacy ``actions/*`` authority.  Writes require confirmation; read weather
does not.  The reminder implementation is deliberately narrow: one future
local notification through Windows Task Scheduler.
"""
from __future__ import annotations

import asyncio
import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.paths import data_dir


class _WeatherParams(BaseModel):
    city: str = Field(min_length=1, description="Kota untuk cuaca")
    when: str = Field("today", description="today | tomorrow | waktu lain")


class WeatherLookup(Tool):
    name = "weather_lookup"
    description = "Cari cuaca terbaru secara native; read-only."
    params_schema = _WeatherParams
    read_only = True
    timeout_s = 45

    async def run(self, city: str, when: str = "today", **_) -> ToolResult:
        from jarvis.agent.tools.web import WebSearch

        place = " ".join(str(city or "").split())
        moment = " ".join(str(when or "today").split())
        if not place:
            return ToolResult.fail("kota wajib diisi")
        return await WebSearch().run(query=f"cuaca {place} {moment}", mode="news")


class _ReminderParams(BaseModel):
    date: str = Field(description="Tanggal YYYY-MM-DD")
    time: str = Field(description="Waktu HH:MM 24 jam")
    message: str = Field(min_length=1, max_length=200, description="Isi pengingat")


class ReminderCreate(Tool):
    name = "reminder_create"
    description = "Buat satu pengingat lokal pada tanggal dan waktu tertentu."
    params_schema = _ReminderParams
    requires_confirmation = True
    timeout_s = 30

    def confirmation_text(self, **kwargs) -> str:
        return (f"Buat pengingat pada {kwargs.get('date', '?')} "
                f"{kwargs.get('time', '?')}: {kwargs.get('message', '')}?")

    async def run(self, date: str, time: str, message: str, **_) -> ToolResult:
        try:
            target = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        except ValueError:
            return ToolResult.fail("tanggal/waktu harus YYYY-MM-DD dan HH:MM")
        if target <= datetime.now():
            return ToolResult.fail("waktu pengingat sudah lewat")
        if platform.system() != "Windows":
            return ToolResult.fail("reminder native belum didukung pada OS ini")

        safe_message = " ".join(str(message).replace("\x00", "").split())[:200]
        root = data_dir() / "voice_reminders"
        root.mkdir(parents=True, exist_ok=True)
        name = f"JarvisVoiceReminder_{target.strftime('%Y%m%d_%H%M%S')}"
        script = root / f"{name}.py"
        script.write_text(
            "import ctypes\n"
            f"ctypes.windll.user32.MessageBoxW(0, {json.dumps(safe_message)}, "
            '"JARVIS Reminder", 0x40)\n',
            encoding="utf-8",
        )
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        command = str(pythonw if pythonw.is_file() else sys.executable)

        def _schedule():
            return subprocess.run(
                ["schtasks", "/Create", "/TN", name, "/TR",
                 f'"{command}" "{script}"', "/SC", "ONCE", "/SD",
                 target.strftime("%m/%d/%Y"), "/ST", target.strftime("%H:%M"), "/F"],
                capture_output=True, text=True, timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

        try:
            result = await asyncio.to_thread(_schedule)
        except Exception as exc:  # noqa: BLE001
            script.unlink(missing_ok=True)
            return ToolResult.fail(f"scheduler reminder gagal: {type(exc).__name__}")
        if result.returncode != 0:
            script.unlink(missing_ok=True)
            return ToolResult.fail("scheduler Windows menolak reminder")
        return ToolResult.success(
            {"id": name, "at": target.isoformat(timespec="minutes")},
            display=f"pengingat {target.strftime('%d %b %H:%M')}",
        )


class _SystemParams(BaseModel):
    action: str = Field(description="volume_up | volume_down | volume_mute | wifi_on | wifi_off")


class SystemReflex(Tool):
    name = "system_reflex"
    description = "Aksi sistem cepat native: volume atau Wi-Fi."
    params_schema = _SystemParams
    timeout_s = 15
    _WIFI = frozenset({"wifi_on", "wifi_off"})
    _VOLUME = frozenset({"volume_up", "volume_down", "volume_mute"})

    def needs_confirmation(self, **kwargs) -> bool:
        return str(kwargs.get("action", "")).casefold() in self._WIFI

    def confirmation_text(self, **kwargs) -> str:
        action = str(kwargs.get("action", "")).casefold()
        return "Aktifkan Wi-Fi?" if action == "wifi_on" else "Matikan Wi-Fi?"

    async def run(self, action: str, **_) -> ToolResult:
        action = str(action or "").casefold()
        if action not in self._VOLUME | self._WIFI:
            return ToolResult.fail("aksi system_reflex tidak didukung")

        def _run():
            if platform.system() == "Windows":
                if action in self._VOLUME:
                    import pyautogui
                    key = {"volume_up": "volumeup", "volume_down": "volumedown",
                           "volume_mute": "volumemute"}[action]
                    for _ in range(5 if action != "volume_mute" else 1):
                        pyautogui.press(key)
                    return
                state = "Enabled" if action == "wifi_on" else "Disabled"
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"Get-NetAdapter -Name Wi-Fi | Set-NetAdapter -AdminStatus {state} -Confirm:$false"],
                    check=True, capture_output=True, timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return
            raise RuntimeError("system_reflex belum didukung pada OS ini")

        try:
            await asyncio.to_thread(_run)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(f"{action} gagal: {type(exc).__name__}")
        display = {
            "volume_up": "volume dinaikkan", "volume_down": "volume diturunkan",
            "volume_mute": "mute audio diubah", "wifi_on": "Wi-Fi diaktifkan",
            "wifi_off": "Wi-Fi dimatikan",
        }[action]
        return ToolResult.success(display, display=display)


__all__ = ["WeatherLookup", "ReminderCreate", "SystemReflex"]
