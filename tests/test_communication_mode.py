"""Task 7 — communication-mode owner and fake WhatsApp bridge lifecycle."""
from __future__ import annotations

import asyncio
import queue
import sys
import weakref

import pytest


class _GrantManager:
    def __init__(self) -> None:
        self.revocations: list[tuple[int, str]] = []

    def revoke_generation(self, generation, *, purpose=None):
        self.revocations.append((generation, purpose))
        return 1


class _Loop:
    def is_running(self):
        return True


class _Live:
    def __init__(self):
        self._loop = _Loop()
        self.out_queue = queue.Queue()
        self._phone_active = False


class _Stream:
    def __init__(self, *, fail_start=False, fail_write=False):
        self.fail_start = fail_start
        self.fail_write = fail_write
        self.started = 0
        self.stopped = 0
        self.closed = 0

    def start(self):
        self.started += 1
        if self.fail_start:
            raise RuntimeError("stream start failed")

    def stop(self):
        self.stopped += 1

    def close(self):
        self.closed += 1

    def write(self, _chunk):
        if self.fail_write:
            raise RuntimeError("output vanished")


class _SoundDevice:
    def __init__(self, input_stream, output_stream):
        self.input_stream = input_stream
        self.output_stream = output_stream

    def RawInputStream(self, **_kwargs):
        return self.input_stream

    def RawOutputStream(self, **_kwargs):
        return self.output_stream


@pytest.fixture(autouse=True)
def _reset_singletons():
    from jarvis.agent import communication_mode
    from jarvis.agent.execution_grants import MANAGER
    from jarvis.integrations import whatsapp_voice

    previous_mode = communication_mode.MODE
    previous_bridge = whatsapp_voice.WhatsAppAudioBridge._instance
    previous_ref = whatsapp_voice._live_ref
    communication_mode.MODE = communication_mode.CommunicationMode()
    whatsapp_voice.WhatsAppAudioBridge._instance = None
    whatsapp_voice._live_ref = None
    MANAGER.clear()
    yield
    current = whatsapp_voice.WhatsAppAudioBridge._instance
    if current is not None:
        current.stop()
    communication_mode.MODE.exit()
    MANAGER.clear()
    communication_mode.MODE = previous_mode
    whatsapp_voice.WhatsAppAudioBridge._instance = previous_bridge
    whatsapp_voice._live_ref = previous_ref


def _configure_bridge(monkeypatch, *, output_stream=None, input_stream=None):
    from jarvis.integrations import whatsapp_voice

    live = _Live()
    whatsapp_voice._live_ref = weakref.ref(live)
    input_stream = input_stream or _Stream()
    output_stream = output_stream or _Stream()
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        _SoundDevice(input_stream, output_stream),
    )
    values = {
        "whatsapp_web.audio_bridge.enabled": True,
        "whatsapp_web.audio_bridge.remote_input_device": "virtual-in",
        "whatsapp_web.audio_bridge.remote_output_device": "virtual-out",
    }
    monkeypatch.setattr(
        whatsapp_voice.config,
        "get",
        lambda key, default=None: values.get(key, default),
    )
    return whatsapp_voice.WhatsAppAudioBridge(), live, input_stream, output_stream


def test_owner_generation_and_escape_set_are_explicit_ids_only():
    from jarvis.agent.communication_mode import (
        CommunicationMode,
        ESCAPE_CAPABILITY_IDS,
    )
    from jarvis.agent.execution_grants import PURPOSE_COMMUNICATION_OVERRIDE

    grants = _GrantManager()
    mode = CommunicationMode(grant_manager=grants)

    assert mode.active() is False
    assert mode.generation() == 0
    assert mode.enter() == 1
    assert mode.enter() == 1
    assert mode.active() is True
    assert mode.exit() is True
    assert mode.active() is False
    assert grants.revocations == [(1, PURPOSE_COMMUNICATION_OVERRIDE)]
    assert mode.enter() == 2

    assert ESCAPE_CAPABILITY_IDS == {
        "whatsapp_status",
        "whatsapp_hangup",
        "task_cancel",
        "emergency_stop",
        "communication_auth",
    }
    assert all(" " not in item for item in ESCAPE_CAPABILITY_IDS)
    assert mode.is_escape("please whatsapp_hangup now") is False
    assert mode.is_escape("whatsapp_hangup") is True


def test_override_issue_binds_active_generation_and_rejects_inactive_mode():
    from jarvis.agent.communication_mode import CommunicationMode
    from jarvis.agent.execution_grants import (
        ExecutionGrantManager,
        PURPOSE_COMMUNICATION_OVERRIDE,
    )

    grants = ExecutionGrantManager()
    mode = CommunicationMode(grant_manager=grants)
    with pytest.raises(RuntimeError, match="not active"):
        mode.issue_override(
            task_id="T-real",
            trace_id="trace-123",
            capability_ids={"web.web_search"},
            ttl_s=30,
        )

    generation = mode.enter()
    grant = mode.issue_override(
        task_id="T-real",
        trace_id="trace-123",
        capability_ids={"web.web_search"},
        ttl_s=30,
        uses=2,
    )

    assert grant.purpose == PURPOSE_COMMUNICATION_OVERRIDE
    assert grant.task_id == "T-real"
    assert grant.trace_id == "trace-123"
    assert grant.capability_ids == {"web.web_search"}
    assert grant.generation == generation
    assert grant.uses_left == 2


