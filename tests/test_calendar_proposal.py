"""Phase WA6 RED — post-call calendar proposal.

Proposal hanya field allowlist (title/time/duration), tanpa konflik & tanpa
double-booking, local approval sebelum create, metadata result saja; TIDAK
ada authority create otomatis (write path terpisah di fase live).
"""
from __future__ import annotations


def _fresh(monkeypatch, *, now=1_800_000_000):
    import jarvis.core.calendar_proposal as cp

    state = {"now": now}
    monkeypatch.setattr(cp, "_now", lambda: state["now"])
    return cp, state


def test_create_requires_allowlist_fields_only(monkeypatch):
    cp, _state = _fresh(monkeypatch)
    proposal = cp.CalendarProposal()
    # Field di luar allowlist → ditolak
    assert proposal.create(title="Meeting", start_ts=1_800_100_000,
                           duration_min=30, notes="bebas") is False
    assert proposal.create(title="Meeting", start_ts=1_800_100_000,
                           duration_min=30, attendees=["a@b.c"]) is False
    # Allowlist lengkap → diterima
    assert proposal.create(title="Meeting", start_ts=1_800_100_000,
                           duration_min=30) is True
    assert proposal.status() == "draft"


def test_title_and_duration_are_bounded(monkeypatch):
    cp, _state = _fresh(monkeypatch)
    proposal = cp.CalendarProposal()
    assert proposal.create(title="", start_ts=1_800_100_000,
                           duration_min=30) is False
    assert proposal.create(title="x" * 121, start_ts=1_800_100_000,
                           duration_min=30) is False
    assert proposal.create(title="OK\u0000bad", start_ts=1_800_100_000,
                           duration_min=30) is False
    assert proposal.create(title="OK", start_ts=1_800_100_000,
                           duration_min=4) is False        # < min duration
    assert proposal.create(title="OK", start_ts=1_800_100_000,
                           duration_min=1441) is False     # > max duration


def test_start_must_be_in_the_future(monkeypatch):
    cp, state = _fresh(monkeypatch, now=1_800_000_000)
    proposal = cp.CalendarProposal()
    assert proposal.create(title="Lalu", start_ts=1_799_999_999,
                           duration_min=30) is False       # masa lalu
    assert proposal.create(title="Nanti", start_ts=1_800_000_001,
                           duration_min=30) is True


def test_conflict_detection_prevents_double_booking(monkeypatch):
    cp, _state = _fresh(monkeypatch)
    proposal = cp.CalendarProposal()
    assert proposal.create(title="Meeting", start_ts=1_800_100_000,
                           duration_min=30) is True

    # Slot overlap dengan existing → conflict
    assert proposal.has_conflict([(1_800_090_000, 1_800_110_000)]) is True
    assert proposal.has_conflict([(1_800_101_500, 1_800_102_000)]) is True
    # Slot tidak overlap → aman
    assert proposal.has_conflict([(1_800_115_000, 1_800_120_000)]) is False
    assert proposal.has_conflict([(1_800_130_000, 1_800_140_000)]) is False
    assert proposal.has_conflict([]) is False


def test_local_approval_is_one_shot_and_required_for_create(monkeypatch):
    cp, _state = _fresh(monkeypatch)
    proposal = cp.CalendarProposal()
    proposal.create(title="Meeting", start_ts=1_800_100_000, duration_min=30)

    assert proposal.status() == "draft"           # belum boleh create
    assert proposal.approve() is True
    assert proposal.status() == "approved"        # siap create (local approval)
    assert proposal.approve() is False            # one-shot
    assert proposal.reject() is False             # sudah approved


def test_reject_marks_proposal_and_blocks_approval(monkeypatch):
    cp, _state = _fresh(monkeypatch)
    proposal = cp.CalendarProposal()
    proposal.create(title="Meeting", start_ts=1_800_100_000, duration_min=30)
    assert proposal.reject() is True
    assert proposal.status() == "rejected"
    assert proposal.approve() is False


def test_result_is_metadata_only(monkeypatch):
    cp, _state = _fresh(monkeypatch)
    proposal = cp.CalendarProposal()
    proposal.create(title="Meeting", start_ts=1_800_100_000, duration_min=30)
    proposal.approve()
    result = proposal.result()
    assert result["title"] == "Meeting"
    assert result["start_ts"] == 1_800_100_000
    assert result["duration_min"] == 30
    assert result["status"] == "approved"
    for forbidden in ("attendees", "notes", "path", "raw"):
        assert forbidden not in result, forbidden


def test_no_automatic_calendar_write_authority(monkeypatch):
    # Kontrak statis: module proposal TIDAK mengimpor google/gcal/write —
    # create kalender hanya via write path terpisah yang disetujui lokal.
    from pathlib import Path

    source = Path("jarvis/core/calendar_proposal.py").read_text(encoding="utf-8")
    for forbidden in ("google", "gcal", "create_event", "requests",
                      "open(", "write_bytes", "subprocess"):
        assert forbidden not in source, forbidden
