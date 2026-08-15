"""RED-first contracts for playback-aware Live speech arbitration."""
from __future__ import annotations

import asyncio
import threading
import types

from jarvis.core.speech_queue import SpeechQueue
from jarvis.integrations import voice_playback_fix, voice_speech


class _FakeStream:
    def __init__(self):
        self.writes: list[bytes] = []

    def start(self):
        return None

    def write(self, chunk):
        self.writes.append(bytes(chunk))

    def stop(self):
        return None

    def close(self):
        return None


class _FailingStream(_FakeStream):
    def __init__(
        self,
        *,
        fail_start: bool = False,
        fail_write: bool = False,
        fail_write_at: int = 0,
    ):
        super().__init__()
        self.fail_start = fail_start
        self.fail_write = fail_write
        self.fail_write_at = fail_write_at
        self.write_count = 0

    def start(self):
        if self.fail_start:
            raise RuntimeError("stream start failed")

    def write(self, chunk):
        self.write_count += 1
        if self.fail_write or self.write_count == self.fail_write_at:
            raise RuntimeError("stream write failed")
        super().write(chunk)


class _FakeSD:
    def __init__(self):
        self.stream = _FakeStream()

    def RawOutputStream(self, **_kwargs):
        return self.stream


class _Session:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.sent: list[tuple[dict, bool]] = []

    async def send_client_content(self, *, turns=None, turn_complete=True):
        if self.fail:
            raise RuntimeError("send failed")
        self.sent.append((turns, turn_complete))


class _Live:
    def __init__(self, *, loop, session=None):
        self._loop = loop
        self.session = session or _Session()
        self.audio_in_queue = asyncio.Queue()
        self._turn_done_event = asyncio.Event()
        self._speaking_lock = threading.Lock()
        self._is_speaking = False
        self.speaking: list[bool] = []

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = bool(value)
        self.speaking.append(bool(value))

    def interrupt(self):
        self._interrupted = True
        self.set_speaking(False)
        self._turn_done_event.clear()

    async def _play_audio(self):
        raise AssertionError("playback fix not installed")


class _Window:
    def __init__(self):
        self.on_text_command = None

    def _speak_now(self, line: str):
        callback = getattr(self, "on_speech_command", None)
        if callable(callback):
            return callback(line)
        if self.on_text_command is None:
            return None
        self.on_text_command(line)
        return None


def _legacy(live_cls):
    return types.SimpleNamespace(
        JarvisLive=live_cls,
        sd=_FakeSD(),
        RECEIVE_SAMPLE_RATE=24000,
        CHANNELS=1,
        CHUNK_SIZE=8,
    )


def test_queue_waits_for_ticket_before_submitting_next_item():
    submitted: list[str] = []
    first = voice_speech.PlaybackTicket()

    def speaker(text):
        submitted.append(text)
        return first if text == "first" else None

    queue = SpeechQueue(speaker=speaker)
    queue.say("first", kind="final", turn="T-1")
    queue.say("second", kind="final", turn="T-2")

    assert queue.run_once() is True
    assert queue.run_once() is False
    assert submitted == ["first"]

    first.complete()

    assert queue.run_once() is True
    assert submitted == ["first", "second"]


def test_legacy_none_speaker_retains_immediate_completion():
    submitted: list[str] = []
    queue = SpeechQueue(speaker=lambda text: submitted.append(text))
    queue.say("first", kind="final")
    queue.say("second", kind="final")

    assert queue.drain() == 2
    assert submitted == ["first", "second"]


def test_live_submission_ticket_completes_only_after_playback_drain(monkeypatch):
    monkeypatch.setattr(
        voice_playback_fix.config,
        "get",
        lambda key, default=None: {
            "voice.playback.tail_grace_s": 0.0,
            "voice.playback.poll_s": 0.001,
        }.get(key, default),
    )

    async def scenario():
        loop = asyncio.get_running_loop()

        class Live(_Live):
            pass

        legacy = _legacy(Live)
        assert voice_playback_fix.install(legacy) is True
        assert voice_speech.install(legacy) is True
        live = Live(loop=loop)
        window = _Window()
        voice_speech.bind(window, live)

        ticket = window._speak_now("explain this")
        assert isinstance(ticket, voice_speech.PlaybackTicket)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(live.session.sent) == 1
        assert ticket.done is False

        await live.audio_in_queue.put(b"AB" * 4)
        live._turn_done_event.set()
        player = asyncio.create_task(live._play_audio())
        try:
            await asyncio.wait_for(ticket.wait_async(), timeout=1)
        finally:
            player.cancel()
            try:
                await player
            except asyncio.CancelledError:
                pass

        assert ticket.completed is True
        assert live.speaking[-1] is False

    asyncio.run(scenario())


