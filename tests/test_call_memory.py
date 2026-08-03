"""Phase WA5 RED — call memory & privacy.

Simpan hanya ringkasan metadata (field allowlist), tanpa transcript/audio;
retention bounded + clear; opt-in config; tidak ada PII/secret di memori.
"""
from __future__ import annotations

_ALLOWED_FIELDS = {"session_id", "status", "duration_s", "turn_count"}


def _memory(monkeypatch, *, enabled=True):
    from jarvis.core import call_memory as cm

    monkeypatch.setattr(cm, "_memory_enabled", lambda: enabled)
    return cm


def _valid_summary(**overrides):
    summary = {
        "session_id": "abc123",
        "status": "done",
        "duration_s": 45,
        "turn_count": 6,
    }
    summary.update(overrides)
    return summary


def test_summary_must_use_allowlist_fields_only(monkeypatch):
    cm = _memory(monkeypatch)
    store = cm.CallMemoryStore()

    assert store.record(_valid_summary()) is True
    # Field di luar allowlist → ditolak (transcript/audio/path/notes)
    assert store.record(_valid_summary(transcript="isi rahasia")) is False
    assert store.record(_valid_summary(audio="data")) is False
    assert store.record(_valid_summary(path="C:/tmp/x.wav")) is False
    assert store.record(_valid_summary(notes="catatan bebas")) is False
    assert store.count() == 1


def test_memory_is_opt_in_via_config(monkeypatch):
    cm = _memory(monkeypatch, enabled=False)
    store = cm.CallMemoryStore()
    assert store.record(_valid_summary()) is False
    assert store.count() == 0


def test_secret_or_pii_in_summary_is_rejected(monkeypatch):
    cm = _memory(monkeypatch)
    store = cm.CallMemoryStore()

    assert store.record(_valid_summary()) is True
    assert store.record(_valid_summary(session_id="password123")) is False
    assert store.record(_valid_summary(session_id="4111111111111111")) is False
    assert store.count() == 1


def test_store_never_contains_transcript_or_audio(monkeypatch):
    cm = _memory(monkeypatch)
    store = cm.CallMemoryStore()
    store.record(_valid_summary())

    for entry in store.list_summaries():
        for forbidden in ("transcript", "audio", "path", "payload", "wav"):
            assert forbidden not in entry, forbidden


def test_retention_is_bounded_and_evicts_oldest(monkeypatch):
    cm = _memory(monkeypatch)
    store = cm.CallMemoryStore()
    for i in range(cm.MAX_ENTRIES + 5):
        store.record(_valid_summary(session_id=f"sid-{i}"))
    assert store.count() == cm.MAX_ENTRIES
    # Yang tertua di-evict
    remaining = {e["session_id"] for e in store.list_summaries()}
    assert "sid-0" not in remaining
    assert f"sid-{cm.MAX_ENTRIES + 4}" in remaining


def test_clear_empties_the_store(monkeypatch):
    cm = _memory(monkeypatch)
    store = cm.CallMemoryStore()
    store.record(_valid_summary())
    store.record(_valid_summary(session_id="def456"))
    assert store.count() == 2
    store.clear()
    assert store.count() == 0
    assert store.list_summaries() == []


def test_memory_metadata_is_safe_to_serialize(monkeypatch):
    cm = _memory(monkeypatch)
    store = cm.CallMemoryStore()
    store.record(_valid_summary())
    text = str(store.list_summaries())
    assert "abc123" in text                       # session_id metadata OK
    assert "isi rahasia" not in text
