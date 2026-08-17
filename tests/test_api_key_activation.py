from __future__ import annotations

import os
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from jarvis.ui.window_voice import WindowVoiceMixin
from jarvis.ui.window_widgets import ApiKeySheet


_APP = QApplication.instance() or QApplication([])


class _FakeSheet:
    def __init__(self) -> None:
        self.busy = True
        self.statuses: list[tuple[str, str]] = []
        self.clear_calls = 0
        self.hide_calls = 0
        self.show_calls = 0
        self.raise_calls = 0

    def set_busy(self, busy: bool) -> None:
        self.busy = busy

    def set_status(self, text: str, kind: str = "info") -> None:
        self.statuses.append((text, kind))

    def clear_secret(self) -> None:
        self.clear_calls += 1

    def hide(self) -> None:
        self.hide_calls += 1

    def show(self) -> None:
        self.show_calls += 1

    def raise_(self) -> None:
        self.raise_calls += 1


class _FakeSignal:
    def __init__(self) -> None:
        self.emitted: list[tuple[bool, str]] = []

    def emit(self, ok: bool, detail: str) -> None:
        self.emitted.append((ok, detail))


def _window() -> WindowVoiceMixin:
    window = object.__new__(WindowVoiceMixin)
    window._ready = False
    window._api_sheet = _FakeSheet()
    window._api_key_verified_sig = _FakeSignal()
    window.messages = []
    window.write_log = window.messages.append
    return window


def test_boot_check_uses_credential_presence_without_provider_probe(monkeypatch):
    from jarvis.core import llm

    monkeypatch.setattr(llm, "api_key", lambda: "stored-secret")
    monkeypatch.setattr(
        llm,
        "probe",
        lambda: (_ for _ in ()).throw(AssertionError("boot must not probe provider")),
    )

    assert object.__new__(WindowVoiceMixin)._check_config() is True


def test_core_gemini_client_has_bounded_request_timeout(monkeypatch):
    from google import genai
    from jarvis.core import llm

    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace()

    monkeypatch.setattr(genai, "Client", fake_client)
    monkeypatch.setattr(llm, "api_key", lambda: "fake-test-secret")
    original_get = llm.config.get
    monkeypatch.setattr(
        llm.config,
        "get",
        lambda key, default=None: 7
        if key == "llm.request_timeout_s"
        else original_get(key, default),
    )
    monkeypatch.setattr(llm, "_client", None)

    llm._get_client()

    assert captured["http_options"].timeout == 7000


def test_api_key_sheet_empty_submit_is_visible_and_valid_submit_is_single_shot():
    sheet = ApiKeySheet(None)
    emitted = []
    sheet.done.connect(emitted.append)

    sheet._submit()

    assert "API key" in sheet.status_text
    assert sheet.status_kind == "error"
    assert emitted == []

    sheet._key.setText("fake-test-secret")
    sheet._submit()
    sheet._submit()

    assert emitted == ["fake-test-secret"]
    assert sheet.busy is True
    assert sheet._key.isEnabled() is False
    assert sheet._activate.isEnabled() is False


def test_api_key_store_failure_is_inline_and_retryable(monkeypatch):
    from jarvis.core import secrets_store

    window = _window()
    monkeypatch.setattr(secrets_store, "set", lambda _key, _value: False)

    window._on_api_key("fake-test-secret")

    assert window._ready is False
    assert window._api_sheet.busy is False
    assert window._api_sheet.statuses[-1][1] == "error"
    assert "terenkripsi" in window._api_sheet.statuses[-1][0]
    assert window._api_key_verified_sig.emitted == []


def test_probe_worker_only_emits_and_ui_slot_owns_success_state(monkeypatch):
    from jarvis.core import llm, secrets_store

    window = _window()
    monkeypatch.setattr(secrets_store, "set", lambda _key, _value: True)
    monkeypatch.setattr(llm, "reset_client", lambda: None)
    monkeypatch.setattr(llm, "probe", lambda: (True, "provider responded"))
    monkeypatch.setattr("threading.Thread.start", lambda thread: thread.run())

    window._on_api_key("fake-test-secret")

    assert window._ready is False
    assert window._api_sheet.clear_calls == 1
    assert window._api_sheet.hide_calls == 0
    assert window._api_key_verified_sig.emitted == [(True, "provider responded")]

    window._on_api_key_verified(True, "provider responded")

    assert window._ready is True
    assert window._api_sheet.hide_calls == 1
    assert any("sistem online" in message for message in window.messages)


def test_failed_probe_stays_visible_and_can_retry():
    window = _window()

    window._on_api_key_verified(False, "provider tidak merespons")

    assert window._ready is False
    assert window._api_sheet.hide_calls == 0
    assert window._api_sheet.show_calls == 1
    assert window._api_sheet.raise_calls == 1
    assert window._api_sheet.busy is False
    assert window._api_sheet.statuses[-1][1] == "error"
    assert "belum online" in window._api_sheet.statuses[-1][0]
