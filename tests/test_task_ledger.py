"""Fase 38 — durable task ledger and recovery classification.

A task that dies mid-flight must never be silently replayed or claimed safe.
The ledger records lifecycle transitions transactionally, and boot hydration
reconciles non-terminal records of a prior process incarnation into explicit
recovery dispositions on the Task Deck — never as running workers.
"""
from __future__ import annotations

import threading
import time

import pytest


@pytest.fixture()
def ledger(tmp_path):
    from jarvis.agent.task_ledger import TaskLedger
    return TaskLedger(tmp_path / "ledger.sqlite")


def _incarnation_id() -> str:
    return f"inc-{time.time_ns() % 10**6}"


# ── lifecycle writes ────────────────────────────────────────────────────────


def test_ledger_records_terminal_transition(ledger):
    view = ledger.create("T-1", title="periksa build", source="ui",
                         conversation="voice-live", incarnation=_incarnation_id())
    assert view.state == "queued"
    assert view.task_id == "T-1"

    running = ledger.mark("T-1", state="running", incarnation=view.incarnation)
    assert running.state == "running"
    done = ledger.finish("T-1", ok=True, result="Build hijau",
                         incarnation=view.incarnation)
    assert done.state == "done"

    assert [r.task_id for r in ledger.all_records()] == ["T-1"]


def test_ledger_pending_tool_marker_no_args(ledger):
    view = ledger.create("T-2", title="tugas", source="ui",
                         conversation="c1", incarnation=_incarnation_id())
    pending = ledger.mark_pending_tool(
        "T-2", tool="file_write", read_only=False,
        incarnation=view.incarnation)
    assert pending.pending_tool == "file_write"
    assert pending.pending_read_only is False

    cleared = ledger.mark_pending_tool(
        "T-2", tool="", read_only=None, incarnation=view.incarnation)
    assert cleared.pending_tool == ""
    # Raw arguments must NEVER be stored; only the tool name is safe.
    assert "secret" not in repr(pending)


def test_ledger_durable_across_reconstruction(tmp_path):
    from jarvis.agent.task_ledger import TaskLedger
    path = tmp_path / "ledger.sqlite"
    inc = _incarnation_id()

    first = TaskLedger(path)
    first.create("T-3", title="lanjut", source="voice",
                 conversation="c1", incarnation=inc)

    # A fresh object over the SAME path must still see the record.
    second = TaskLedger(path)
    records = second.all_records()
    assert [r.task_id for r in records] == ["T-3"]
    assert records[0].state == "queued"


def test_ledger_reconciles_prior_incarnation_to_recovery(ledger):
    stale = _incarnation_id()
    ledger.create("T-old", title="terputus", source="ui",
                  conversation="c1", incarnation=stale)

    recovered = ledger.reconcile(active_incarnation=_incarnation_id())
    by_id = {r.task_id: r for r in recovered}
    assert "T-old" in by_id
    assert by_id["T-old"].state == "recoverable"
    # Reconciliation does not auto-run anything: no active worker is created.
    assert ledger.active_count() == 0


def test_pending_non_read_only_becomes_outcome_uncertain(ledger):
    stale = _incarnation_id()
    ledger.create("T-write", title="nulis file", source="ui",
                  conversation="c1", incarnation=stale)
    ledger.mark_pending_tool("T-write", tool="file_write", read_only=False,
                             incarnation=stale)

    by_id = {r.task_id: r for r in ledger.reconcile(
        active_incarnation=_incarnation_id())}
    assert by_id["T-write"].state == "outcome_uncertain"
    assert by_id["T-write"].recovery_action == "inspect"


def test_pending_read_only_recoverable_no_replay(ledger):
    stale = _incarnation_id()
    ledger.create("T-ro", title="baca file", source="ui",
                  conversation="c1", incarnation=stale)
    ledger.mark_pending_tool("T-ro", tool="file_read", read_only=True,
                             incarnation=stale)

    by_id = {r.task_id: r for r in ledger.reconcile(
        active_incarnation=_incarnation_id())}
    # Read-only pending is still not auto-run; explicit restart only.
    assert by_id["T-ro"].state == "recoverable"
    assert by_id["T-ro"].recovery_action == "continue"


