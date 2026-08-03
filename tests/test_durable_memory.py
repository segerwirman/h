"""WA5-lanjutan RED — durable semantic memory & recall.

Facts yang disetujui (non-secret) → memori durable opt-in; recall by
query; retention bounded (ring buffer) + clear; tanpa transcript/audio,
tanpa file write/provider/network.
"""
from __future__ import annotations

MAX_FACTS = 50


def _memory():
    import jarvis.core.durable_memory as dm

    return dm, dm.DurableMemory()


def test_opt_in_enabled_flag():
    dm, mem = _memory()
    assert mem.enabled() is False          # default opt-out
    assert mem.propose("harga kamar 150 ribu") is None   # disabled → tanpa id
    mem.set_enabled(True)
    assert mem.enabled() is True


def test_propose_approve_flow_is_local_and_one_shot():
    dm, mem = _memory()
    mem.set_enabled(True)
    pid = mem.propose("customer preferensi kopi robusta")
    assert pid is not None
    assert mem.approve(pid) is True
    assert mem.approve(pid) is False       # one-shot
    assert mem.recall("kopi") == ["customer preferensi kopi robusta"]
    pid2 = mem.propose("customer suka teh")
    assert mem.reject(pid2) is True
    assert mem.recall("teh") == []
    assert mem.reject(pid2) is False       # one-shot


def test_secret_never_enters_memory():
    dm, mem = _memory()
    mem.set_enabled(True)
    for bad in ("password saya rahasia123", "token=abc123",
                "OTP 123456", "cvv 789", "transfer 50000",
                "rekening 1234567890"):
        assert mem.propose(bad) is None, bad      # ditolak di propose
    assert mem.recall() == []


def test_recall_by_query_and_empty_query():
    dm, mem = _memory()
    mem.set_enabled(True)
    p1 = mem.propose("customer pesan kamar deluxe")
    p2 = mem.propose("checkout pukul 12 siang")
    mem.approve(p1)
    mem.approve(p2)
    assert mem.recall("kamar") == ["customer pesan kamar deluxe"]
    assert len(mem.recall()) == 2          # tanpa query → semua
    assert mem.recall("tidakada") == []


def test_retention_bounded_ring_buffer():
    dm, mem = _memory()
    mem.set_enabled(True)
    for i in range(MAX_FACTS + 5):
        assert mem.propose(f"fact nomor {i}") is not None
    # approve semua
    for pid in list(mem.pending_ids()):
        mem.approve(pid)
    assert len(mem.recall()) == MAX_FACTS  # bounded
    assert "fact nomor 0" not in mem.recall()      # tertua tergeser
    assert "fact nomor 4" not in mem.recall()
    assert "fact nomor 54" in mem.recall()


def test_clear_removes_everything():
    dm, mem = _memory()
    mem.set_enabled(True)
    pid = mem.propose("fakta sementara")
    mem.approve(pid)
    assert len(mem.recall()) == 1
    assert mem.clear() is True
    assert mem.recall() == []


def test_metadata_only_and_no_file_write():
    import io
    from pathlib import Path

    source = Path("jarvis/core/durable_memory.py").read_text(encoding="utf-8")
    for forbidden in ("open(", "write_bytes", "import whatsapp", "requests",
                      "socket", "http", "subprocess", "selenium",
                      "playwright"):
        assert forbidden not in source, forbidden
