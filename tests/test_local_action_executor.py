"""Shared local action execution must keep PROMPT N memory bridge intact."""
from __future__ import annotations

import asyncio

import pytest

from jarvis.core.action_registry import Action


def test_text_action_queues_one_notice_and_returns_confirmation(monkeypatch):
    from jarvis.integrations import local_action_executor as executor

    notices = []
    monkeypatch.setattr(executor.voice_notices, "remember_action", notices.append)
    monkeypatch.setattr(executor, "_work", lambda _action: None)
    action = Action("app", "spotify", "open", {"app": "Spotify"})

    result = asyncio.run(executor.submit(action))

    assert result == "Membuka Spotify."
    assert notices == [action]


def test_unsupported_action_does_not_write_notice(monkeypatch):
    from jarvis.integrations import local_action_executor as executor

    notices = []
    monkeypatch.setattr(executor.voice_notices, "remember_action", notices.append)

    with pytest.raises(ValueError, match="unsupported_local_action"):
        asyncio.run(executor.submit(Action("panel", "kamera", "open", {"panel": "kamera"})))

    assert notices == []


def test_typed_unsupported_action_falls_open_without_traceback():
    from jarvis.ui.window import execute_typed_action

    action = Action("panel", "kamera", "open", {"panel": "kamera"})

    assert execute_typed_action(action) is None


def test_voice_l1_delegates_to_shared_submitter(monkeypatch):
    from jarvis.integrations import voice_l1
    from jarvis.integrations import local_action_executor as executor

    assert voice_l1._submit_default is executor.submit


def test_typed_execution_reuses_shared_submitter(monkeypatch):
    from jarvis.ui.window import execute_typed_action
    from jarvis.integrations import local_action_executor as executor

    seen = []

    async def submit(action):
        seen.append(action)
        return "Membuka Spotify."

    monkeypatch.setattr(executor, "submit", submit)
    action = Action("app", "spotify", "open", {"app": "Spotify"})

    assert execute_typed_action(action) == "Membuka Spotify."
    assert seen == [action]
