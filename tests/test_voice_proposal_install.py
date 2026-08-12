"""18A proposal composition folded into the existing voice L1 seam."""
from __future__ import annotations

import asyncio
import types


def test_proposal_hook_feature_off_preserves_existing_l1_hook(monkeypatch):
    from jarvis.integrations import voice_proposal_install

    async def fallback(*_):
        return False

    monkeypatch.setattr(
        voice_proposal_install.config,
        "get",
        lambda _key, default=None: False,
    )
    assert voice_proposal_install.compose(fallback) is fallback


def test_proposal_hook_feature_on_handles_before_legacy_fallback(monkeypatch):
    from jarvis.integrations import voice_proposal_install

    monkeypatch.setattr(
        voice_proposal_install.config,
        "get",
        lambda _key, default=None: True,
    )
    legacy_called = []

    async def legacy_hook(*_):
        legacy_called.append(True)
        return False

    hook = voice_proposal_install.compose(legacy_hook)

    class Gate:
        text = "aktifkan mode fokus"

        def reset(self):
            pass

    class Live:
        def speak(self, _):
            pass

    assert asyncio.run(hook(Live(), Gate())) is True
    assert legacy_called == []


def test_proposal_installer_fail_open_for_unsupported_phrase(monkeypatch):
    from jarvis.integrations import voice_proposal_install

    monkeypatch.setattr(
        voice_proposal_install.config,
        "get",
        lambda _key, default=None: True,
    )
    called = []

    async def fallback(*_):
        called.append(True)
        return False

    hook = voice_proposal_install.compose(fallback)

    class Gate:
        text = "klik tombol beli"

        def reset(self):
            raise AssertionError("must not reset")

    assert asyncio.run(hook(object(), Gate())) is False
    assert called == [True]


def test_composition_is_idempotent(monkeypatch):
    from jarvis.integrations import voice_proposal_install

    monkeypatch.setattr(
        voice_proposal_install.config,
        "get",
        lambda _key, default=None: True,
    )
    hook = voice_proposal_install.compose(None)
    assert voice_proposal_install.compose(hook) is hook
    assert not hasattr(voice_proposal_install, "install")


def test_voice_l1_install_keeps_proposal_when_l1_is_off(monkeypatch):
    from jarvis.integrations import voice_l1

    monkeypatch.setattr(
        voice_l1.config,
        "get",
        lambda path, default=None: {
            "routing.voice_l1_hook.enabled": False,
            "routing.voice_desktop_proposals.enabled": True,
        }.get(path, default),
    )
    legacy = types.SimpleNamespace(VOICE_L1_HOOK=None)

    assert voice_l1.install(legacy) is True
    assert getattr(legacy.VOICE_L1_HOOK, "_jarvis_voice_proposal_hook", False)
    first = legacy.VOICE_L1_HOOK
    assert voice_l1.install(legacy) is True
    assert legacy.VOICE_L1_HOOK is first


def test_voice_l1_install_is_noop_when_both_flags_are_off(monkeypatch):
    from jarvis.integrations import voice_l1

    async def fallback(*_):
        return False

    monkeypatch.setattr(voice_l1.config, "get", lambda _path, default=None: False)
    legacy = types.SimpleNamespace(VOICE_L1_HOOK=fallback)

    assert voice_l1.install(legacy) is False
    assert legacy.VOICE_L1_HOOK is fallback
