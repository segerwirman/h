"""Code helper: screenshot cleanup failure stays observable and bounded."""
from __future__ import annotations

import sys
import types

from actions import code_helper
from jarvis.core import quiet


def test_screen_debug_cleanup_failure_records_event_without_provider(monkeypatch):
    class Screenshot:
        def read_bytes(self):
            return b"fake image"

        def unlink(self):
            raise OSError("screenshot locked")

    class Response:
        text = "analysis result"

    class Models:
        def generate_content(self, **_kwargs):
            return Response()

    class Client:
        def __init__(self, **_kwargs):
            self.models = Models()

    fake_types = types.ModuleType("google.genai.types")
    fake_types.Part = types.SimpleNamespace(
        from_bytes=lambda **_kwargs: "fake part",
    )
    fake_genai = types.ModuleType("google.genai")
    fake_genai.Client = Client
    fake_genai.types = fake_types
    fake_google = types.ModuleType("google")
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)

    events = []
    monkeypatch.setattr(
        quiet,
        "swallowed",
        lambda event, exc=None, **context: events.append((event, exc, context)),
    )
    monkeypatch.setattr(code_helper, "_take_screenshot", lambda: Screenshot())
    monkeypatch.setattr(code_helper, "_get_api_key", lambda: "fake-key")
    monkeypatch.setattr(code_helper, "_image_to_base64", lambda _path: "ignored")

    result = code_helper._screen_debug_action("describe", "", None)

    assert result == "analysis result"
    assert len(events) == 1
    assert events[0][0] == "actions.code_helper.screenshot_cleanup_failed"
    assert isinstance(events[0][1], OSError)
