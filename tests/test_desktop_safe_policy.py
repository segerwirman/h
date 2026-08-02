"""Direct desktop-safe policy matrix."""
from __future__ import annotations

import asyncio

from jarvis.agent.execution_context import ExecutionContext
from jarvis.core.element_model import ScreenElementTree


def _context(*, surface="desktop", source="ui", toolsets=("desktop_safe",)):
    return ExecutionContext.create(
        source=source, actor_id="local-user", session_id="desktop-a",
        surface=surface, toolsets=toolsets,
    )

def test_desktop_safe_policy_allows_only_desktop_local_context():
    from jarvis.agent import policy

    for surface, source, toolsets, allowed in (
        ("desktop", "ui", ("desktop_safe",), True),
        ("desktop", "agent", ("desktop_safe",), True),
        ("voice", "gemini_live", ("desktop_safe",), False),
        ("remote", "telegram", ("desktop_safe",), False),
        ("desktop", "cron", ("desktop_safe",), False),
        ("desktop", "delegation", ("desktop_safe",), False),
        ("desktop", "ui", ("local",), False),
    ):
        decision = policy.decide(
            _context(surface=surface, source=source, toolsets=toolsets),
            capability="desktop_safe.desktop_observe", risk="medium",
        )
        assert decision.allowed is allowed


def test_desktop_safe_tool_rejects_context_session_mismatch_before_authority_use():
    from jarvis.agent.tools.desktop_observe import DesktopObserve
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    tree = ScreenElementTree()
    gate = CuaSafetyGate()
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)), lambda _rect: None,
    )
    context = ExecutionContext.create(
        source="agent", actor_id="local-user", session_id="context-b", surface="desktop",
        toolsets=["desktop_safe"],
    )
    result = asyncio.run(DesktopObserve(session=authority).run(
        _session=type("Session", (), {"id": "runtime-a"})(), _context=context,
    ))

    assert result.ok is False
    assert "session" in (result.error or "").lower()
