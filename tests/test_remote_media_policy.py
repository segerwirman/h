"""15C narrow remote media policy and verified metadata contract."""
from __future__ import annotations


def test_remote_media_policy_accepts_only_named_media_states():
    from jarvis.agent.remote_media_policy import admit

    for action in ("status", "play", "pause", "mute", "unmute", "volume_up", "volume_down"):
        assert admit(action) == {"allowed": True, "action": action}
    for action in ("toggle", "set_volume", "skip_ad", "navigate", "open_url", "click", "", "play all"):
        assert admit(action) == {"allowed": False, "reason": "remote_media_action_rejected"}


def test_remote_media_result_is_metadata_only_and_redacts_page_content():
    from jarvis.agent.remote_media_policy import render_result

    result = render_result({"playing": True, "paused": False, "muted": False,
                            "volume": 0.75, "playerTitle": "private song",
                            "playerVideoId": "abc", "url": "https://private"})
    assert result == {"ok": True, "media": {"state": "playing", "muted": False, "volume_percent": 75}}
    assert "private" not in str(result)


def test_unavailable_or_malformed_media_has_fixed_safe_reason():
    from jarvis.agent.remote_media_policy import render_result

    assert render_result(None) == {"ok": False, "reason": "remote_media_unavailable"}
    assert render_result({"playing": "yes"}) == {"ok": False, "reason": "remote_media_unavailable"}


def test_non_finite_media_volume_fails_closed_with_fixed_safe_reason():
    from jarvis.agent.remote_media_policy import render_result

    for volume in (float("nan"), float("inf"), float("-inf")):
        result = render_result({"playing": True, "muted": False, "volume": volume})
        assert result == {"ok": False, "reason": "remote_media_unavailable"}


def test_remote_media_policy_has_no_browser_navigation_or_desktop_surface():
    from jarvis.agent import remote_media_policy
    source = open(remote_media_policy.__file__, encoding="utf-8").read().lower()
    for forbidden in ("browser_navigate", "open_url", "playwright", "coordinate", "screenshot", "uia", "telegram", "subprocess"):
        assert forbidden not in source