def test_send_failure_requeues_item_and_retries_after_recovery():
    async def scenario():
        loop = asyncio.get_running_loop()

        class Live(_Live):
            pass

        legacy = _legacy(Live)
        assert voice_speech.install(legacy) is True
        live = Live(loop=loop, session=_Session(fail=True))
        window = _Window()
        voice_speech.bind(window, live)
        queue = SpeechQueue(speaker=window._speak_now)
        queue.say("first", kind="final", turn="T-1")
        queue.say("second", kind="final", turn="T-2")

        assert queue.run_once() is True
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert live._voice_speech_ticket is None

        live.session.fail = False
        assert queue.run_once() is True
        assert queue.pending() == 1
        assert queue.busy() is True
        await asyncio.sleep(0)
        retry_ticket = live._voice_speech_ticket
        assert isinstance(retry_ticket, voice_speech.PlaybackTicket)
        voice_speech.mark_audio(live)
        assert voice_speech.playback_drained(live) is True

        assert queue.run_once() is True
        assert queue.pending() == 0
        await asyncio.sleep(0)
        assert len(live.session.sent) == 2
        voice_speech.abort(live)

    asyncio.run(scenario())


def test_interrupt_aborts_inflight_ticket_without_audible_completion():
    async def scenario():
        loop = asyncio.get_running_loop()

        class Live(_Live):
            pass

        legacy = _legacy(Live)
        assert voice_speech.install(legacy) is True
        live = Live(loop=loop)
        window = _Window()
        voice_speech.bind(window, live)

        ticket = window._speak_now("long explanation")
        await asyncio.sleep(0)
        live.interrupt()

        assert ticket.done is True
        assert ticket.aborted is True
        assert ticket.completed is False

    asyncio.run(scenario())


def test_busy_live_lane_defers_first_queue_submission():
    async def scenario():
        loop = asyncio.get_running_loop()

        class Live(_Live):
            pass

        legacy = _legacy(Live)
        assert voice_speech.install(legacy) is True
        live = Live(loop=loop)
        live._is_speaking = True
        window = _Window()
        voice_speech.bind(window, live)
        queue = SpeechQueue(speaker=window._speak_now)
        queue.say("background progress", kind="progress", turn="T-1")

        assert queue.run_once() is False
        assert live.session.sent == []

        live._is_speaking = False
        live._turn_done_event.set()
        assert queue.run_once() is True
        await asyncio.sleep(0)
        assert len(live.session.sent) == 1

    asyncio.run(scenario())


def test_playback_stream_constructor_failure_aborts_ticket(monkeypatch):
    monkeypatch.setattr(
        voice_playback_fix.config,
        "get",
        lambda key, default=None: {
            "voice.playback.tail_grace_s": 0.0,
            "voice.playback.poll_s": 0.001,
        }.get(key, default),
    )

    async def scenario():
        loop = asyncio.get_running_loop()

        class Live(_Live):
            pass

        class ConstructorFailSD:
            def RawOutputStream(self, **_kwargs):
                raise RuntimeError("stream constructor failed")

        legacy = _legacy(Live)
        legacy.sd = ConstructorFailSD()
        assert voice_playback_fix.install(legacy) is True
        live = Live(loop=loop)
        ticket = voice_speech.submit(live, "test constructor failure")
        await asyncio.sleep(0)

        try:
            await live._play_audio()
        except RuntimeError:
            pass

        assert ticket.aborted is True
        assert ticket.completed is False

    asyncio.run(scenario())


