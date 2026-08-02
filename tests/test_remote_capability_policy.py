"""Focused regressions for bounded session-bound remote read rendering."""
from __future__ import annotations


def test_remote_read_output_is_session_bound_and_capped():
    from jarvis.agent.remote_read_policy import render_remote_read

    output = render_remote_read(
        {"unread_count": 30, "items": [{"sender": "ab…@x.com", "subject": "S", "time": "t"}] * 20},
        chat_id="chat-7", expected_chat_id="chat-7", max_items=3, max_chars=400)
    assert output["ok"] is True
    assert len(output["content"]) <= 400
    assert output["content"].count("ab…@x.com") <= 3

    denied = render_remote_read({"unread_count": 1, "items": []}, chat_id="other", expected_chat_id="chat-7")
    assert denied == {"ok": False, "reason": "remote_session_mismatch"}


def test_remote_read_renderer_rejects_raw_secret_or_path_fields():
    from jarvis.agent.remote_read_policy import render_remote_read

    result = render_remote_read({"token": "secret", "items": []}, chat_id="c", expected_chat_id="c")
    assert result == {"ok": False, "reason": "remote_read_payload_rejected"}


def test_remote_read_renderer_fails_closed_for_malformed_shapes_and_bounds():
    from jarvis.agent.remote_read_policy import render_remote_read

    malformed = (
        ({"unread_count": "not-a-count", "items": []}, {}),
        ({"unread_count": 1, "items": {"sender": "x"}}, {}),
        ({"count": 1, "items": "not-a-list"}, {}),
        ({"briefing": object()}, {}),
        ({"count": 1, "items": []}, {"max_items": "many"}),
        ({"count": 1, "items": []}, {"max_chars": None}),
    )
    for payload, limits in malformed:
        result = render_remote_read(
            payload, chat_id="chat-7", expected_chat_id="chat-7", **limits)
        assert result == {"ok": False, "reason": "remote_read_payload_rejected"}
