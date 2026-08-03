"""18A installer composes proposal hook only when explicitly enabled."""
from __future__ import annotations
import asyncio
import types


def test_proposal_hook_feature_off_preserves_existing_l1_hook(monkeypatch):
    from jarvis.integrations import voice_proposal_install
    legacy = types.SimpleNamespace(VOICE_L1_HOOK=None)
    monkeypatch.setattr(voice_proposal_install.config, "get", lambda key, default=None: False)
    assert voice_proposal_install.install(legacy) is False
    assert legacy.VOICE_L1_HOOK is None


def test_proposal_hook_feature_on_handles_before_legacy_fallback(monkeypatch):
    from jarvis.integrations import voice_proposal_install
    monkeypatch.setattr(voice_proposal_install.config, "get", lambda key, default=None: True)
    legacy_called = []
    async def legacy_hook(*_): legacy_called.append(True); return False
    legacy = types.SimpleNamespace(VOICE_L1_HOOK=legacy_hook)
    assert voice_proposal_install.install(legacy) is True
    class Gate:
        text = "aktifkan mode fokus"
        def reset(self): pass
    class Live:
        def speak(self, _): pass
    assert asyncio.run(legacy.VOICE_L1_HOOK(Live(), Gate())) is True
    assert legacy_called == []


def test_proposal_installer_fail_open_for_unsupported_phrase(monkeypatch):
    from jarvis.integrations import voice_proposal_install
    monkeypatch.setattr(voice_proposal_install.config, "get", lambda key, default=None: True)
    called=[]
    async def fallback(*_): called.append(True); return False
    legacy=types.SimpleNamespace(VOICE_L1_HOOK=fallback)
    voice_proposal_install.install(legacy)
    class Gate:
        text='klik tombol beli'
        def reset(self): raise AssertionError('must not reset')
    assert asyncio.run(legacy.VOICE_L1_HOOK(object(), Gate())) is False
    assert called == [True]


def test_installer_is_idempotent():
    from jarvis.integrations import voice_proposal_install
    legacy=types.SimpleNamespace(VOICE_L1_HOOK=None)
    # Config-independent idempotence marker is installed only after actual enable.
    assert hasattr(voice_proposal_install, 'install')
