"""Desktop-safe confirmation is accepted only from the active native UI adapter."""

from __future__ import annotations

import asyncio

from jarvis.agent.execution_context import ExecutionContext

def _context():
    return ExecutionContext.create(
        source="agent", actor_id="local", session_id="desktop-a", surface="desktop",
        toolsets=["desktop_safe"],
    )

def test_set_value_rejects_non_desktop_confirmation_adapter_before_executor(monkeypatch):
    from jarvis.agent import registry

    tool = registry.get("desktop_safe_set_value")
    monkeypatch.setattr(tool, "run", lambda **_: (_ for _ in ()).throw(AssertionError("must not run")))

    class RemoteLikeAdapter:
        name = "telegram"
        interactive = True

        async def ask(self, *_):
            return "Lanjut"

    result = asyncio.run(registry.execute(
        "desktop_safe_set_value",
        {"observation_id": "opaque-observation", "element_id": "opaque-element", "value": 30},
        adapter=RemoteLikeAdapter(),
        session=type("Session", (), {"id": "desktop-a"})(), context=_context(),
    ))

    assert result.ok is False
    assert "desktop-local" in (result.error or "")

def test_set_value_rejects_forged_desktop_local_adapter_before_executor(monkeypatch):
    from jarvis.agent import registry

    tool = registry.get("desktop_safe_set_value")
    monkeypatch.setattr(tool, "run", lambda **_: (_ for _ in ()).throw(AssertionError("must not run")))

    class ForgedAdapter:
        name = "ui"
        interactive = True
        desktop_local = True

        async def ask(self, *_):
            return "Lanjut"

    result = asyncio.run(registry.execute(
        "desktop_safe_set_value",
        {"observation_id": "opaque-observation", "element_id": "opaque-element", "value": 30},
        adapter=ForgedAdapter(),
        session=type("Session", (), {"id": "desktop-a"})(), context=_context(),
    ))

    assert result.ok is False
    assert "desktop-local" in (result.error or "")

def test_set_value_accepts_active_native_ui_adapter_confirmation(monkeypatch):
    from jarvis.agent import registry
    from jarvis.agent.adapters.ui import UIAdapter
    from jarvis.agent.base import ToolResult

    tool = registry.get("desktop_safe_set_value")
    calls = []

    async def run(**kwargs):
        calls.append(kwargs)
        return ToolResult.success("ok")

    monkeypatch.setattr(tool, "run", run)
    adapter = UIAdapter()
    monkeypatch.setattr(adapter, "_win", lambda: object())

    async def ask(*_):
        return "Lanjut"

    monkeypatch.setattr(adapter, "ask", ask)

    result = asyncio.run(registry.execute(
        "desktop_safe_set_value",
        {"observation_id": "opaque-observation", "element_id": "opaque-element", "value": 30},
        adapter=adapter,
        session=type("Session", (), {"id": "desktop-a"})(), context=_context(),
    ))

    assert result.ok is True
    assert calls[0]["_desktop_safe_confirmation"] is True
