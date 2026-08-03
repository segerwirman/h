"""WA4-lanjutan RED — dialogue rules lanjutan + simulator proof.

One-question-at-a-time; confirm dates/prices/reference; escalation on
payment/objective drift; simulator successful-inquiry/safe-refusal/
escalation proof. Murni lokal; tanpa provider/network.
"""
from __future__ import annotations

_FIXED_REASONS = {
    "dialogue_multiple_questions",
    "dialogue_confirm_required",
    "dialogue_escalation_payment",
    "dialogue_escalation_drift",
}


def test_one_question_at_a_time_rule():
    import jarvis.core.dialogue_rules as dr

    assert dr.one_question_at_a_time("Harga kamar berapa?")["ok"] is True
    assert dr.one_question_at_a_time("Harga berapa?")["ok"] is True
    # Lebih dari satu pertanyaan → ditolak
    result = dr.one_question_at_a_time("Harga berapa? Bisa kurang?")
    assert result["ok"] is False
    assert result["reason"] == "dialogue_multiple_questions"
    # Tanpa pertanyaan (jawaban) → OK
    assert dr.one_question_at_a_time("Baik, saya catat.")["ok"] is True


def test_confirm_dates_prices_reference():
    import jarvis.core.dialogue_rules as dr

    assert dr.needs_confirmation("harga 150 ribu") is True
    assert dr.needs_confirmation("Rp500.000 sudah termasuk") is True
    assert dr.needs_confirmation("tanggal 10/08/2026") is True
    assert dr.needs_confirmation("referensi ORD-12345") is True
    assert dr.needs_confirmation("halo, apa kabar") is False
    # Konfirmasi eksplisit memenuhi
    assert dr.confirms("ya betul, 150 ribu") is True
    assert dr.confirms("benar, ORD-12345") is True
    assert dr.confirms("cerita saja") is False
    # Nilai sensitif tetap ter-escalate, bukan sekadar confirm
    assert dr.escalation_reason("transfer 100000") \
        == "dialogue_escalation_payment"


def test_escalation_on_payment_and_drift():
    import jarvis.core.dialogue_rules as dr

    assert dr.escalation_reason("tolong transfer dulu") \
        == "dialogue_escalation_payment"
    assert dr.escalation_reason("OTP saya 123456") \
        == "dialogue_escalation_payment"
    assert dr.escalation_reason("jam buka hari ini?") is None

    objective = "cek harga kamar dan ketersediaan"
    assert dr.objective_drift("cerita liburan saya kemarin", objective) is True
    assert dr.objective_drift("harga kamar berapa?", objective) is False


def test_simulator_successful_inquiry(monkeypatch):
    import jarvis.core.dialogue_rules as dr

    result = dr.simulate_dialogue_scenario("successful_inquiry")
    assert result["ok"] is True
    assert result["outcome"] == "proceed"
    assert result["turn_count"] >= 2


def test_simulator_safe_refusal(monkeypatch):
    import jarvis.core.dialogue_rules as dr

    result = dr.simulate_dialogue_scenario("safe_refusal")
    assert result["ok"] is False
    assert result["outcome"] == "escalated"
    assert result["reason"] == "dialogue_escalation_payment"


def test_simulator_escalation_drift(monkeypatch):
    import jarvis.core.dialogue_rules as dr

    result = dr.simulate_dialogue_scenario("escalation_drift")
    assert result["ok"] is False
    assert result["outcome"] == "escalated"
    assert result["reason"] == "dialogue_escalation_drift"


def test_reason_codes_closed_set_and_metadata_only(monkeypatch):
    import jarvis.core.dialogue_rules as dr

    results = [
        dr.one_question_at_a_time("A? B?"),
        dr.simulate_dialogue_scenario("safe_refusal"),
        dr.simulate_dialogue_scenario("escalation_drift"),
    ]
    for result in results:
        if result.get("reason"):
            assert result["reason"] in _FIXED_REASONS, result["reason"]
            assert result["reason"] in dr._FIXED_REASONS
    text = str(dr.simulate_dialogue_scenario("successful_inquiry"))
    for forbidden in ("password", "token=", "path", "payload"):
        assert forbidden not in text, forbidden


def test_no_live_authority_via_static_contract(monkeypatch):
    from pathlib import Path

    source = Path("jarvis/core/dialogue_rules.py").read_text(encoding="utf-8")
    for forbidden in ("import whatsapp", "requests", "socket", "http",
                      "subprocess", "selenium", "playwright", "write_bytes"):
        assert forbidden not in source, forbidden