def test_playback_stream_start_failure_aborts_ticket(monkeypatch):
    monkeypatch.setattr(
        voice_playback_fix.config,
        "get",
        lambda key, default=None: {
            "voice.playback.tail_grace_s": 0.0,
            "voice.playback.poll_s": 0.001,
        }.get(key, default),
    )

    async def scenario():
        loop = asyncio.get_running_loop()

        class Live(_Live):
            pass

        legacy = _legacy(Live)
        legacy.sd.stream = _FailingStream(fail_start=True)
        assert voice_playback_fix.install(legacy) is True
        live = Live(loop=loop)
        ticket = voice_speech.submit(live, "test start failure")
        await asyncio.sleep(0)

        try:
            await live._play_audio()
        except RuntimeError:
            pass

        assert ticket.aborted is True

    asyncio.run(scenario())


def test_playback_write_failure_aborts_instead_of_completing(monkeypatch):
    monkeypatch.setattr(
        voice_playback_fix.config,
        "get",
        lambda key, default=None: {
            "voice.playback.tail_grace_s": 0.0,
            "voice.playback.poll_s": 0.001,
        }.get(key, default),
    )

    async def scenario():
        loop = asyncio.get_running_loop()

        class Live(_Live):
            pass

        legacy = _legacy(Live)
        legacy.sd.stream = _FailingStream(fail_write=True)
        assert voice_playback_fix.install(legacy) is True
        live = Live(loop=loop)
        ticket = voice_speech.submit(live, "test write failure")
        await asyncio.sleep(0)
        await live.audio_in_queue.put(b"AB" * 4)

        player = asyncio.create_task(live._play_audio())
        try:
            await asyncio.wait_for(ticket.wait_async(), timeout=1)
        finally:
            player.cancel()
            try:
                await player
            except (asyncio.CancelledError, RuntimeError):
                # The playback owner raises the stream error after aborting the
                # ticket; the frozen loop treats it as a failed playback turn.
                pass

        assert ticket.aborted is True
        assert ticket.completed is False

    asyncio.run(scenario())


def test_playback_tail_write_failure_aborts_instead_of_completing(monkeypatch):
    monkeypatch.setattr(
        voice_playback_fix.config,
        "get",
        lambda key, default=None: {
            "voice.playback.tail_grace_s": 0.0,
            "voice.playback.poll_s": 0.001,
        }.get(key, default),
    )

    async def scenario():
        loop = asyncio.get_running_loop()

        class Live(_Live):
            pass

        legacy = _legacy(Live)
        legacy.sd.stream = _FailingStream(fail_write_at=2)
        assert voice_playback_fix.install(legacy) is True
        live = Live(loop=loop)
        ticket = voice_speech.submit(live, "test tail failure")
        await asyncio.sleep(0)
        await live.audio_in_queue.put(b"AB" * 4)
        live._turn_done_event.set()

        try:
            await asyncio.wait_for(live._play_audio(), timeout=1)
        except RuntimeError:
            pass

        assert ticket.aborted is True
        assert ticket.completed is False

    asyncio.run(scenario())


def test_notice_lane_cannot_bypass_submitting_window_queue():
    from jarvis.integrations import voice_speech

    queue = SpeechQueue(speaker=lambda _text: None)
    live = types.SimpleNamespace(
        session=object(),
        audio_in_queue=asyncio.Queue(),
        _is_speaking=False,
        _awaiting_since=None,
        _interrupted=False,
        _turn_done_event=asyncio.Event(),
        ui=types.SimpleNamespace(_win=types.SimpleNamespace(
            _speech_queue=queue)),
    )
    live._turn_done_event.set()
    queue._inflight_item = types.SimpleNamespace()

    assert voice_speech.notice_lane_idle(live) is False


def test_confirmation_waits_for_current_audible_turn_then_runs_first():
    submitted: list[str] = []
    current = voice_speech.PlaybackTicket()

    def speaker(text):
        submitted.append(text)
        return current if len(submitted) == 1 else None

    queue = SpeechQueue(speaker=speaker)
    queue.say("current explanation", kind="final", turn="conversation")
    assert queue.run_once() is True
    queue.say("background progress", kind="progress", turn="T-progress")
    queue.say("Lanjutkan aksi ini?", kind="confirm", turn="T-confirm")

    assert queue.run_once() is False
    assert submitted == ["current explanation"]

    current.complete()
    assert queue.run_once() is True
    assert submitted == ["current explanation", "Lanjutkan aksi ini?"]


