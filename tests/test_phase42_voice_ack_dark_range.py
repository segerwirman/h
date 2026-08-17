"""Fase 42 — instrumentasi rentang gelap: akhir ucapan (voice) → dispatch/ACK.

Fase UKUR: menambah PENANDA, bukan memperbaiki performa. total_ms turn
``voice_ack`` di log ``latency.turn`` = rentang akhir-ucapan → task masuk
dispatch (ACK area). Angka pertama untuk rentang ini lahir pada sesi voice
nyata berikutnya; test di sini mengunci wiring pengukuran.
"""
from __future__ import annotations

import types

import pytest

from jarvis.core import latency


@pytest.fixture(autouse=True)
def _clean():
    latency.reset()
    yield
    latency.reset()


def test_voice_handoff_measures_dark_range_with_fake_clock():
    latency.start("voice_ack", task="voice:tes", now=100.0)
    latency.mark("voice_ack", "speech_end", now=100.0)
    report = latency.voice_handoff(now=100.05)  # delta 50 ms
    assert report["total_ms"] == 50.0
    stages = dict(report["stages"])
    assert "speech_end" in stages
    assert "dispatch_start" in stages


def test_voice_handoff_is_noop_without_voice_turn():
    assert latency.voice_handoff(now=1.0) == {}


def test_voice_handoff_after_second_voice_ack_start_is_bounded():
    latency.start("voice_ack", now=10.0)
    latency.mark("voice_ack", "speech_end", now=10.0)
    # ucapan kedua menimpa turn pertama (start idempotent overwrite)
    latency.start("voice_ack", now=20.0)
    latency.mark("voice_ack", "speech_end", now=20.0)
    report = latency.voice_handoff(now=20.05)  # delta 50 ms
    assert report["total_ms"] == 50.0
    assert len(report["stages"]) == 2  # satu pasang, bukan dua


def test_voice_intercept_opens_dark_range_turn(monkeypatch):
    from jarvis.ui import window_voice as wv

    calls: list[tuple] = []
    fake_latency = types.SimpleNamespace(
        start=lambda key, **kw: calls.append(("start", key)),
        mark=lambda key, stage, **kw: calls.append(("mark", key, stage)),
    )
    monkeypatch.setattr(wv, "latency", fake_latency)
    monkeypatch.setattr(
        wv, "classify_execution",
        lambda text, ctx: types.SimpleNamespace(
            tier=wv.ExecutionTier.AGENT, lane="heavy", reason="test"),
    )
    obj = object.__new__(wv.WindowVoiceMixin)
    obj.reply_flow = types.SimpleNamespace(handle_utterance=lambda s: False)
    obj._pending_close_decision = None
    obj._pending_voice_proposal_id = None
    obj._voice_intercept("tolong pesankan tiket pesawat ke jakarta")
    assert ("start", "voice_ack") in calls
    assert ("mark", "voice_ack", "speech_end") in calls
