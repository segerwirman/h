from __future__ import annotations

import asyncio

from jarvis.agent.tools.capability_status import CapabilityStatus


def test_capability_status_reports_ready_and_blocked(monkeypatch):
    monkeypatch.setattr(
        "jarvis.agent.model_routing.role_statuses",
        lambda: {
            "heavy": {
                "configured": True,
                "provider": "custom",
                "model": "work-model",
                "reason": "test",
            }
        },
    )
    monkeypatch.setattr(
        "jarvis.agent.toolgroups.all_groups",
        lambda: [
            {
                "name": "Application Control",
                "available": True,
                "enabled": True,
                "tools": ["open_app"],
                "availability_reason": "",
            },
            {
                "name": "Google Cloud",
                "available": False,
                "enabled": True,
                "tools": [],
                "availability_reason": "Hubungkan Google OAuth.",
            },
        ],
    )
    result = asyncio.run(CapabilityStatus().run())
    assert result.ok
    assert "READY Application Control" in result.content
    assert "BLOCKED Google Cloud" in result.content
    assert result.meta["ready_groups"] == 1
