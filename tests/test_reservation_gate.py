"""Phase WA7 RED — reservation commitment gate.

Reservasi = komitmen → wajib gate ekstra: local approval + fixed
disclosure labels + cancellation window. Tanpa auto-commit; setiap gate
failure → no-op + alasan fixed (reason code), tidak ada side effect.
"""
from __future__ import annotations

_FIXED_REASONS = {
    "reservation_approval_missing",
    "reservation_disclosure_missing",
    "reservation_cancellation_window_missing",
    "reservation_unknown_label",
}


def test_gate_fails_without_local_approval():
    from jarvis.core.reservation_gate import ReservationCommitmentGate

    gate = ReservationCommitmentGate()
    result = gate.evaluate(
        approved=False,
        labels=["commitment", "cancellation_policy"],
        cancel_within_days=7,
    )
    assert result["ok"] is False
    assert result["reason"] == "reservation_approval_missing"
    assert not gate.ready()


def test_gate_rejects_unknown_disclosure_labels():
    from jarvis.core.reservation_gate import ReservationCommitmentGate

    gate = ReservationCommitmentGate()
    result = gate.evaluate(
        approved=True,
        labels=["commitment", "diskon 50% gratis"],
        cancel_within_days=7,
    )
    assert result["ok"] is False
    assert result["reason"] == "reservation_unknown_label"
    # label kosong → disclosure missing
    result = gate.evaluate(approved=True, labels=[], cancel_within_days=7)
    assert result["ok"] is False
    assert result["reason"] == "reservation_disclosure_missing"


def test_gate_requires_cancellation_window():
    from jarvis.core.reservation_gate import ReservationCommitmentGate

    gate = ReservationCommitmentGate()
    result = gate.evaluate(
        approved=True,
        labels=["commitment", "cancellation_policy"],
        cancel_within_days=0,
    )
    assert result["ok"] is False
    assert result["reason"] == "reservation_cancellation_window_missing"
    result = gate.evaluate(
        approved=True,
        labels=["commitment", "cancellation_policy"],
        cancel_within_days=366,
    )
    assert result["ok"] is False
    assert result["reason"] == "reservation_cancellation_window_missing"


def test_gate_passes_only_when_all_conditions_met():
    from jarvis.core.reservation_gate import ReservationCommitmentGate

    gate = ReservationCommitmentGate()
    result = gate.evaluate(
        approved=True,
        labels=["commitment", "cancellation_policy"],
        cancel_within_days=7,
    )
    assert result["ok"] is True
    assert result["reason"] is None
    assert gate.ready() is True


def test_failure_is_a_noop_without_side_effects():
    from jarvis.core.reservation_gate import ReservationCommitmentGate

    gate = ReservationCommitmentGate()
    before = gate.snapshot()
    result = gate.evaluate(
        approved=False,
        labels=["commitment"],
        cancel_within_days=7,
    )
    assert result["ok"] is False
    # no-op: state gate tidak berubah, tidak ada commitment tercatat
    assert gate.snapshot() == before
    assert gate.commitments() == []


def test_commitment_is_recorded_only_after_green_light():
    from jarvis.core.reservation_gate import ReservationCommitmentGate

    gate = ReservationCommitmentGate()
    # Tanpa green light → tidak tercatat
    gate.evaluate(approved=False, labels=["commitment"],
                  cancel_within_days=7)
    assert gate.commitments() == []

    # Green light → tercatat sebagai commitment metadata (bukan eksekusi)
    result = gate.evaluate(approved=True,
                           labels=["commitment", "cancellation_policy"],
                           cancel_within_days=7)
    assert result["ok"] is True
    entries = gate.commitments()
    assert len(entries) == 1
    assert entries[0]["status"] == "ready"
    assert entries[0]["cancel_within_days"] == 7


def test_fixed_reason_codes_are_a_closed_set():
    from jarvis.core.reservation_gate import _FIXED_REASONS as reasons

    assert reasons == _FIXED_REASONS
    # Semua reason di evaluate berasal dari set fixed
    from jarvis.core.reservation_gate import ReservationCommitmentGate

    gate = ReservationCommitmentGate()
    results = [
        gate.evaluate(approved=False, labels=[], cancel_within_days=7),
        gate.evaluate(approved=True, labels=[], cancel_within_days=7),
        gate.evaluate(approved=True, labels=["x"], cancel_within_days=0),
    ]
    for result in results:
        assert result["ok"] is False
        assert result["reason"] in reasons, result["reason"]
