"""Phase WA2 RED — bounded call session state machine + local approval.

Remote hanya dapat mengirim proposal enum (bukan eksekusi); transisi state
hanya via local approval. TTL + one-shot; metadata result saja.
"""
from __future__ import annotations

from jarvis.core.bus import BUS


def _fresh_session(monkeypatch, *, now=1000.0):
    import jarvis.core.call_session as cs

    state = {"now": now}
    monkeypatch.setattr(cs, "_now", lambda: state["now"])
    return cs, state


def test_start_requires_valid_contact_objective_ttl(monkeypatch):
    cs, _state = _fresh_session(monkeypatch)
    session = cs.CallSession()
    assert session.start("", "Tanya harga", 60) is False
    assert session.start("   ", "Tanya harga", 60) is False
    assert session.start("+6281111", "", 60) is False
    assert session.start("+6281111", "x" * 501, 60) is False
    assert session.start("+6281111", "Tanya harga", 29) is False      # < min TTL
    assert session.start("+6281111", "Tanya harga", 3601) is False    # > max TTL
    assert session.start("+6281111", "Tanya harga", 5.5) is False
    assert session.status() == "idle"


def test_start_enters_awaiting_and_publishes(monkeypatch):
    cs, _state = _fresh_session(monkeypatch)
    events = []
    BUS.subscribe("call.proposed", lambda d: events.append(d))
    session = cs.CallSession()
    assert session.start("+6281111", "Tanya harga", 60) is True
    assert session.status() == "awaiting"
    assert session.ttl_s() == 60
    assert len(events) == 1
    assert events[0]["session_id"] == session.session_id()


def test_remote_proposal_is_enum_only(monkeypatch):
    cs, _state = _fresh_session(monkeypatch)
    session = cs.CallSession()
    session.start("+6281111", "Tanya harga", 60)
    # Enum anggota diterima sebagai proposal (bukan eksekusi)
    assert session.propose(cs.RemoteCallProposal.ACCEPT) is True
    assert session.propose(cs.RemoteCallProposal.DECLINE) is True
    # String bebas / non-anggota ditolak — hanya enum
    assert session.propose("ACCEPT") is False
    assert session.propose("rm -rf /") is False
    # Proposal TIDAK mengubah state — masih menunggu approval lokal
    assert session.status() == "awaiting"


def test_local_approval_transitions_to_active_once(monkeypatch):
    cs, _state = _fresh_session(monkeypatch)
    events = []
    BUS.subscribe("call.approved", lambda d: events.append(d))
    session = cs.CallSession()
    session.start("+6281111", "Tanya harga", 60)
    assert session.approve() is True
    assert session.status() == "active"
    assert session.approve() is False               # one-shot
    assert len(events) == 1


def test_end_transitions_to_done_and_is_one_shot(monkeypatch):
    cs, _state = _fresh_session(monkeypatch)
    session = cs.CallSession()
    session.start("+6281111", "Tanya harga", 60)
    session.approve()
    assert session.end() is True
    assert session.status() == "done"
    assert session.end() is False
    assert session.start("+6282222", "Baru", 60) is False   # one-shot


def test_cancel_is_bounded_and_publishes(monkeypatch):
    cs, _state = _fresh_session(monkeypatch)
    events = []
    BUS.subscribe("call.cancelled", lambda d: events.append(d))
    session = cs.CallSession()
    session.start("+6281111", "Tanya harga", 60)
    assert session.cancel() is True
    assert session.status() == "cancelled"
    assert session.cancel() is False               # idempotent
    assert len(events) == 1


def test_ttl_expiry_is_deadline_based(monkeypatch):
    cs, state = _fresh_session(monkeypatch, now=1000.0)
    events = []
    BUS.subscribe("call.expired", lambda d: events.append(d))
    session = cs.CallSession()
    session.start("+6281111", "Tanya harga", 60)
    state["now"] = 1059.9
    assert session.status() == "awaiting"          # belum lewat TTL
    state["now"] = 1060.1
    assert session.status() == "expired"           # TTL habis tanpa approve
    assert len(events) == 1                        # publish sekali
    assert session.approve() is False              # tidak bisa approve lagi


def test_result_is_metadata_only(monkeypatch):
    cs, _state = _fresh_session(monkeypatch)
    session = cs.CallSession()
    session.start("+6281111", "Tanya harga", 60)
    session.approve()
    result = session.result()
    assert result["status"] == "active"
    assert result["session_id"] == session.session_id()
    assert result["contact"] == "+6281111"
    assert result["objective"] == "Tanya harga"
    # metadata-only: tidak ada transcript/audio/path/raw
    for forbidden in ("transcript", "audio", "path", "raw", "payload"):
        assert forbidden not in result, forbidden
