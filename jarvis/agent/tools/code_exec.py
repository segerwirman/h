"""execute_code (§3.1.K) — subprocess terisolasi, cwd terbatas, timeout ketat.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.paths import data_dir
from jarvis.core import quiet

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

#: S-40 — argv sebagai DAFTAR, dan ``shell=False``.
#:
#: Bentuk lama menyusun satu string lalu menyerahkannya ke shell:
#: ``f'{cmd_prefix} "{script}"'``. Script-nya dikutip, interpreternya tidak —
#: sehingga di setiap instalasi yang path-nya memuat spasi (mesin Takeda:
#: ``E:\jarvis agent\h``) perintahnya terpotong dan tool ini GAGAL SETIAP
#: KALI: ``'E:\jarvis' is not recognized as an internal or external command``.
#:
#: Daftar argv menghapus persoalan kutip seluruhnya, dan sekalian membuang
#: shell dari jalurnya — satu lapisan interpretasi yang tidak pernah
#: dibutuhkan, karena kodenya ditulis ke berkas, bukan disisipkan ke perintah.
_RUNNERS: dict[str, tuple[list[str], str]] = {
    "python": ([sys.executable], ".py"),
    "node": (["node"], ".js"),
    "javascript": (["node"], ".js"),
    "bash": (["bash"], ".sh"),
    "powershell": (["powershell", "-NoProfile", "-File"], ".ps1"),
}


class _ExecParams(BaseModel):
    code: str = Field(description="Kode sumber yang dieksekusi")
    language: str = Field("python",
                          description="python | node | bash | powershell")
    timeout: int = Field(30, description="Timeout detik (maks 300)")


class ExecuteCode(Tool):
    name = "execute_code"
    description = ("Eksekusi potongan kode di sandbox subprocess "
                   "(python/node/bash/powershell). Tangkap stdout, stderr, "
                   "exit code. Gunakan print() untuk hasil.")
    params_schema = _ExecParams
    timeout_s = 320

    async def run(self, code: str, language: str = "python",
                  timeout: int = 30, **_) -> ToolResult:
        language = (language or "python").lower()
        runner = _RUNNERS.get(language)
        if runner is None:
            return ToolResult.fail(f"bahasa tidak didukung: {language}")
        cmd_prefix, suffix = runner
        timeout = min(int(timeout or 30), 300)

        sandbox = data_dir() / "sandbox"
        sandbox.mkdir(parents=True, exist_ok=True)

        def _exec():
            with tempfile.NamedTemporaryFile(
                    "w", suffix=suffix, dir=sandbox, delete=False,
                    encoding="utf-8") as f:
                f.write(code)
                script = Path(f.name)
            try:
                return subprocess.run(
                    [*cmd_prefix, str(script)], shell=False,
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", cwd=str(sandbox), timeout=timeout,
                    creationflags=_CREATE_NO_WINDOW)
            finally:
                try:
                    script.unlink()
                except OSError as exc:
                    quiet.swallowed("agent.tools.code_exec.cleanup_failed", exc)

        try:
            r = await asyncio.to_thread(_exec)
        except subprocess.TimeoutExpired:
            return ToolResult.fail(f"timeout {timeout}s")
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        body = out or "(tanpa stdout)"
        if err:
            body += "\n[stderr]\n" + err
        return ToolResult(ok=r.returncode == 0,
                          content=f"exit={r.returncode}\n{body[-20_000:]}",
                          display=f"exit {r.returncode}",
                          error=None if r.returncode == 0
                          else f"exit code {r.returncode}")
