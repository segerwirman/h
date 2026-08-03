"""Fase 8: approval desktop-local dan audit metadata-only."""
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


def test_desktop_safe_audit_contains_only_opaque_metadata():
    from jarvis.agent import registry

    record = registry._audit_args(
        "desktop_safe_set_value",
        {"observation_id": "opaque-observation", "element_id": "opaque-element",
         "value": 30, "_session": object(), "_context": object()},
    )

    assert record == {
        "observation_id": "opaque-observation",
        "element_id": "opaque-element",
        "action": "desktop_safe_set_value",
    }
    assert "value" not in record
    assert "_session" not in record
    assert "_context" not in record


def test_ui_adapter_declares_desktop_local_confirmation_authority():
    from jarvis.agent.adapters.ui import UIAdapter

    assert UIAdapter.desktop_local is True


def test_desktop_safe_audit_error_is_reason_code_not_ui_text(monkeypatch):
    from jarvis.agent import registry

    captured = []
    session_results = []
    monkeypatch.setattr("jarvis.agent.tool_usage.append_record", captured.append)
    result = type("Result", (), {"ok": False, "error": "raw ui label: password field"})()

    class Session:
        id = "desktop-a"

        def record_tool(self, _name, _args, session_result, _elapsed):
            session_results.append(session_result)

    registry._log_call(
        "desktop_safe_set_value",
        {"observation_id": "obs", "element_id": "el", "value": 30},
        result, 0.01, Session(),
    )

    assert captured[0]["args"] == {
        "observation_id": "obs", "element_id": "el", "action": "desktop_safe_set_value",
    }
    assert captured[0]["error"] == "desktop_safe_failed"
    assert session_results[0].error == "desktop_safe_failed"
    assert "password" not in repr(captured[0])
    assert "password" not in repr(session_results[0])
