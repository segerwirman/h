"""Phase WA3 RED — bounded two-way audio proof linked to approved call session.

Inbound + outbound audio path teruji via injected capture/playback
functions (fixture-only; tanpa hardware di CI); start/stop call via
session WA2; bounded duration; metadata-only result.
"""
from __future__ import annotations

from jarvis.core.bus import BUS


def _fresh_proof(monkeypatch, *, now=1000.0):
    import jarvis.core.call_audio as ca

    state = {"now": now}
    monkeypatch.setattr(ca, "_now", lambda: state["now"])
    return ca, state


def _active_session(monkeypatch, *, now=1000.0):
    import jarvis.core.call_session as cs

    state = {"now": now}
    monkeypatch.setattr(cs, "_now", lambda: state["now"])
    session = cs.CallSession()
    session.start("+6281111", "Tanya harga", 60)
    session.approve()
    return session


def test_admit_duration_is_bounded_finite_int():
    from jarvis.core.call_audio import admit_duration

    assert admit_duration(1)["ok"] is True
    assert admit_duration(300)["ok"] is True
    assert admit_duration(600)["ok"] is True
    assert admit_duration(True)["ok"] is False
    assert admit_duration(5.0)["ok"] is False
    assert admit_duration(0)["ok"] is False
    assert admit_duration(-3)["ok"] is False
    assert admit_duration(601)["ok"] is False
    assert admit_duration("30")["ok"] is False


def test_start_requires_approved_active_session(monkeypatch):
    ca, _state = _fresh_proof(monkeypatch)
    import jarvis.core.call_session as cs

    idle = cs.CallSession()
    awaiting = cs.CallSession()
    awaiting.start("+6281111", "Tanya harga", 60)

    proof = ca.CallAudioProof()
    assert proof.start(idle, 30) is False                 # idle → tolak
    assert proof.start(awaiting, 30) is False             # belum approve → tolak
    assert proof.start(None, 30) is False                 # tanpa session → tolak
    assert proof.start(_active_session(monkeypatch), 601) is False  # durasi over

    active = _active_session(monkeypatch)
    assert proof.start(active, 30) is True                # hanya session active


def test_start_publishes_and_runs_bounded(monkeypatch):
    ca, state = _fresh_proof(monkeypatch, now=1000.0)
    events = []
    BUS.subscribe("call.audio.started", lambda d: events.append(d))

    capture = {"calls": 0}
    playback = {"calls": 0}

    def fake_capture(duration_s):
        capture["calls"] += 1
        return duration_s * 48000

    def fake_playback(duration_s):
        playback["calls"] += 1
        return True

    session = _active_session(monkeypatch)
    proof = ca.CallAudioProof(capture=fake_capture, playback=fake_playback)
    assert proof.start(session, 30) is True
    assert proof.status() == "running"
    assert len(events) == 1
    assert events[0]["session_id"] == session.session_id()
    assert capture["calls"] == 1 and playback["calls"] == 1


def test_finish_is_deadline_based(monkeypatch):
    ca, state = _fresh_proof(monkeypatch, now=1000.0)
    session = _active_session(monkeypatch)
    proof = ca.CallAudioProof()
    proof.start(session, 10)
    state["now"] = 1009.9
    assert proof.status() == "running"
    state["now"] = 1010.1
    assert proof.status() == "done"
    assert proof.result()["status"] == "done"


def test_stop_ends_early_and_publishes_once(monkeypatch):
    ca, state = _fresh_proof(monkeypatch, now=1000.0)
    events = []
    BUS.subscribe("call.audio.done", lambda d: events.append(d))
    session = _active_session(monkeypatch)
    proof = ca.CallAudioProof()
    proof.start(session, 60)
    state["now"] = 1005.0
    assert proof.stop() is True
    assert proof.status() == "done"
    assert proof.stop() is False                         # idempotent
    assert len(events) == 1


def test_session_cancel_stops_audio_proof(monkeypatch):
    ca, state = _fresh_proof(monkeypatch, now=1000.0)
    session = _active_session(monkeypatch)
    proof = ca.CallAudioProof()
    proof.start(session, 60)
    state["now"] = 1005.0
    session.cancel()                                     # sinyal stop via session
    assert proof.status() == "cancelled"


def test_session_done_stops_audio_proof(monkeypatch):
    ca, state = _fresh_proof(monkeypatch, now=1000.0)
    session = _active_session(monkeypatch)
    proof = ca.CallAudioProof()
    proof.start(session, 60)
    state["now"] = 1005.0
    session.end()                                        # sinyal stop via session
    assert proof.status() == "done"


def test_result_is_metadata_only_and_honest_without_audio_functions(monkeypatch):
    ca, _state = _fresh_proof(monkeypatch, now=1000.0)
    session = _active_session(monkeypatch)
    # Tanpa fungsi audio: proof jalan tapi jujur audio_exercised False
    proof = ca.CallAudioProof()
    assert proof.start(session, 30) is True
    result = proof.result()
    assert result["status"] == "running"
    assert result["audio_exercised"] is False
    assert result["session_id"] == session.session_id()
    # metadata-only: tidak ada data audio mentah/path/raw/payload
    for forbidden in ("path", "raw", "payload", "wav", "file"):
        assert forbidden not in result, forbidden
    assert all(isinstance(v, (bool, int, str)) for v in result.values())


def test_result_reports_samples_with_audio_functions(monkeypatch):
    ca, _state = _fresh_proof(monkeypatch, now=1000.0)
    session = _active_session(monkeypatch)

    def fake_capture(duration_s):
        return duration_s * 48000

    def fake_playback(duration_s):
        return True

    proof = ca.CallAudioProof(capture=fake_capture, playback=fake_playback)
    proof.start(session, 5)
    result = proof.result()
    assert result["audio_exercised"] is True
    assert result["samples_captured"] == 5 * 48000
    assert result["playback_ok"] is True
