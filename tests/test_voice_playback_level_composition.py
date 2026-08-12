"""Characterization for the playback-level helper composition boundary."""
from __future__ import annotations

import asyncio
import types

import pytest

from jarvis.integrations import voice_playback_level


@pytest.fixture(autouse=True)
def _reset_level_state():
    voice_playback_level.reset()
    voice_playback_level.mark_uninstalled()
    yield
    voice_playback_level.reset()
    voice_playback_level.mark_uninstalled()


class _FakeLive:
    def __init__(self):
        self.audio_in_queue = asyncio.Queue()
        self.seen = []

    async def play(self):
        self.seen.append(self.audio_in_queue)
        return await self.audio_in_queue.get()


def _chunk():
    return (b"\x80\x00" * 1600)


def test_compose_measures_consumed_audio_and_restores_queue():
    original = _FakeLive.play
    wrapped = voice_playback_level.compose(original)
    live = _FakeLive()
    original_queue = live.audio_in_queue
    voice_playback_level.reset()
    voice_playback_level._installed = True

    async def run():
        await live.audio_in_queue.put(_chunk())
        result = await wrapped(live)
        return result

    assert asyncio.run(run()) == _chunk()
    assert live.seen and live.seen[0] is not original_queue
    assert live.audio_in_queue is original_queue
    assert voice_playback_level.current_level() == 0.0


def test_compose_resets_level_after_playback_finishes():
    async def original(self):
        await self.audio_in_queue.get()

    voice_playback_level.reset()
    wrapped = voice_playback_level.compose(original)

    live = _FakeLive()

    async def run():
        await live.audio_in_queue.put(_chunk())
        await wrapped(live)

    asyncio.run(run())
    assert voice_playback_level.current_level() == 0.0


def test_compose_is_idempotent_and_rejects_non_callable():
    original = _FakeLive.play
    wrapped = voice_playback_level.compose(original)
    assert voice_playback_level.compose(wrapped) is wrapped
    with pytest.raises(TypeError):
        voice_playback_level.compose(None)


def test_compose_restores_queue_when_original_fails():
    async def original(self):
        await self.audio_in_queue.get()
        raise RuntimeError("playback failed")

    wrapped = voice_playback_level.compose(original)
    live = _FakeLive()
    original_queue = live.audio_in_queue

    async def run():
        await live.audio_in_queue.put(_chunk())
        await wrapped(live)

    with pytest.raises(RuntimeError, match="playback failed"):
        asyncio.run(run())
    assert live.audio_in_queue is original_queue
    assert voice_playback_level.current_level() == 0.0


def test_compose_does_not_mark_installation_without_owner():
    voice_playback_level.reset()
    voice_playback_level._installed = False
    assert voice_playback_level.is_installed() is False
    voice_playback_level._installed = True
    assert voice_playback_level.is_installed() is True
    voice_playback_level._installed = False


def test_fake_legacy_owner_composes_level_before_install():
    from jarvis.integrations import voice_playback_fix

    class _SD:
        def RawOutputStream(self, **_kwargs):
            raise AssertionError("not reached in composition characterization")

    legacy = types.SimpleNamespace(JarvisLive=_FakeLive, sd=_SD())
    assert voice_playback_fix.install(legacy) is True
    assert voice_playback_level.is_installed() is True
    assert getattr(legacy.JarvisLive._play_audio,
                   "_jarvis_playback_level", False) is True


__all__ = []
