"""Remote Telegram light-lane policy regressions."""
from __future__ import annotations

import asyncio


def test_remote_telegram_reflex_tidak_menjalankan_desktop_control(monkeypatch):
    from jarvis.agent.adapters import telegram_light
    from jarvis.agent.execution_context import ExecutionContext
    from jarvis.agent.router import Route, Tier

    context = ExecutionContext.create(
        source="telegram", actor_id="42", session_id="99", surface="remote",
        toolsets={"messaging", "agent"},
    )
    route = Route(Tier.REFLEX, "light", "light", "reflex", 1.0)
    monkeypatch.setattr(
        telegram_light, "_reflex",
        lambda _text: (_ for _ in ()).throw(AssertionError("desktop reflex called")),
    )

    result = asyncio.run(telegram_light.execute("buka browser", route, context=context))

    assert result.ok is False
    assert "desktop" in result.error.lower()
