"""A51d: media executor must verify intent-specific postconditions.

Regression: execute("play") returned ok=True with a paused state, and
execute("mute") returned ok=True with muted=False. Fix: postcondition per
action before rendering success.
"""
import asyncio

from jarvis.agent.remote_media_execution import execute


class _Result:
    def __init__(self, state):
        self.ok = True
        self.content = state


def _runner_for(state):
    async def runner(**kwargs):
        return _Result(state)
    return runner


def test_play_rejects_paused_state():
    result = asyncio.run(execute("play", runner=_runner_for({
        "playing": False, "muted": False, "volume": 0.2,
    })))
    assert result["ok"] is False
    assert result["reason"] == "remote_media_state_not_matched"


def test_pause_rejects_playing_state():
    result = asyncio.run(execute("pause", runner=_runner_for({
        "playing": True, "muted": False, "volume": 0.2,
    })))
    assert result["ok"] is False
    assert result["reason"] == "remote_media_state_not_matched"


def test_mute_rejects_unmuted_state():
    result = asyncio.run(execute("mute", runner=_runner_for({
        "playing": True, "muted": False, "volume": 0.2,
    })))
    assert result["ok"] is False
    assert result["reason"] == "remote_media_state_not_matched"


def test_unmute_rejects_muted_state():
    result = asyncio.run(execute("unmute", runner=_runner_for({
        "playing": True, "muted": True, "volume": 0.2,
    })))
    assert result["ok"] is False
    assert result["reason"] == "remote_media_state_not_matched"


def test_play_accepts_playing_state():
    result = asyncio.run(execute("play", runner=_runner_for({
        "playing": True, "muted": False, "volume": 0.2,
    })))
    assert result["ok"] is True
    assert result["media"]["state"] == "playing"


def test_mute_accepts_muted_state():
    result = asyncio.run(execute("mute", runner=_runner_for({
        "playing": True, "muted": True, "volume": 0.2,
    })))
    assert result["ok"] is True
    assert result["media"]["muted"] is True
