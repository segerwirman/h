"""Agentic Browser (Modul 4 & 5) — integration with vercel-labs/agent-browser.

Wraps the real ``agent-browser`` CLI (https://github.com/vercel-labs/agent-browser),
a browser-automation tool for AI agents that drives Chrome/Chromium over CDP and
returns accessibility-tree snapshots with compact ``@eN`` element refs.

Real CLI surface (matched here):
    agent-browser [--cdp <port|ws-url>] snapshot [-i]     # "see" the page
    agent-browser [--cdp <port|ws-url>] click  <@eN|css>  # interact
    agent-browser [--cdp <port|ws-url>] type   <@eN|css> <text>
    agent-browser [--cdp <port|ws-url>] open   <url>

An optional ``--cdp`` target may attach to a browser session owned by the
agent tool. This module never mounts a browser in ContentStage. The executable,
CDP flag, and snapshot flags remain configurable for installed CLI variants.
"""
from __future__ import annotations

import shutil
import subprocess

from jarvis.core import config, log

_logger = log.get("browser.agent")


class BrowserAgent:
    def __init__(self, executable: str | None = None, cdp: str | None = None):
        self.executable = executable or str(config.get(
            "browser.agent_cli.executable", "agent-browser"))
        self._resolved_exe: str | None = None
        # `--cdp` accepts a bare port (→ http://localhost:PORT) or a ws:// URL.
        self.cdp = cdp or str(config.get(
            "browser.agent_cli.cdp", "")) or None
        self._cdp_flag = str(config.get(
            "browser.agent_cli.cdp_flag", "--cdp"))
        self._snapshot_args = list(config.get(
            "browser.agent_cli.snapshot_args", ["snapshot", "-i"]))
        self._timeout = float(config.get(
            "browser.agent_cli.timeout_s", 15))

    def attach(self, cdp: str | int) -> None:
        """Point the agent at an owned browser CDP port or ws:// URL."""
        self.cdp = str(cdp) if cdp else None

    def _resolve_executable(self) -> str:
        """Resolve the CLI name to a runnable path (cached).

        On Windows, npm installs global CLIs as ``.cmd``/``.ps1`` shims with no
        ``.exe``. ``subprocess.run(["agent-browser", …])`` (no ``shell``) uses
        CreateProcess, which only finds ``.exe`` and raises ``FileNotFoundError``
        even when the CLI IS installed — the "browser.agent.missing" log. Passing
        the full ``…\\agent-browser.CMD`` path (which ``shutil.which`` resolves
        via PATHEXT) runs correctly. If nothing is found, fall back to the bare
        name so a genuinely-missing CLI still degrades honestly."""
        if self._resolved_exe is None:
            self._resolved_exe = shutil.which(self.executable) or self.executable
        return self._resolved_exe

    def _base(self) -> list[str]:
        cmd = [self._resolve_executable()]
        if self.cdp:
            cmd += [self._cdp_flag, str(self.cdp)]
        return cmd

    def _run(self, args: list[str]) -> subprocess.CompletedProcess | None:
        try:
            return subprocess.run(self._base() + args, capture_output=True,
                                  text=True, timeout=self._timeout)
        except FileNotFoundError:
            _logger.error("browser.agent.missing",
                         detail="agent-browser CLI not found in PATH — "
                                "install it: npm install -g agent-browser")
            return None
        except Exception as e:
            _logger.error("browser.agent.run_error", error=str(e)[:120])
            return None

    def get_accessibility_tree(self) -> str | None:
        """Snapshot of the current page (interactive elements with @eN refs).

        Returns the CLI's text snapshot — passed straight to the LLM, which
        selects a ``CLICK @eN`` / ``TYPE @eN | text`` / ``GOTO url`` action.
        None means the agent-browser CLI is unavailable / errored."""
        r = self._run(self._snapshot_args)
        if r is None:
            return None
        if r.returncode == 0:
            return (r.stdout or "").strip() or None
        _logger.warning("browser.agent.snapshot_failed", error=(r.stderr or "")[:100])
        return None

    def execute_action(self, action_type: str, target_id: str | None = None,
                       value: str | None = None) -> bool:
        """Execute one page action against the attached browser."""
        at = (action_type or "").lower()
        if at == "click" and target_id:
            args = ["click", str(target_id)]
        elif at in ("type", "fill") and target_id is not None:
            args = ["type", str(target_id), str(value or "")]
        elif at in ("goto", "open") and value:
            args = ["open", str(value)]
        else:
            _logger.warning("browser.agent.bad_action", action=action_type)
            return False
        r = self._run(args)
        if r is None:
            return False
        if r.returncode == 0:
            _logger.info("browser.agent.action_success", action=at, target=target_id)
            return True
        _logger.warning("browser.agent.action_failed", error=(r.stderr or "")[:100])
        return False

    def navigate(self, url: str) -> bool:
        """Navigate the attached browser to a URL (agent-browser ``open``)."""
        return self.execute_action("open", value=url)
