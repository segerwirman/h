"""HermesBridge — deprecated process-level bridge ke Hermes Agent CLI.

Dua jalur dengan kontrak latency berbeda:

  send_direct(target, text)   Tier 2 — ``hermes send``: TANPA LLM, tanpa agent
                              loop; reuse kredensial gateway. ~0.8-1.5 s.
  run_task(task)              Tier 3 — ``hermes -z`` (one-shot agent penuh,
                              semua tool). 10 s – beberapa menit; HANYA boleh
                              dipanggil dari worker thread (lihat
                              async_dispatch).

Bridge hanya dapat dipakai bila feature flag ``hermes.enabled`` dinyalakan
secara eksplisit. Default MK50 adalah ``false``. Guard dilakukan kembali di
setiap boundary yang bisa menyentuh executable supaya instance lama atau
caller legacy tidak dapat menjalankan CLI setelah flag dimatikan.
"""
from __future__ import annotations

import json
import shutil as shutil  # compatibility seam for tests proving CLI stays untouched
import subprocess as subprocess  # compatibility seam; retired runtime never calls it
import threading

_DISABLED_ERROR = (
    "Integrasi Hermes dinonaktifkan; gunakan agent native Jarvis."
)


def is_enabled() -> bool:
    """Hermes is permanently retired from the Jarvis runtime.

    The function remains only as an import-compatible tombstone while old
    installs migrate.  Configuration can no longer reactivate a process-level
    Hermes dependency.
    """
    return False


def _disabled_result() -> dict:
    return {
        "ok": False,
        "error": _DISABLED_ERROR,
        "stdout": "",
        "stderr": "",
        "exit": -1,
        "elapsed_ms": 0.0,
    }


class HermesBridge:
    """Import-compatible tombstone for retired Hermes integrations."""

    _instance: "HermesBridge | None" = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "HermesBridge":
        with cls._lock:
            if cls._instance is None:
                cls._instance = HermesBridge()
            return cls._instance

    @classmethod
    def _reset_for_tests(cls) -> None:
        with cls._lock:
            cls._instance = None

    def __init__(self):
        self.executable = "hermes"
        self._resolved: str | None = None
        self.profile = ""
        self.send_timeout_s = 20.0
        self.task_timeout_s = 600.0
        self.model = ""
        self.toolsets = ""

    # ── plumbing ──────────────────────────────────────────────────────────

    def _exe(self) -> str | None:
        """Retired runtime never resolves an executable."""
        return None

    def available(self) -> bool:
        """Hermes runtime is retired and never available."""
        return False

    def _run(self, args: list[str], timeout: float) -> dict:
        """Return retired-runtime result without touching executable or process."""
        return _disabled_result()

    # ── Tier 2: no-LLM direct send ────────────────────────────────────────

    def send_direct(self, target: str, text: str) -> dict:
        """``hermes send --to <target> <text>`` — tanpa LLM/agent loop.
        target: 'telegram' | 'telegram:chat_id' | 'discord:#ops' | dst."""
        r = self._run(["send", "--to", target, "--json", text],
                      timeout=self.send_timeout_s)
        if r["ok"]:
            try:
                r["result"] = json.loads(r["stdout"])
            except (json.JSONDecodeError, ValueError):
                r["result"] = {"raw": r["stdout"].strip()}
        return r

    def list_targets(self) -> list[str]:
        r = self._run(["send", "--list"], timeout=self.send_timeout_s)
        return [ln.strip() for ln in r["stdout"].splitlines()
                if ln.strip()] if r["ok"] else []

    # ── Tier 3: full agent one-shot ───────────────────────────────────────

    def run_task(self, task: str, timeout_s: float | None = None) -> dict:
        """``hermes -z <task>`` — agent loop penuh (web, file, terminal,
        cron, delegation, computer-use, dst). BLOCKING sampai selesai —
        panggil hanya dari worker thread (async_dispatch)."""
        args: list[str] = []
        if self.model:
            args += ["-m", self.model]
        if self.toolsets:
            args += ["-t", self.toolsets]
        args += ["-z", task]
        return self._run(args, timeout=timeout_s or self.task_timeout_s)

    # ── Tier 2: konfigurasi & gateway (PARITY v2 Fase 3) ──────────────────

    def config_set(self, key: str, value: str) -> dict:
        """``hermes config set <key> <value>`` — key dotted masuk
        config.yaml Hermes, key UPPERCASE masuk .env Hermes. Tanpa LLM."""
        return self._run(["config", "set", key, str(value)],
                         timeout=self.send_timeout_s)

    def gateway_command(self, action: str, timeout_s: float = 90) -> dict:
        """``hermes gateway <status|restart|start|stop>``."""
        if action not in ("status", "restart", "start", "stop"):
            return {"ok": False, "error": f"aksi gateway asing: {action}",
                    "stdout": "", "stderr": "", "exit": -1, "elapsed_ms": 0.0}
        return self._run(["gateway", action], timeout=timeout_s)

    # ── health ────────────────────────────────────────────────────────────

    def check(self) -> dict:
        """Probe ringan untuk boot check: version saja (~0.8 s)."""
        if not is_enabled():
            return {"ok": False, "detail": _DISABLED_ERROR}
        exe = self._exe()
        if exe is None:
            return {"ok": False, "detail": "hermes CLI tidak di PATH"}
        r = self._run(["version"], timeout=15)
        if r["ok"]:
            first = (r["stdout"].splitlines() or [""])[0].strip()
            return {"ok": True, "detail": first[:80]}
        return {"ok": False, "detail": r.get("error") or r["stderr"][:80]}
