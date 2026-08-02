"""Direct desktop-safe policy matrix."""
from __future__ import annotations

from jarvis.agent.execution_context import ExecutionContext


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
