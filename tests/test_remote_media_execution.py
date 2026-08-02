"""15C verified media execution adapter."""
from __future__ import annotations

import asyncio


class _Result:
    def __init__(self, ok, content):
        self.ok, self.content = ok, content


def test_verified_media_executor_calls_only_allowed_action_and_returns_safe_metadata():
    from jarvis.agent.remote_media_execution import execute

    seen = []
    async def runner(**kwargs):
        seen.append(kwargs)
        return _Result(True, {"playing": False, "muted": True, "volume": 0.4,
                              "playerTitle": "hidden", "url": "https://hidden"})

    result = asyncio.run(execute("mute", runner=runner))
    assert result == {"ok": True, "media": {"state": "paused", "muted": True, "volume_percent": 40}}
    assert seen == [{"action": "mute"}]


def test_rejected_or_unverified_media_never_returns_raw_tool_content():
    from jarvis.agent.remote_media_execution import execute

    async def failed(**_):
        return _Result(False, {"url": "https://private", "error": "raw"})

    assert asyncio.run(execute("navigate", runner=failed)) == {"ok": False, "reason": "remote_media_action_rejected"}
    assert asyncio.run(execute("play", runner=failed)) == {"ok": False, "reason": "remote_media_unavailable"}


def test_malformed_runner_result_cannot_escape_fixed_safe_failure():
    from jarvis.agent.remote_media_execution import execute

    class HostileResult:
        @property
        def ok(self):
            raise RuntimeError("PRIVATE RUNNER ERROR")

    async def hostile(**_):
        return HostileResult()

    result = asyncio.run(execute("status", runner=hostile))

    assert result == {"ok": False, "reason": "remote_media_unavailable"}
    assert "PRIVATE" not in str(result)


def test_proposal_executor_maps_only_fixed_media_action_to_verified_runner():
    from jarvis.agent.remote_media_execution import execute_proposal

    seen = []
    async def runner(**kwargs):
        seen.append(kwargs)
        return _Result(True, {"playing": False, "muted": False, "volume": 0.6})

    result = asyncio.run(execute_proposal("media_pause", runner=runner))
    assert result == {"ok": True, "media": {"state": "paused", "muted": False, "volume_percent": 60}}
    assert seen == [{"action": "pause"}]
    assert asyncio.run(execute_proposal("media_set_volume", runner=runner)) == {"ok": False, "reason": "remote_media_action_rejected"}


def test_execution_source_does_not_contain_navigation_or_sensitive_surfaces():
    from jarvis.agent import remote_media_execution
    source = open(remote_media_execution.__file__, encoding="utf-8").read().lower()
    for forbidden in ("navigate", "open_url", "coordinate", "screenshot", "uia", "telegram", "subprocess"):
        assert forbidden not in source
