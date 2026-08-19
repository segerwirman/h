"""Cuaca: fallback log player tidak boleh gagal diam tanpa jejak."""
from __future__ import annotations

from actions import weather_report as weather
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
