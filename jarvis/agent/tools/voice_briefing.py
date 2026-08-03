"""18B: voice-native wrapper around the existing safe briefing compositor."""
from __future__ import annotations

from pydantic import BaseModel

from jarvis.agent.base import Tool, ToolResult


class _NoParams(BaseModel):
    pass


def _safe_briefing() -> dict:
    """Return only the existing compositor's bounded display contract."""
    import asyncio
    from jarvis.agent.tools.briefing_tool import BriefingTool

    result = asyncio.run(BriefingTool().run())
    content = getattr(result, "content", {})
    return content if getattr(result, "ok", False) and isinstance(content, dict) else {}


class VoiceBriefing(Tool):
    name = "voice_briefing"
    description = "Bacakan briefing aman Calendar, Gmail, dan monitor; read-only."
    params_schema = _NoParams
    read_only = True
    timeout_s = 45

    async def run(self, **_) -> ToolResult:
        try:
            payload = await __import__("asyncio").to_thread(_safe_briefing)
            text = str(payload.get("briefing", "")).strip()
        except Exception:
            text = "Briefing saat ini belum tersedia."
        if not text:
            text = "Briefing saat ini belum tersedia."
        return ToolResult.success({"briefing": text[:600]}, display=text[:600])


__all__ = ["VoiceBriefing"]
