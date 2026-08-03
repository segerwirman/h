"""Phase WA4 RED — bounded autonomous call dialogue.

Turn policy (alternasi ketat local ↔ remote), stop word + user interrupt,
no secret/PII disclosure (turn ditolak, tidak disimpan), per-turn objective
guard, bounded turn count, summary metadata-only (tanpa transcript).
"""
from __future__ import annotations

from jarvis.core.bus import BUS

LOCAL = "local"
REMOTE = "remote"


def _fresh_dialogue(monkeypatch):
    import jarvis.core.call_dialogue as cd

    return cd


def _active_session(monkeypatch, *, now=1000.0):
    import jarvis.core.call_session as cs

    state = {"now": now}
    monkeypatch.setattr(cs, "_now", lambda: state["now"])
    session = cs.CallSession()
    session.start("+6281111", "Tanya harga", 60)
    session.approve()
    return session


def test_start_requires_approved_active_session(monkeypatch):
    cd = _fresh_dialogue(monkeypatch)
    import jarvis.core.call_session as cs

    idle = cs.CallSession()
    awaiting = cs.CallSession()
    awaiting.start("+6281111", "Tanya harga", 60)

    dialogue = cd.CallDialogue()
    assert dialogue.start(idle) is False
    assert dialogue.start(awaiting) is False
    assert dialogue.start(None) is False
    assert dialogue.start(_active_session(monkeypatch)) is True
    assert dialogue.status() == "running"


def test_turn_alternation_is_strict(monkeypatch):
    cd = _fresh_dialogue(monkeypatch)
    session = _active_session(monkeypatch)
    dialogue = cd.CallDialogue()
    dialogue.start(session)

    assert dialogue.submit_turn("Halo, ada info harga?", LOCAL) is True
    assert dialogue.submit_turn("Tentu, harga mulai 100rb.", REMOTE) is True
    # Remote mencoba double-turn (masih giliran local) → ditolak
    assert dialogue.submit_turn("Saya remote lagi?", REMOTE) is False
    assert dialogue.submit_turn("Baik, saya catat.", LOCAL) is True
    # Local mencoba double-turn (sekarang giliran remote) → ditolak
    assert dialogue.submit_turn("Saya local lagi?", LOCAL) is False
    assert dialogue.submit_turn("Terima kasih!", REMOTE) is True


def test_turn_text_is_bounded(monkeypatch):
    cd = _fresh_dialogue(monkeypatch)
    session = _active_session(monkeypatch)
    dialogue = cd.CallDialogue()
    dialogue.start(session)

    assert dialogue.submit_turn("", LOCAL) is False
    assert dialogue.submit_turn("   ", LOCAL) is False
    assert dialogue.submit_turn("x" * 501, LOCAL) is False
    assert dialogue.submit_turn("Halo\u0000dunia", LOCAL) is False
    assert dialogue.submit_turn("Halo normal", LOCAL) is True


def test_dialogue_is_bounded_by_max_turns(monkeypatch):
    cd = _fresh_dialogue(monkeypatch)
    session = _active_session(monkeypatch)
    dialogue = cd.CallDialogue()
    dialogue.start(session)

    # Isi sampai batas maksimum turn (bergantian)
    submitted = 0
    source = LOCAL
    for _ in range(cd.MAX_TURNS):
        if dialogue.submit_turn(f"Turn {submitted}", source):
            submitted += 1
            source = REMOTE if source == LOCAL else LOCAL
    assert submitted == cd.MAX_TURNS
    assert dialogue.status() == "completed"
    # Tidak ada turn lagi setelah batas
    assert dialogue.submit_turn("Terlambat", LOCAL) is False


def test_stop_word_interrupts_dialogue(monkeypatch):
    cd = _fresh_dialogue(monkeypatch)
    events = []
    BUS.subscribe("call.dialogue.ended", lambda d: events.append(d))
    session = _active_session(monkeypatch)
    dialogue = cd.CallDialogue()
    dialogue.start(session)

    dialogue.submit_turn("Berapa totalnya?", LOCAL)
    assert dialogue.submit_turn("Cukup, berhenti.", REMOTE) is True
    assert dialogue.status() == "interrupted"
    assert len(events) == 1
    assert events[0]["status"] == "interrupted"


def test_secret_and_pii_turns_are_rejected_and_not_stored(monkeypatch):
    cd = _fresh_dialogue(monkeypatch)
    session = _active_session(monkeypatch)
    dialogue = cd.CallDialogue()
    dialogue.start(session)

    # Giliran local pertama diterima
    assert dialogue.submit_turn("Bisa kirim detail?", LOCAL) is True
    # Remote mencoba meminta/menyebut secret → ditolak
    assert dialogue.submit_turn("Password admin saya 12345", REMOTE) is False
    assert dialogue.submit_turn("Token API: abc123def", REMOTE) is False
    assert dialogue.submit_turn("Kartu 4111111111111111", REMOTE) is False
    # Turn yang ditolak TIDAK masuk hitungan dan TIDAK tersimpan
    assert dialogue.turn_count() == 1
    assert "12345" not in str(dialogue.summary())


def test_session_end_stops_dialogue(monkeypatch):
    cd = _fresh_dialogue(monkeypatch)
    session = _active_session(monkeypatch)
    dialogue = cd.CallDialogue()
    dialogue.start(session)
    session.end()
    assert dialogue.status() == "ended"
    assert dialogue.submit_turn("Masih ada?", LOCAL) is False


def test_summary_is_metadata_only_without_transcript(monkeypatch):
    cd = _fresh_dialogue(monkeypatch)
    session = _active_session(monkeypatch)
    dialogue = cd.CallDialogue()
    dialogue.start(session)
    dialogue.submit_turn("Halo, ada info harga?", LOCAL)
    dialogue.submit_turn("Tentu, mulai 100rb.", REMOTE)

    summary = dialogue.summary()
    assert summary["status"] == "running"
    assert summary["turn_count"] == 2
    assert summary["sources"] == [LOCAL, REMOTE]
    assert summary["session_id"] == session.session_id()
    # metadata-only: konten turn TIDAK pernah muncul
    for forbidden in ("Halo", "100rb", "transcript", "text"):
        assert forbidden not in summary, forbidden
