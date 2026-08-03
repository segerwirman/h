"""WA6-lanjutan RED — calendar review lanjutan.

Typed outcome mappings (hotel stay, flight departure/arrival, service
appointment, callback); timezone known-set; status confirmed/tentative;
terms/price/reference/reminder bounded; second local approval; write
path `gcal_create_proposed` TETAP fase live (tidak dikerjakan di sini).
Kontrak statis: tanpa provider google/gcal.
"""
from __future__ import annotations

_FUTURE_TS = 1_800_100_000


def _review():
    import jarvis.core.calendar_review as cr

    return cr, cr.CalendarReview()


def test_typed_outcome_mapping():
    import jarvis.core.calendar_review as cr

    assert cr.map_outcome("check-in hotel bintang lima") \
        == cr.OutcomeType.HOTEL_STAY
    assert cr.map_outcome("jam keberangkatan pesawat") \
        == cr.OutcomeType.FLIGHT_DEPARTURE
    assert cr.map_outcome("perkiraan kedatangan") \
        == cr.OutcomeType.FLIGHT_ARRIVAL
    assert cr.map_outcome("janji temu dokter gigi") \
        == cr.OutcomeType.SERVICE_APPOINTMENT
    assert cr.map_outcome("saya telepon balik nanti") \
        == cr.OutcomeType.CALLBACK
    assert cr.map_outcome("cerita belanja") is None


def test_timezone_known_set():
    import jarvis.core.calendar_review as cr

    assert cr.admit_timezone("Asia/Jakarta")["ok"] is True
    assert cr.admit_timezone("UTC")["ok"] is True
    assert cr.admit_timezone("Mars/Olympus")["ok"] is False
    assert cr.admit_timezone("")["ok"] is False


def test_propose_valid_and_rejected_inputs():
    cr, review = _review()
    pid = review.propose(title="Hotel Kamar 101", start_ts=_FUTURE_TS,
                         duration_min=30, outcome="HOTEL_STAY",
                         timezone="Asia/Jakarta", terms="termasuk sarapan",
                         price=150000, reference="ORD-12345",
                         reminder_min=60)
    assert pid is not None
    assert review.status(pid) == "pending"
    # Input invalid → ditolak
    assert review.propose(title="X", start_ts=_FUTURE_TS, duration_min=30,
                          outcome="BELANJA") is None          # outcome asing
    assert review.propose(title="X", start_ts=_FUTURE_TS, duration_min=30,
                          timezone="Mars/Olympus") is None    # tz asing
    assert review.propose(title="X", start_ts=_FUTURE_TS, duration_min=30,
                          price=True) is None                 # bool
    assert review.propose(title="X", start_ts=_FUTURE_TS, duration_min=30,
                          price=-5) is None                   # negatif
    assert review.propose(title="X", start_ts=_FUTURE_TS, duration_min=30,
                          reference="password rahasia") is None  # secret
    assert review.propose(title="X", start_ts=_FUTURE_TS, duration_min=30,
                          terms="t" * 201) is None            # terms > 200
    assert review.propose(title="X", start_ts=_FUTURE_TS, duration_min=30,
                          reminder_min=0) is None


def test_second_local_approval_flow():
    cr, review = _review()
    pid = review.propose(title="Hotel", start_ts=_FUTURE_TS,
                         duration_min=30)
    assert review.first_approve(pid) is True
    assert review.status(pid) == "awaiting_second"
    assert review.second_approve(pid) is True
    assert review.status(pid) == "approved"
    assert review.second_approve(pid) is False        # one-shot
    # Tanpa first → second tidak jalan
    pid2 = review.propose(title="Hotel2", start_ts=_FUTURE_TS,
                          duration_min=30)
    assert review.second_approve(pid2) is False
    assert review.status(pid2) == "pending"


def test_reject_and_tentative_status():
    cr, review = _review()
    pid = review.propose(title="Hotel", start_ts=_FUTURE_TS,
                         duration_min=30)
    assert review.mark_tentative(pid) is True
    assert review.status(pid) == "tentative"
    assert review.first_approve(pid) is False        # tentative bukan pending
    pid2 = review.propose(title="Hotel2", start_ts=_FUTURE_TS,
                          duration_min=30)
    assert review.reject(pid2) is True
    assert review.status(pid2) == "rejected"
    assert review.reject(pid2) is False              # one-shot


def test_review_metadata_only(monkeypatch):
    cr, review = _review()
    pid = review.propose(title="Hotel", start_ts=_FUTURE_TS,
                         duration_min=30, outcome="HOTEL_STAY",
                         timezone="Asia/Jakarta", price=150000)
    review.first_approve(pid)
    meta = review.review(pid)
    assert meta["outcome"] == "HOTEL_STAY"
    assert meta["timezone"] == "Asia/Jakarta"
    assert meta["status"] == "awaiting_second"
    assert meta["price"] == 150000
    text = str(meta)
    for forbidden in ("password", "token=", "payload"):
        assert forbidden not in text, forbidden


def test_no_provider_authority_via_static_contract():
    from pathlib import Path

    source = Path("jarvis/core/calendar_review.py").read_text(encoding="utf-8")
    for forbidden in ("google", "gcal", "create_event", "requests", "http",
                      "open(", "subprocess", "socket", "selenium",
                      "playwright", "import whatsapp"):
        assert forbidden not in source, forbidden
