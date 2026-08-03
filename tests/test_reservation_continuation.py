"""WA7-lanjutan RED — decision continuation & hard block.

Exact option permit (short-lived; changed term INVALIDATES permit) +
hard block payment/CVV/OTP/PIN boundary (no-payment); simulator
changed-price invalidation & no-payment proof. Offline, tanpa provider.
"""
from __future__ import annotations

OPTION = {"price": 150_000, "fees": 0, "date": "2026-08-10",
          "cancellation": "gratis s/d H-1"}


def _fresh(monkeypatch, *, now=1_000.0):
    import jarvis.core.reservation_continuation as rc

    state = {"now": now}
    monkeypatch.setattr(rc, "_now", lambda: state["now"])
    return rc, state


def test_permit_requires_local_approval_and_is_short_lived(monkeypatch):
    rc, state = _fresh(monkeypatch)
    permit = rc.ExactOptionPermit()
    permit.create(OPTION)
    assert permit.status() == "awaiting_approval"
    assert permit.approve() is True
    assert permit.status() == "active"
    assert permit.approve() is False                # one-shot
    # Short-lived: TTL 120s
    state["now"] += 121
    assert permit.status() == "expired"
    assert permit.matches(OPTION) is False


def test_changed_term_invalidates_permit(monkeypatch):
    rc, _state = _fresh(monkeypatch)
    permit = rc.ExactOptionPermit()
    permit.create(OPTION)
    permit.approve()

    assert permit.matches(OPTION) is True           # exact → berlaku
    changed = dict(OPTION, price=160_000)           # harga berubah!
    assert permit.matches(changed) is False
    assert permit.status() == "invalidated"         # changed term → invalid
    # Setelah invalidated, permit tidak pernah berlaku lagi
    assert permit.matches(OPTION) is False


def test_hard_block_detects_payment_boundary():
    import jarvis.core.reservation_continuation as rc

    guard = rc.HardBlockGuard()
    blocked = [
        "tolong transfer 100000 ke rekening",
        "CVV saya 123",
        "OTP 123456",
        "password saya 12345678",
        "bayar pakai kartu 4111111111111111",
        "deposit 50000 dulu",
        "PIN 1234",
    ]
    for text in blocked:
        assert guard.is_blocked(text), text
        assert guard.reason(text) == "reservation_payment_hard_block"

    safe = [
        "jam buka hari ini?",
        "harga kamar berapa?",
        "boleh dibatalkan?",
    ]
    for text in safe:
        assert not guard.is_blocked(text), text


def test_simulator_proves_changed_price_invalidation(monkeypatch):
    rc, _state = _fresh(monkeypatch)
    result = rc.simulate_decision_flow(
        option=OPTION, candidate=dict(OPTION, price=160_000))
    assert result["permit_status"] == "invalidated"
    assert result["commit_allowed"] is False


def test_simulator_proves_no_payment_boundary(monkeypatch):
    rc, _state = _fresh(monkeypatch)
    result = rc.simulate_decision_flow(
        option=OPTION, candidate=OPTION, customer_turn="saya transfer ya")
    assert result["hard_blocked"] is True
    assert result["commit_allowed"] is False


def test_simulator_happy_path_allows_exact_commit(monkeypatch):
    rc, _state = _fresh(monkeypatch)
    result = rc.simulate_decision_flow(option=OPTION, candidate=OPTION)
    assert result["permit_status"] == "active"
    assert result["hard_blocked"] is False
    assert result["commit_allowed"] is True


def test_no_live_authority_via_static_contract(monkeypatch):
    from pathlib import Path

    source = Path(
        "jarvis/core/reservation_continuation.py").read_text(encoding="utf-8")
    for forbidden in ("import whatsapp", "requests", "socket", "http",
                      "subprocess", "selenium", "playwright", "write_bytes"):
        assert forbidden not in source, forbidden
