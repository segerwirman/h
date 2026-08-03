"""Fase 15A: paired Telegram mendapat catalog read-only GWS yang sangat sempit."""
from __future__ import annotations


def _remote():
    from jarvis.gateway.base import InboundMessage
    return InboundMessage("m1", "telegram", "chat-7", "actor-9").execution_context()


def test_remote_context_exposes_only_safe_gws_read_tools(monkeypatch):
    from jarvis.agent import capabilities
    from jarvis.agent import registry

    safe = {"gmail_safe_summary", "gcal_safe_agenda", "morning_briefing"}
    original = registry.all_tools
    monkeypatch.setattr(registry, "all_tools", lambda refresh=False: {
        name: object() for name in safe | {"gmail_read", "gmail_send", "gcal_create", "desktop_safe_click"}
    })

    names = set(capabilities.REGISTRY.exposed_tool_names(_remote()))

    assert safe <= names
    assert not {"gmail_read", "gmail_send", "gcal_create", "desktop_safe_click",
                "remote_setup", "terminal", "file_write"} & names


def test_remote_schema_excludes_secret_and_mutating_gws_tools(monkeypatch):
    from jarvis.agent import registry
    from jarvis.gateway.base import InboundMessage

    class _Tool:
        def __init__(self, name, read_only=True):
            self.name, self.read_only, self.requires_confirmation = name, read_only, not read_only
            self.description = name
        def json_schema(self): return {"name": self.name}
        def is_available(self): return True

    tools = {
        "gmail_safe_summary": _Tool("gmail_safe_summary"),
        "gcal_safe_agenda": _Tool("gcal_safe_agenda"),
        "morning_briefing": _Tool("morning_briefing"),
        "gmail_send": _Tool("gmail_send", False),
        "gcal_create": _Tool("gcal_create", False),
    }
    monkeypatch.setattr(registry, "all_tools", lambda refresh=False: tools)

    ctx = InboundMessage("m1", "telegram", "chat", "actor").execution_context()
    names = {x["function"]["name"] for x in registry.schemas(context=ctx)}

    assert {"gmail_safe_summary", "gcal_safe_agenda", "morning_briefing"} <= names
    assert not {"gmail_send", "gcal_create", "remote_setup"} & names


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
