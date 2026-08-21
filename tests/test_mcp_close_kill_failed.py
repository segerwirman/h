"""Fase 35 — MCP close kill failure stays observable (fake/offline contract).

Migrasi satu baris: ``except Exception: pass`` di ``MCPServer.close()``
diganti ``quiet.swallowed("mcp.close_kill_failed", exc)``. Kontrol flow tidak
berubah: close() tetap mengembalikan None, tetap membersihkan ``_proc``, dan
tidak pernah melempar keluar.

Kontrak fake/offline: tidak ada subprocess nyata, tidak ada spawn server MCP,
tidak ada jaringan. Fake proc hanya objek dengan metode ``kill()``.
"""
from __future__ import annotations

from jarvis.agent import mcp_client
from jarvis.core import quiet


class FakeProc:
    """Fake subprocess handle whose kill() always fails."""

    def __init__(self):
        self.kill_calls = 0

    def kill(self):
        self.kill_calls += 1
        raise OSError("process already gone")

    def poll(self):
        return None


def test_mcp_close_kill_failed_records_event_and_keeps_flow(monkeypatch):
    """kill() gagal → swallowed event tercatat, close() tetap aman."""
    events = []
    monkeypatch.setattr(
        quiet,
        "swallowed",
        lambda event, exc=None, **context: events.append((event, exc, context)),
    )

    srv = mcp_client.MCPServer("fake", "cmd", [])
    fake = FakeProc()
    srv._proc = fake

    result = srv.close()

    # control flow unchanged: None return, _proc cleared, no exception raised
    assert result is None
    assert srv._proc is None
    assert fake.kill_calls == 1
    # kill failure is observable, not silent
    assert len(events) == 1
    assert events[0][0] == "mcp.close_kill_failed"
    assert isinstance(events[0][1], OSError)


def test_mcp_close_without_proc_records_no_event(monkeypatch):
    """close() tanpa proc tetap no-op aman tanpa telemetry."""
    events = []
    monkeypatch.setattr(
        quiet,
        "swallowed",
        lambda event, exc=None, **context: events.append((event, exc, context)),
    )

    srv = mcp_client.MCPServer("fake", "cmd", [])

    result = srv.close()

    assert result is None
    assert srv._proc is None
    assert events == []
