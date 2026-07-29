"""Tool cron (§3.1.L) — antarmuka agent ke scheduler."""
from __future__ import annotations

import asyncio
import datetime

from pydantic import BaseModel, Field

from jarvis.agent import cron
from jarvis.agent.base import Tool, ToolResult


def _fmt(ts) -> str:
    if not ts:
        return "-"
    return datetime.datetime.fromtimestamp(float(ts)).strftime(
        "%Y-%m-%d %H:%M")


class _CreateParams(BaseModel):
    name: str = Field(description="Nama unik job")
    schedule: str = Field(description="Cron expression 5-field, "
                                      "mis. '0 7 * * *' (tiap 07:00)")
    task: str = Field(description="Tugas yang dijalankan agent")
    skills: list[str] = Field(default_factory=list,
                              description="Skill yang di-attach ke job")
    enabled: bool = Field(True)


class CronCreateTool(Tool):
    name = "cron_create"
    description = ("Buat job terjadwal (cron). Job berjalan sebagai sesi "
                   "agent otonom; hasil dikirim ke Telegram bila aktif.")
    params_schema = _CreateParams
    timeout_s = 15

    async def run(self, name: str, schedule: str, task: str,
                  skills: list[str] | None = None, enabled: bool = True,
                  **_) -> ToolResult:
        ok, msg = await asyncio.to_thread(
            cron.create, name, schedule, task, skills or [], enabled)
        return (ToolResult.success(f"job dibuat, id={msg}") if ok
                else ToolResult.fail(msg))


class CronListTool(Tool):
    name = "cron_list"
    description = "Daftar semua cron job + jadwal berikutnya."
    read_only = True
    timeout_s = 15

    async def run(self, **_) -> ToolResult:
        jobs = await asyncio.to_thread(cron.list_jobs)
        if not jobs:
            return ToolResult.success("belum ada job", display="0 job")
        lines = [f"[{j['id']}] {j['name']}  '{j['schedule']}'  "
                 f"{'ON' if j['enabled'] else 'OFF'}  "
                 f"next={_fmt(j.get('next_run'))}  "
                 f"runs={j.get('run_count', 0)}\n    task: {j['task'][:100]}"
                 for j in jobs]
        return ToolResult.success("\n".join(lines),
                                  display=f"{len(jobs)} job")


class _IdParams(BaseModel):
    id: str = Field(description="ID atau nama job")


class _UpdateParams(BaseModel):
    id: str = Field(description="ID atau nama job")
    name: str = Field("", description="Nama baru (opsional)")
    schedule: str = Field("", description="Jadwal baru (opsional)")
    task: str = Field("", description="Tugas baru (opsional)")


class CronUpdateTool(Tool):
    name = "cron_update"
    description = "Perbarui job (nama/jadwal/tugas)."
    params_schema = _UpdateParams
    timeout_s = 15

    async def run(self, id: str, name: str = "", schedule: str = "",
                  task: str = "", **_) -> ToolResult:
        ok = await asyncio.to_thread(
            cron.update, id, name=name or None, schedule=schedule or None,
            task=task or None)
        return (ToolResult.success("job diperbarui") if ok
                else ToolResult.fail("job tidak ditemukan / input tidak valid"))


class CronPauseTool(Tool):
    name = "cron_pause"
    description = "Pause sebuah job."
    params_schema = _IdParams
    timeout_s = 15

    async def run(self, id: str, **_) -> ToolResult:
        ok = await asyncio.to_thread(cron.set_enabled, id, False)
        return (ToolResult.success("job dipause") if ok
                else ToolResult.fail("job tidak ditemukan"))


class CronResumeTool(Tool):
    name = "cron_resume"
    description = "Aktifkan kembali job yang dipause."
    params_schema = _IdParams
    timeout_s = 15

    async def run(self, id: str, **_) -> ToolResult:
        ok = await asyncio.to_thread(cron.set_enabled, id, True)
        return (ToolResult.success("job aktif kembali") if ok
                else ToolResult.fail("job tidak ditemukan"))


class CronRunTool(Tool):
    name = "cron_run"
    description = "Jalankan job SEKARANG (abaikan jadwal)."
    params_schema = _IdParams
    timeout_s = 15

    async def run(self, id: str, **_) -> ToolResult:
        ok, msg = await asyncio.to_thread(cron.run_job_now, id)
        return ToolResult.success(msg) if ok else ToolResult.fail(msg)


class CronDeleteTool(Tool):
    name = "cron_delete"
    description = "Hapus job terjadwal."
    params_schema = _IdParams
    requires_confirmation = True
    timeout_s = 15

    async def run(self, id: str, **_) -> ToolResult:
        ok = await asyncio.to_thread(cron.delete, id)
        return (ToolResult.success("job dihapus") if ok
                else ToolResult.fail("job tidak ditemukan"))