def test_override_issue_revokes_if_generation_changes_during_issue():
    from jarvis.agent.communication_mode import CommunicationMode
    from jarvis.agent.execution_grants import ExecutionGrantManager

    class ChangingGrants(ExecutionGrantManager):
        def issue(self, **kwargs):
            grant = super().issue(**kwargs)
            mode.exit()
            return grant

    grants = ChangingGrants()
    mode = CommunicationMode(grant_manager=grants)
    mode.enter()

    with pytest.raises(RuntimeError, match="generation changed"):
        mode.issue_override(
            task_id="T-real",
            trace_id="trace-123",
            capability_ids={"web.web_search"},
            ttl_s=30,
        )

    assert len(grants) == 0


def test_successful_bridge_start_enters_lock_only_after_active(monkeypatch):
    from jarvis.agent import communication_mode

    bridge, live, input_stream, output_stream = _configure_bridge(monkeypatch)
    observations = []
    real_enter = communication_mode.MODE.enter

    def enter():
        observations.append((bridge.active, input_stream.started,
                             output_stream.started))
        return real_enter()

    monkeypatch.setattr(communication_mode.MODE, "enter", enter)
    result = bridge.start()

    assert result["active"] is True
    assert communication_mode.MODE.active() is True
    assert communication_mode.MODE.generation() == 1
    assert observations == [(True, 1, 1)]
    assert live._phone_active is True


def test_failed_bridge_start_never_engages_lock(monkeypatch):
    from jarvis.agent import communication_mode

    bridge, live, input_stream, _ = _configure_bridge(
        monkeypatch, output_stream=_Stream(fail_start=True),
    )
    result = bridge.start()

    assert result["active"] is False
    assert communication_mode.MODE.active() is False
    assert communication_mode.MODE.generation() == 0
    assert live._phone_active is False
    assert input_stream.closed == 1


def test_stop_and_output_failure_exit_lock_and_revoke_generation(monkeypatch):
    from jarvis.agent import communication_mode
    from jarvis.agent.execution_grants import (
        MANAGER,
        PURPOSE_COMMUNICATION_OVERRIDE,
    )

    bridge, _live, _input, _output = _configure_bridge(monkeypatch)
    assert bridge.start()["active"] is True
    generation = communication_mode.MODE.generation()
    grant = MANAGER.issue(
        purpose=PURPOSE_COMMUNICATION_OVERRIDE,
        task_id="T-call",
        trace_id="trace-call",
        capability_ids={"web.web_search"},
        ttl_s=30,
        generation=generation,
    )

    assert bridge.stop()["active"] is False
    assert communication_mode.MODE.active() is False
    assert MANAGER.get(grant.id) is None

    bridge, _live, _input, output = _configure_bridge(
        monkeypatch, output_stream=_Stream(fail_write=True),
    )
    assert bridge.start()["active"] is True
    grant = MANAGER.issue(
        purpose=PURPOSE_COMMUNICATION_OVERRIDE,
        task_id="T-output",
        trace_id="trace-output",
        capability_ids={"web.web_search"},
        ttl_s=30,
        generation=communication_mode.MODE.generation(),
    )
    bridge._output_queue.put_nowait(b"audio")
    bridge._output_worker()

    assert output.closed == 1
    assert communication_mode.MODE.active() is False
    assert MANAGER.get(grant.id) is None


def test_stop_exception_still_exits_lock(monkeypatch):
    from jarvis.agent import communication_mode
    from jarvis.integrations import whatsapp_voice

    bridge = whatsapp_voice.WhatsAppAudioBridge()
    bridge._active = True
    bridge._output_thread = type("Thread", (), {
        "join": lambda self, timeout=None: (_ for _ in ()).throw(
            RuntimeError("join failed")),
    })()
    communication_mode.MODE.enter()

    with pytest.raises(RuntimeError, match="join failed"):
        bridge.stop()

    assert communication_mode.MODE.active() is False


def test_hangup_exits_lock_even_when_web_and_bridge_stop_raise(monkeypatch):
    from jarvis.agent import communication_mode
    from jarvis.agent.tools import whatsapp_web as tool_mod
    from jarvis.integrations import whatsapp_voice, whatsapp_web

    class Service:
        def hangup(self):
            raise RuntimeError("web hangup failed")

    communication_mode.MODE.enter()
    monkeypatch.setattr(
        whatsapp_web.WhatsAppWebService,
        "get",
        classmethod(lambda cls: Service()),
    )
    monkeypatch.setattr(
        whatsapp_voice,
        "stop_bridge",
        lambda: (_ for _ in ()).throw(RuntimeError("bridge stop failed")),
    )

    result = asyncio.run(tool_mod.WhatsAppHangup().run())

    assert result.ok is False
    assert communication_mode.MODE.active() is False


def test_shutdown_without_bridge_instance_retires_orphaned_mode(monkeypatch):
    from jarvis.agent import communication_mode
    from jarvis.integrations import voice_safety, whatsapp_voice

    communication_mode.MODE.enter()
    whatsapp_voice.WhatsAppAudioBridge._instance = None
    voice_safety._stop_communication_mode()

    assert communication_mode.MODE.active() is False
