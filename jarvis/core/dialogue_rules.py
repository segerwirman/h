"""WA4-lanjutan — dialogue rules lanjutan + simulator proof.

One-question-at-a-time (pertanyaan ganda ditolak); confirm
dates/prices/reference (pernyataan nilai sensitif non-secret wajib
konfirmasi eksplisit); escalation on payment/objective drift; simulator
membuktikan successful-inquiry / safe-refusal / escalation. Murni lokal;
tanpa provider/network/file.
"""
from __future__ import annotations

import re

_FIXED_REASONS = {
    "dialogue_multiple_questions",
    "dialogue_confirm_required",
    "dialogue_escalation_payment",
    "dialogue_escalation_drift",
}

_CONFIRM_WORDS = ("ya", "betul", "benar", "setuju", "iya", "siap", "ok")
_PAYMENT_MARKERS = (
    "transfer", "bayar", "pembayaran", "payment", "deposit", "kartu",
    "cvv", "otp", "pin ", "password", "passphrase", "rekening", "bank",
)
_REFERENCE_PATTERN = re.compile(r"\b(ORD|INV|REF|TRX)[- ]?\d{3,}\b", re.I)
_DATE_PATTERN = re.compile(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}")
_PRICE_PATTERN = re.compile(r"\b(rp|harga)\s?\d|\b\d{4,}\b|ribu|juta", re.I)


def one_question_at_a_time(text: str) -> dict:
    """Maksimal satu tanda tanya per turn; lebih → ditolak."""
    if (text or "").count("?") > 1:
        return {"ok": False, "reason": "dialogue_multiple_questions"}
    return {"ok": True}


def needs_confirmation(text: str) -> bool:
    """Pernyataan harga/date/reference (BUKAN pertanyaan) wajib konfirmasi."""
    lowered = (text or "").lower()
    if "?" in lowered:
        return False                       # pertanyaan tidak perlu confirm
    if _PRICE_PATTERN.search(lowered) or _DATE_PATTERN.search(text or ""):
        return True
    return bool(_REFERENCE_PATTERN.search(text or ""))


def confirms(text: str) -> bool:
    """Konfirmasi eksplisit — memenuhi kebutuhan confirm."""
    lowered = (text or "").lower()
    return any(word in lowered for word in _CONFIRM_WORDS)


def escalation_reason(text: str) -> str | None:
    """Sentuhan payment/secret → alasan escalation fixed."""
    lowered = (text or "").lower()
    if any(marker in lowered for marker in _PAYMENT_MARKERS):
        return "dialogue_escalation_payment"
    return None


def objective_drift(text: str, objective: str) -> bool:
    """Tidak ada overlap token bermakna dengan objective → drift."""
    tokens = {t.strip(".,!? ") for t in (objective or "").lower().split()
              if len(t.strip(".,!? ")) >= 4}
    lowered = (text or "").lower()
    return not any(token in lowered for token in tokens)


def simulate_dialogue_scenario(scenario: str) -> dict:
    """Simulator proof: alur dialog pendek dengan rules WA4-lanjutan."""
    from jarvis.core.call_session import CallSession
    from jarvis.core.call_dialogue import CallDialogue, LOCAL, REMOTE

    objective = "cek harga kamar dan ketersediaan"
    session = CallSession()
    session.start(contact="Toko Bunga", objective=objective, ttl_s=300)
    session.approve()
    dialogue = CallDialogue()
    dialogue.start(session)
    turns = 0

    def _turn(text: str, source: str) -> dict:
        nonlocal turns
        if dialogue.submit_turn(text, source):
            turns += 1
        return {"ok": True}

    if scenario == "successful_inquiry":
        q = "Harga kamar berapa?"
        if one_question_at_a_time(q).get("ok"):
            _turn(q, LOCAL)
        answer = "150 ribu per malam."
        if needs_confirmation(answer):
            _turn(answer, REMOTE)
            _turn("ya betul.", LOCAL)          # konfirmasi eksplisit
        else:
            _turn(answer, REMOTE)
        return {"ok": True, "outcome": "proceed", "turn_count": turns}

    if scenario == "safe_refusal":
        _turn("Harga kamar berapa?", LOCAL)
        reply = "bisa transfer 100000 dulu ya"
        reason = escalation_reason(reply)
        _turn(reply, REMOTE)
        return {"ok": False, "outcome": "escalated", "reason": reason,
                "turn_count": turns}

    if scenario == "escalation_drift":
        _turn("Harga kamar berapa?", LOCAL)
        reply = "cerita liburan saya kemarin sangat menyenangkan"
        drifted = objective_drift(reply, objective)
        _turn(reply, REMOTE)
        return {"ok": False, "outcome": "escalated",
                "reason": "dialogue_escalation_drift" if drifted else None,
                "turn_count": turns}

    return {"ok": False, "outcome": "unknown_scenario"}


__all__ = ["one_question_at_a_time", "needs_confirmation", "confirms",
           "escalation_reason", "objective_drift",
           "simulate_dialogue_scenario", "_FIXED_REASONS"]
