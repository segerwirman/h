"""WA9-live RED — call live controls (kill switch, hangup, rings).

Kill switch one-shot (membatalkan session + audio proof + bus
call.killed), visible hangup (metadata-only), rollout rings bertingkat
(test → trusted → business → public; ring berikutnya butuh bukti accept
dari ring sebelumnya). Murni lokal; tanpa SDK/network/file.
"""
from __future__ import annotations


def _controls():
    import jarvis.live.call_live_controls as clc

    return clc, clc.CallKillSwitch()


class _FakeProof:
    def __init__(self):
        self._state = "running"
        self.stopped = 0

    def stop(self) -> bool:
        if self._state != "running":
            return False
        self._state = "done"
        self.stopped += 1
        return True

    def status(self) -> str:
        return self._state


def _session():
    from jarvis.core.call_session import CallSession

    session = CallSession()
    session.start("Toko", "cek", 300)
    session.approve()
    return session


def test_kill_switch_one_shot_and_bus_event():
    clc, switch = _controls()
    session = _session()
    proof = _FakeProof()
    assert switch.arm(session, proof) is True
    assert switch.status() == "armed"
    assert switch.kill() is True
    assert switch.status() == "killed"
    assert session.status() == "cancelled"      # session dibatalkan
    assert proof.status() == "done"             # proof dihentikan
    assert switch.kill() is False               # one-shot
    assert switch.arm(session, proof) is False  # tidak bisa re-arm


def test_kill_without_arm_rejected():
    clc, switch = _controls()
    assert switch.kill() is False
    assert switch.status() == "idle"


def test_visible_hangup_ends_session_with_metadata():
    import jarvis.live.call_live_controls as clc

    session = _session()
    proof = _FakeProof()
    result = clc.visible_hangup(session, proof)
    assert result["ok"] is True
    assert result["hangup_visible"] is True
    assert session.status() == "done"
    assert proof.status() == "done"
    # One-shot: hangup kedua ditolak
    second = clc.visible_hangup(session, proof)
    assert second["ok"] is False


def test_rollout_rings_are_staged_and_require_proof():
    import jarvis.live.call_live_controls as clc

    rings = clc.RolloutRings()
    assert rings.RING_ORDER == ("test", "trusted", "business", "public")
    # Ring pertama (test) bebas
    assert rings.admit_target("test") is True
    # Ring berikutnya butuh bukti accept ring sebelumnya
    assert rings.admit_target("trusted") is False
    rings.record_accept("test", "0812-0001")
    assert rings.admit_target("trusted") is True
    assert rings.admit_target("business") is False
    rings.record_accept("trusted", "0812-0002")
    assert rings.admit_target("business") is True
    # Ring tak dikenal → ditolak
    assert rings.admit_target("public_beta") is False


def test_kill_switch_no_live_authority_via_static_contract():
    from pathlib import Path

    source = Path("jarvis/live/call_live_controls.py").read_text(
        encoding="utf-8")
    for forbidden in ("import whatsapp", "requests", "socket", "http",
                      "subprocess", "selenium", "playwright", "write_bytes",
                      "open("):
        assert forbidden not in source, forbidden
