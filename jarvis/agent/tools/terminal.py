"""Terminal & process (§3.1.B) — blacklist perintah destruktif; yang cocok
meminta konfirmasi user. Tidak pernah memunculkan jendela terminal (Windows).
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import sys

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.paths import workspace_root

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# pola destruktif → requires_confirmation (spec §3.1.B)
_DANGEROUS = re.compile(
    r"(?:\brm\s+(-\w*\s+)*-\w*r\w*f|\brm\s+-rf\b|\bmkfs\b|\bdd\s+if=|"
    r"\bdd\s+of=/dev/|:\(\)\s*{\s*:\|:&\s*};|"
    r"\bformat\s+[a-z]:|\bdel\s+/s\b|\brd\s+/s\b|remove-item\s+.*-recurse|"
    r"\bshutdown\b|\breboot\b|\brmdir\s+/s\b|"
    r"\bgit\s+push\s+.*--force\b|\bgit\s+reset\s+--hard\b|"
    r"\breg\s+delete\b|\bdiskpart\b|\bcipher\s+/w\b)",
    re.IGNORECASE)


class _TermParams(BaseModel):
    command: str = Field(description="Perintah shell")
    cwd: str = Field("", description="Working directory (default workspace)")
    timeout: int = Field(60, description="Timeout detik (maks 600)")


class Terminal(Tool):
    name = "terminal"
    description = ("Jalankan perintah shell dan kembalikan stdout+stderr+exit "
                   "code. Perintah destruktif meminta konfirmasi user dulu.")
    params_schema = _TermParams
    timeout_s = 620

    def needs_confirmation(self, **kw) -> bool:
        return bool(_DANGEROUS.search(kw.get("command", "")))

    def confirmation_text(self, **kw) -> str:
        return ("Perintah shell ini terdeteksi berbahaya:\n"
                f"`{kw.get('command', '')[:200]}`\nJalankan?")

    async def run(self, command: str, cwd: str = "", timeout: int = 60,
                  **_) -> ToolResult:
        timeout = min(int(timeout or 60), 600)

        def _exec():
            return subprocess.run(
                command, shell=True, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                cwd=cwd or str(workspace_root()), timeout=timeout,
                creationflags=_CREATE_NO_WINDOW)

        try:
            r = await asyncio.to_thread(_exec)
        except subprocess.TimeoutExpired:
            return ToolResult.fail(f"timeout {timeout}s: {command[:120]}")
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        body = out
        if err:
            body += ("\n[stderr]\n" + err) if body else "[stderr]\n" + err
        body = body[-20_000:] if body else "(tanpa output)"
        result = ToolResult(ok=r.returncode == 0,
                            content=f"exit={r.returncode}\n{body}",
                            display=f"exit {r.returncode}",
                            error=None if r.returncode == 0
                            else f"exit code {r.returncode}",
                            meta={"exit": r.returncode})
        return result


class _ProcListParams(BaseModel):
    filter: str = Field("", description="Substring nama proses")


class ProcessList(Tool):
    name = "process_list"
    description = "Daftar proses berjalan (pid, nama, cpu%, mem MB)."
    params_schema = _ProcListParams
    read_only = True
    timeout_s = 30

    async def run(self, filter: str = "", **_) -> ToolResult:
        def _list():
            import psutil
            rows = []
            for p in psutil.process_iter(["pid", "name", "cpu_percent",
                                          "memory_info"]):
                try:
                    name = p.info["name"] or ""
                    if filter and filter.lower() not in name.lower():
                        continue
                    mem = (p.info["memory_info"].rss // (1024 * 1024)
                           if p.info["memory_info"] else 0)
                    rows.append((p.info["pid"], name,
                                 p.info["cpu_percent"] or 0.0, mem))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            rows.sort(key=lambda r: r[3], reverse=True)
            return rows[:60]

        rows = await asyncio.to_thread(_list)
        text = "\n".join(f"{pid:>7}  {name[:40]:<40} cpu={cpu:4.1f}% "
                         f"mem={mem}MB" for pid, name, cpu, mem in rows)
        return ToolResult.success(text or "(kosong)",
                                  display=f"{len(rows)} proses")


class _KillParams(BaseModel):
    pid: int = Field(description="PID proses yang dihentikan")


class ProcessKill(Tool):
    name = "process_kill"
    description = "Hentikan proses berdasarkan PID (butuh konfirmasi user)."
    params_schema = _KillParams
    requires_confirmation = True
    timeout_s = 15

    async def run(self, pid: int, **_) -> ToolResult:
        def _kill():
            import psutil
            p = psutil.Process(int(pid))
            name = p.name()
            p.terminate()
            try:
                p.wait(timeout=3)
            except psutil.TimeoutExpired:
                p.kill()
            return name

        try:
            name = await asyncio.to_thread(_kill)
        except Exception as e:                               # noqa: BLE001
            return ToolResult.fail(f"gagal kill {pid}: {str(e)[:120]}")
        return ToolResult.success(f"proses {pid} ({name}) dihentikan")


class _SpawnParams(BaseModel):
    command: str = Field(description="Perintah yang dijalankan di background")
    cwd: str = Field("", description="Working directory")


class ProcessSpawn(Tool):
    name = "process_spawn"
    description = ("Jalankan perintah di background (detached), kembalikan "
                   "PID. Untuk server/aplikasi yang harus tetap hidup.")
    params_schema = _SpawnParams
    timeout_s = 20

    def needs_confirmation(self, **kw) -> bool:
        return bool(_DANGEROUS.search(kw.get("command", "")))

    async def run(self, command: str, cwd: str = "", **_) -> ToolResult:
        def _spawn():
            return subprocess.Popen(
                command, shell=True, cwd=cwd or str(workspace_root()),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_CREATE_NO_WINDOW).pid

        pid = await asyncio.to_thread(_spawn)
        return ToolResult.success(f"berjalan di background, pid={pid}",
                                  pid=pid)
