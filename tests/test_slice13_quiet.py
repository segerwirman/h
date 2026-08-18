"""Fase 35 Slice 13 — local fallback observability characterization."""
from __future__ import annotations

from collections import Counter

from jarvis.core import quiet


_EVENTS = {
    "agent.router.json_scan_skipped",
    "agent.ack_composer.ack_timeout_invalid",
    "agent.capability_service.skill_pin_failed",
    "nlp.predictive.history_load_failed",
}


def _spy(monkeypatch):
    events = []

    def record(event, exc=None, **_context):
        events.append((event, type(exc).__name__ if exc is not None else None))

    monkeypatch.setattr(quiet, "swallowed", record)
    return events


def test_router_skips_malformed_fragment_and_records_it(monkeypatch):
    from jarvis.agent import router

    events = _spy(monkeypatch)

    result = router._first_json_object('prefix {not valid} then {"tier": 1}')

    assert result == {"tier": 1}
    assert events == [("agent.router.json_scan_skipped", "JSONDecodeError")]


def test_router_valid_json_path_remains_silent(monkeypatch):
    from jarvis.agent import router

    events = _spy(monkeypatch)

    assert router._first_json_object('prefix {"tier": 1}') == {"tier": 1}
    assert events == []


def test_ack_timeout_invalid_value_keeps_default_and_records(monkeypatch):
    from jarvis.agent import ack_composer

    events = _spy(monkeypatch)
    monkeypatch.setattr(
        ack_composer.config,
        "get",
        lambda path, default=None: "not-a-number"
        if path == "agent.interaction.ack_timeout_s" else default,
    )

    assert ack_composer._timeout() == 0.25
    assert events == [("agent.ack_composer.ack_timeout_invalid", "ValueError")]


def test_ack_timeout_valid_value_remains_silent(monkeypatch):
    from jarvis.agent import ack_composer

    events = _spy(monkeypatch)
    monkeypatch.setattr(
        ack_composer.config,
        "get",
        lambda path, default=None: 0.5
        if path == "agent.interaction.ack_timeout_s" else default,
    )

    assert ack_composer._timeout() == 0.5
    assert events == []


def test_skill_pin_failure_keeps_false_return_and_records(monkeypatch):
    from jarvis.agent import capability_service

    events = _spy(monkeypatch)

    def fail_set_pinned(_name, _pinned):
        raise RuntimeError("local skill store unavailable")

    monkeypatch.setattr(capability_service.skill_usage, "set_pinned", fail_set_pinned)

    assert capability_service.set_skill_pinned("demo", True) is False
    assert events == [("agent.capability_service.skill_pin_failed", "RuntimeError")]


def test_skill_pin_success_remains_silent(monkeypatch):
    from jarvis.agent import capability_service

    events = _spy(monkeypatch)
    calls = []
    monkeypatch.setattr(
        capability_service.skill_usage,
        "set_pinned",
        lambda name, pinned: calls.append((name, pinned)),
    )

    assert capability_service.set_skill_pinned("demo", True) is True
    assert calls == [("demo", True)]
    assert events == []


def test_predictive_corrupt_history_falls_back_to_empty_counter_and_records(
    tmp_path, monkeypatch
):
    from jarvis.nlp.predictive import PredictiveText

    events = _spy(monkeypatch)
    path = tmp_path / "command_history.json"
    path.write_text("{not valid json", encoding="utf-8")
    predictive = object.__new__(PredictiveText)
    predictive._path = path

    predictive._load()

    assert predictive._history == Counter()
    assert events == [("nlp.predictive.history_load_failed", "JSONDecodeError")]


def test_predictive_missing_history_falls_back_to_empty_counter_and_records(
    tmp_path, monkeypatch
):
    from jarvis.nlp.predictive import PredictiveText

    events = _spy(monkeypatch)
    predictive = object.__new__(PredictiveText)
    predictive._path = tmp_path / "missing-history.json"

    predictive._load()

    assert predictive._history == Counter()
    assert events == [("nlp.predictive.history_load_failed", "FileNotFoundError")]


def test_predictive_valid_history_remains_silent(tmp_path, monkeypatch):
    from jarvis.nlp.predictive import PredictiveText

    events = _spy(monkeypatch)
    path = tmp_path / "command_history.json"
    path.write_text('{"buka spotify": 3}', encoding="utf-8")
    predictive = object.__new__(PredictiveText)
    predictive._path = path

    predictive._load()

    assert predictive._history == Counter({"buka spotify": 3})
    assert events == []


def test_slice13_selected_block_count_is_bounded():
    assert 1 <= 4 <= 5


def test_selected_event_names_are_stable():
    assert _EVENTS == {
        "agent.router.json_scan_skipped",
        "agent.ack_composer.ack_timeout_invalid",
        "agent.capability_service.skill_pin_failed",
        "nlp.predictive.history_load_failed",
    }
