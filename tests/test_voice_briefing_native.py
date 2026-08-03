"""18B native execution returns only the safe briefing field."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace


def test_native_voice_briefing_exec_uses_registry_and_returns_no_raw_payload(monkeypatch):
    from jarvis.integrations import voice_native_tools
    from jarvis.agent.base import ToolResult

    class Legacy:
        TOOL_DECLARATIONS = []
        class JarvisLive:
            async def _execute_tool(self, fc):
                return {"legacy": fc.name}
        class types:
            @staticmethod
            def FunctionResponse(**kwargs): return kwargs
        @staticmethod
        def _load_system_prompt(): return ""

    async def execute(name, args, **_):
        assert name == "voice_briefing" and args == {}
        return ToolResult.success({"briefing": "Agenda aman."}, display="Agenda aman.")

    from jarvis.agent import registry
    monkeypatch.setattr(registry, "execute", execute)
    voice_native_tools.install(Legacy)
    response = asyncio.run(Legacy.JarvisLive()._execute_tool(SimpleNamespace(id="b", name="voice_briefing", args={})))
    assert response["response"]["ok"] is True
    assert set(json.loads(response["response"]["result"])) == {"briefing"}
    assert "raw" not in str(response)


def test_voice_briefing_is_read_only_and_no_confirmation():
    from jarvis.agent.tools.voice_briefing import VoiceBriefing
    tool = VoiceBriefing()
    assert tool.read_only is True
    assert tool.requires_confirmation is False
    assert tool.params_schema.model_fields == {}