def test_direct_submit_cannot_replace_an_active_ticket():
    async def scenario():
        loop = asyncio.get_running_loop()
        live = _Live(loop=loop)

        first = voice_speech.submit(live, "first")
        second = voice_speech.submit(live, "second")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert live._voice_speech_ticket is first
        assert first.done is False
        assert second.aborted is True
        assert len(live.session.sent) == 1

        voice_speech.abort(live)

    asyncio.run(scenario())


def test_submit_exact_preserves_generic_notice_turn_complete_flag():
    async def scenario():
        loop = asyncio.get_running_loop()
        live = _Live(loop=loop)

        ticket = voice_speech.submit_exact(
            live,
            "visual context only",
            exact=False,
            turn_complete=False,
        )
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert live.session.sent == [
            ({"parts": [{"text": "visual context only"}]}, False)
        ]
        voice_speech.abort(live)
        assert ticket.aborted is True

    asyncio.run(scenario())


def test_drained_boundary_is_claimed_once_until_new_turn():
    async def scenario():
        loop = asyncio.get_running_loop()
        live = _Live(loop=loop)
        live._turn_done_event.set()
        voice_speech.mark_turn_complete(live)
        assert voice_speech.claim_turn_boundary(live) is True
        assert voice_speech.claim_turn_boundary(live) is False
        voice_speech.release_turn_boundary(live)
        assert voice_speech.claim_turn_boundary(live) is True

        live._turn_done_event.clear()
        voice_speech.mark_turn_complete(live)
        assert voice_speech.claim_turn_boundary(live) is False

    asyncio.run(scenario())


def test_context_only_submission_completes_on_send_ack_without_audio():

    async def scenario():
        loop = asyncio.get_running_loop()
        live = _Live(loop=loop)

        ticket = voice_speech.submit_exact(
            live,
            "visual context only",
            exact=False,
            turn_complete=False,
            require_playback=False,
        )
        assert await asyncio.wait_for(ticket.wait_async(), timeout=1) == "completed"
        assert live.session.sent == [
            ({"parts": [{"text": "visual context only"}]}, False)
        ]
        assert voice_speech.lane_idle(live) is True

    asyncio.run(scenario())


def test_send_timeout_aborts_ticket_and_releases_lane(monkeypatch):
    class HangingSession:
        def __init__(self):
            self.started = asyncio.Event()

        async def send_client_content(self, **_kwargs):
            self.started.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(voice_speech, "_SEND_TIMEOUT_S", 0.01)

    async def scenario():
        loop = asyncio.get_running_loop()
        live = _Live(loop=loop, session=HangingSession())

        ticket = voice_speech.submit(live, "will hang")
        await live.session.started.wait()
        assert await asyncio.wait_for(ticket.wait_async(), timeout=1) == "aborted"
        assert voice_speech.lane_idle(live) is True

    asyncio.run(scenario())


def test_stale_drain_cannot_complete_the_next_ticket():
    async def scenario():
        loop = asyncio.get_running_loop()
        live = _Live(loop=loop)

        first = voice_speech.submit(live, "first")
        await asyncio.sleep(0)
        voice_speech.mark_audio(live)
        first_epoch = voice_speech.current_playback_epoch(live)
        assert voice_speech.abort(live) is True
        assert first.aborted is True

        second = voice_speech.submit(live, "second")
        await asyncio.sleep(0)
        second_epoch = voice_speech.current_playback_epoch(live)
        assert second_epoch != first_epoch
        voice_speech.mark_audio(live, epoch=first_epoch)
        assert voice_speech.playback_drained(live, epoch=first_epoch) is False
        assert second.done is False
        voice_speech.abort(live)

    asyncio.run(scenario())


def test_interrupt_failure_still_aborts_active_ticket():
    async def scenario():
        loop = asyncio.get_running_loop()

        class Live(_Live):
            def interrupt(self):
                raise RuntimeError("legacy interrupt failed")

        legacy = _legacy(Live)
        assert voice_speech.install(legacy) is True
        live = Live(loop=loop)
        ticket = voice_speech.submit(live, "pending during interrupt")
        await asyncio.sleep(0)

        try:
            live.interrupt()
        except RuntimeError:
            pass

        assert ticket.aborted is True

    asyncio.run(scenario())
