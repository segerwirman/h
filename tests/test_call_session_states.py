"""WA2-lanjutan RED — call states DIALING/CONNECTED/AWAITING_DECISION/FAILED
+ constraints & allowed disclosures field."""
from __future__ import annotations


def _session():
    from jarvis.core.call_session import CallSession

    session = CallSession()
    session.start(contact="Toko Bunga", objective="cek jam buka", ttl_s=300)
    session.approve()
    return session


def test_dial_connect_await_decision_flow():
    session = _session()
    assert session.status() == "active"
    assert session.dial() is True
    assert session.status() == "dialing"
    assert session.connect() is True
    assert session.status() == "connected"
    assert session.await_decision() is True
    assert session.status() == "awaiting_decision"
    assert session.end() is True
    assert session.status() == "done"


def test_fail_from_dialing_or_connected():
    session = _session()
    session.dial()
    assert session.fail() is True
    assert session.status() == "failed"

    session2 = _session()
    session2.dial()
    session2.connect()
    assert session2.fail() is True
    assert session2.status() == "failed"


def test_invalid_transitions_are_rejected():
    session = _session()
    # connect langsung dari active (belum dialing) → ditolak
    assert session.connect() is False
    assert session.await_decision() is False
    # fail dari active → ditolak
    assert session.fail() is False

    session2 = _session()
    session2.dial()
    # dial dua kali → ditolak
    assert session2.dial() is False
    # await_decision dari dialing (belum connected) → ditolak
    assert session2.await_decision() is False


def test_cancel_and_end_work_from_new_states():
    session = _session()
    session.dial()
    session.connect()
    assert session.cancel() is True
    assert session.status() == "cancelled"

    session2 = _session()
    session2.dial()
    assert session2.end() is True
    assert session2.status() == "done"


def test_constraints_and_allowed_disclosures_are_validated():
    from jarvis.core.call_session import CallSession

    session = CallSession()
    ok = session.start(
        contact="Toko Bunga", objective="cek jam buka", ttl_s=300,
        constraints={"max_duration_min": 30, "max_turns": 20},
        allowed_disclosures=("hours", "price"))
    assert ok is True
    assert session.constraints() == {"max_duration_min": 30,
                                     "max_turns": 20}
    assert session.disclosure_allowed("hours") is True
    assert session.disclosure_allowed("payment_details") is False

    # Key constraint asing → ditolak
    bad = CallSession()
    assert bad.start(contact="X", objective="Y", ttl_s=300,
                     constraints={"free_form": True}) is False
    # allowed_disclosures bukan tuple/list → ditolak
    bad2 = CallSession()
    assert bad2.start(contact="X", objective="Y", ttl_s=300,
                      allowed_disclosures="hours") is False


def test_backward_compat_without_new_fields():
    from jarvis.core.call_session import CallSession

    session = CallSession()
    assert session.start(contact="Toko Bunga", objective="cek jam buka",
                         ttl_s=300) is True
    assert session.constraints() == {}
    assert session.disclosure_allowed("hours") is False


def test_result_includes_constraints_metadata():
    session = _session()
    result = session.result()
    assert "constraints" in result
    assert "allowed_disclosures" in result
    assert result["status"] == "active"
