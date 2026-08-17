from __future__ import annotations

import types


class _FakeSignal:
    def __init__(self):
        self.emitted = []

    def emit(self, ok, detail):
        self.emitted.append((ok, detail))


def test_probe_requires_a_real_provider_response(monkeypatch):
    from jarvis.core import llm

    class Models:
        def generate_content(self, **_kwargs):
            return types.SimpleNamespace(text="OK")

    monkeypatch.setattr(
        llm,
        "_get_client",
        lambda: types.SimpleNamespace(models=Models()),
    )

    ok, detail = llm.probe()

    assert ok is True
    assert detail == "provider responded"


def test_api_key_callback_does_not_claim_online_before_probe(monkeypatch):
    from jarvis.core import llm, secrets_store
    from jarvis.ui.window_voice import WindowVoiceMixin

    monkeypatch.setattr(secrets_store, "set", lambda _key, _value: True)
    monkeypatch.setattr(llm, "reset_client", lambda: None)
    monkeypatch.setattr(llm, "probe", lambda: (False, "provider timeout"))
    monkeypatch.setattr(
        "threading.Thread.start",
        lambda thread: thread.run(),
    )

    window = object.__new__(WindowVoiceMixin)
    window._ready = False
    window._api_sheet = None
    window._api_key_verified_sig = _FakeSignal()
    messages = []
    window.write_log = messages.append

    window._on_api_key("new-secret")

    assert window._ready is False
    assert messages == []
    assert window._api_key_verified_sig.emitted == [
        (False, "provider timeout")
    ]

    window._on_api_key_verified(*window._api_key_verified_sig.emitted[0])

    assert window._ready is False
    assert any("belum online" in message for message in messages)
    assert not any("sistem online" in message for message in messages)


def test_boot_readiness_uses_credential_without_provider_probe(monkeypatch):
    from jarvis.core import llm
    from jarvis.ui.window_voice import WindowVoiceMixin

    monkeypatch.setattr(llm, "api_key", lambda: "saved-secret")
    monkeypatch.setattr(
        llm,
        "probe",
        lambda: (_ for _ in ()).throw(
            AssertionError("window construction must not probe provider")
        ),
    )

    window = object.__new__(WindowVoiceMixin)

    assert window._check_config() is True
