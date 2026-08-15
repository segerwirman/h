"""UI BUS events are delivered only to subscribers present at publication."""
from __future__ import annotations

from jarvis.core.bus import EventBus


def test_late_ui_subscriber_does_not_receive_historical_event():
    bus = EventBus()
    early: list[dict] = []
    late: list[dict] = []

    bus.subscribe("info.card", early.append, ui=True)
    bus.publish("info.card", title="before late window existed")
    bus.subscribe("info.card", late.append, ui=True)

    bus.drain_ui()

    assert early == [{"title": "before late window existed"}]
    assert late == []


def test_each_ui_publish_captures_its_current_subscribers():
    bus = EventBus()
    first: list[str] = []
    second: list[str] = []

    bus.subscribe("topic", lambda data: first.append(data["value"]), ui=True)
    bus.publish("topic", value="old")
    bus.subscribe("topic", lambda data: second.append(data["value"]), ui=True)
    bus.publish("topic", value="new")

    bus.drain_ui()

    assert first == ["old", "new"]
    assert second == ["new"]