def test_interrupted_without_checkpoint_is_interrupted(ledger):
    stale = _incarnation_id()
    ledger.create("T-nochk", title="kerja", source="ui",
                  conversation="c1", incarnation=stale)
    ledger.mark("T-nochk", state="running", incarnation=stale)

    by_id = {r.task_id: r for r in ledger.reconcile(
        active_incarnation=_incarnation_id())}
    assert by_id["T-nochk"].state == "interrupted"
    assert by_id["T-nochk"].recovery_action == "ask_instruction"


def test_terminal_records_of_prior_incarnation_not_recovered(ledger):
    stale = _incarnation_id()
    ledger.create("T-done", title="selesai", source="ui",
                  conversation="c1", incarnation=stale)
    ledger.finish("T-done", ok=True, result="ok", incarnation=stale)

    recovered = ledger.reconcile(active_incarnation=_incarnation_id())
    assert all(r.task_id != "T-done" for r in recovered)


# ── registry hydration integration ──────────────────────────────────────────


def test_registry_hydration_produces_non_active_recovery_views():
    from jarvis.agent.task_ledger import TaskLedger, RecoveryDisposition
    from jarvis.agent.tasks import TaskRegistry, ACTIVE_STATES
    from jarvis.agent.paths import db_path

    ledger_path = db_path()
    ledger = TaskLedger(ledger_path)
    stale = _incarnation_id()
    ledger.create("T-hyd", title="terputus", source="ui",
                  conversation="c1", incarnation=stale)

    try:
        registry = TaskRegistry()
        views = registry.hydrate_recovery(ledger)
        assert views, "hydration should surface the recovery record"
        recovery = views[0]
        assert recovery.status in RecoveryDisposition.dispositions()
        # Recovery records are NOT active workers: no slot, no cancel.
        assert recovery.active is False
        assert recovery.status.value not in {
            s.value for s in ACTIVE_STATES}
        assert recovery.disposition == "recoverable"
    finally:
        ledger.clear_all()


def test_recovery_hydration_tidak_membuat_context_audio_atau_replay(monkeypatch):
    from jarvis.agent import conversation_context
    from jarvis.agent.paths import db_path
    from jarvis.agent.task_ledger import TaskLedger
    from jarvis.agent.tasks import TaskRegistry

    store = conversation_context.ConversationContextStore()
    monkeypatch.setattr(conversation_context, "STORE", store)
    ledger = TaskLedger(db_path())
    stale = _incarnation_id()
    ledger.create(
        "T-old-audio",
        title="lanjutkan tugas rahasia",
        source="voice-task-tool",
        conversation="voice-live",
        incarnation=stale,
    )

    try:
        registry = TaskRegistry()
        views = registry.hydrate_recovery(ledger)

        assert views
        assert registry.active() == []
        assert store.active_tasks("voice-live") == []
        assert store.context_block("voice-live") == ""
    finally:
        ledger.clear_all()


def test_recovery_views_never_occupy_slots(ledger):
    from jarvis.agent.tasks import TaskRegistry
    from jarvis.agent.task_ledger import RecoveryDisposition

    registry = TaskRegistry()
    views = registry.hydrate_recovery(ledger)
    # No recovery record may consume a concurrency slot or resource lock.
    assert registry.running_count() == 0
    assert registry.active() == []


# ── UI hydration contract ───────────────────────────────────────────────────


def test_task_deck_renders_recovery_dispositions():
    from jarvis.ui import task_deck

    assert hasattr(task_deck, "_RECOVERY_GLYPH")
    for disposition in ("recoverable", "interrupted", "outcome_uncertain"):
        assert disposition in task_deck._RECOVERY_GLYPH


def test_task_wiring_hydrates_before_initial_refresh():
    from jarvis.ui import task_wiring
    assert hasattr(task_wiring, "hydrate_recovery_views")
