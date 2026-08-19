"""Cuaca: fallback log player tidak boleh gagal diam tanpa jejak."""
from __future__ import annotations

from actions import weather_report as weather
from jarvis.core import bus
from jarvis.core import locale as jlocale
from jarvis.core import quiet


def test_weather_log_player_failure_mencatat_event(monkeypatch):
    class FailingPlayer:
        def write_log(self, _line: str) -> None:
            raise OSError("log sink unavailable")

    events = []
    monkeypatch.setattr(
        quiet,
        "swallowed",
        lambda event, exc=None, **context: events.append((event, exc, context)),
    )

    weather._log("message", FailingPlayer())

    # Fallback tetap selesai tanpa melempar ulang.
    assert len(events) == 1
    assert events[0][0] == "actions.weather_report.player_log_failed"
    assert isinstance(events[0][1], OSError)


def test_weather_session_memory_failure_mencatat_event_tanpa_browser(monkeypatch):
    class FailingMemory:
        def set_last_search(self, **_kwargs):
            raise OSError("session memory unavailable")

    events = []
    monkeypatch.setattr(
        quiet,
        "swallowed",
        lambda event, exc=None, **context: events.append((event, exc, context)),
    )
    monkeypatch.setattr(
        weather._WEATHER_CACHE,
        "get_or_load",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        weather.webbrowser,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("browser must not be called")
        ),
    )
    monkeypatch.setattr(weather.METRICS, "record", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(jlocale, "resolve", lambda _city: None)
    monkeypatch.setattr(
        bus.BUS,
        "publish",
        lambda *_args, **_kwargs: None,
    )

    result = weather.weather_action(
        {"city": "Bandung", "time": "today"},
        session_memory=FailingMemory(),
    )

    assert result == "Showing the weather for Bandung, today, sir."
    assert len(events) == 1
    assert events[0][0] == "actions.weather_report.session_memory_failed"
    assert isinstance(events[0][1], OSError)
    assert events[0][2]["city"] == "Bandung"
    assert events[0][2]["time"] == "today"

    # The test reaches the local fallback without opening a browser.
    assert result.startswith("Showing the weather")



def test_weather_session_memory_success_preserves_result(monkeypatch):
    saved = []
    monkeypatch.setattr(
        weather._WEATHER_CACHE,
        "get_or_load",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(weather.METRICS, "record", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(jlocale, "resolve", lambda _city: None)
    monkeypatch.setattr(
        weather.webbrowser,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("browser must not be called")
        ),
    )

    class Memory:
        def set_last_search(self, **kwargs):
            saved.append(kwargs)

    result = weather.weather_action(
        {"city": "Bandung", "time": "today"},
        session_memory=Memory(),
    )

    assert result == "Showing the weather for Bandung, today, sir."
    assert saved == [{
        "query": "weather in Bandung today",
        "response": result,
    }]
