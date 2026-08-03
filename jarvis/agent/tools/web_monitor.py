"""Phase 17A: one-shot read-only fetch of a validated public monitor source."""
from __future__ import annotations

import asyncio
from pydantic import BaseModel, Field
from jarvis.agent.base import Tool, ToolResult
from jarvis.monitoring.fetch import fetch_source
from jarvis.monitoring.sources import MonitorSource

class _Params(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=8, max_length=2048)
    mode: str = Field(description="api | rss | html")
    rate_limit_s: int = Field(60, ge=5, le=86400)
    max_items: int = Field(5, ge=1, le=20)

class WebMonitor(Tool):
    name = "web_monitor"
    description = "Periksa satu source publik HTTPS secara read-only (API/RSS/HTML), tanpa login/browser/cookies."
    params_schema = _Params
    read_only = True
    timeout_s = 45
    async def run(self, name: str, url: str, mode: str, rate_limit_s: int = 60,
                  max_items: int = 5, **_) -> ToolResult:
        try:
            source = MonitorSource.create(name, url, mode, rate_limit_s=rate_limit_s)
        except ValueError as exc:
            return ToolResult.fail(f"source_policy_rejected:{exc}")
        result = await asyncio.to_thread(fetch_source, source, max_items=max_items)
        if not result.get("ok"):
            return ToolResult.fail(str(result.get("reason", "source_unavailable")))
        return ToolResult.success(result, display=f"{len(result['items'])} item dari {source.name}")

__all__ = ["WebMonitor"]
