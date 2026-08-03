"""Phase 17D: local, opt-in briefing after boot readiness.

This module deliberately has no fetcher, scheduler, Telegram, or UI imports.
It runs the existing bounded briefing tool in a daemon worker and hands the
result to an injected local sink.
"""
from __future__ import annotations

import asyncio
import threading

from jarvis.core import briefing, log

_logger = log.get("integrations.boot_briefing")


def _tool():
    from jarvis.agent.tools.briefing_tool import BriefingTool
    return BriefingTool()


def build_local_briefing() -> str:
    """Build from existing safe Calendar/Gmail/monitor summary seams only."""
    result = asyncio.run(_tool().run())
    if not getattr(result, "ok", False):
        return ""
    content = getattr(result, "content", {})
    return str(content.get("briefing", "")).strip() if isinstance(content, dict) else ""


def start_if_enabled(deliver) -> bool:
    """Schedule local briefing after boot without delaying readiness/UI."""
    if not briefing.boot_briefing_enabled():
        return False

    def worker() -> None:
        try:
            text = build_local_briefing()
            if text:
                deliver(text)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("boot_briefing.failed", error=type(exc).__name__)

    threading.Thread(target=worker, daemon=True, name="boot-briefing").start()
    return True


__all__ = ["build_local_briefing", "start_if_enabled"]
