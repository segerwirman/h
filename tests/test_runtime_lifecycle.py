"""Phase 24 RED — runtime lifecycle reliability sweep.

Static ownership table + bounded join contract for canonical boot/task-owned
resources. RED: ownership table belum ada; cron.stop() dan SetupQueue.close()
belum men-join thread-nya.
"""
from __future__ import annotations

import time

_CANONICAL_COMPONENTS = (
    "cron_scheduler",
    "telegram_polling",
    "monitor_worker",
    "screen_awareness",
    "voice_pipeline_monitor",
    "wake_detector",
    "browser_session",
    "remote_setup_sweeper",
    "dispatch_worker",
    "response_composer",
    "ack_composer",
    "boot_sequence",
)


def test_ownership_table_covers_all_canonical_components():
    # RED: jarvis/runtime/lifecycle_audit.py belum ada
    from jarvis.runtime.lifecycle_audit import LIFECYCLE_OWNERSHIP

    components = {entry[0] for entry in LIFECYCLE_OWNERSHIP}
    for name in _CANONICAL_COMPONENTS:
        assert name in components, f"komponen {name} tidak terdaftar"


def test_ownership_table_entries_have_owner_and_join_policy():
    from jarvis.runtime.lifecycle_audit import LIFECYCLE_OWNERSHIP

    for component, owner, stop_path, join_policy, failure_state in LIFECYCLE_OWNERSHIP:
        assert owner and owner != "n/a", component
        assert failure_state, component
        if stop_path != "n/a":
            assert join_policy and join_policy != "n/a", component


def test_audit_ownership_reports_components():
    from jarvis.runtime.lifecycle_audit import audit_ownership

    report = audit_ownership()
    assert report["entries"] >= len(_CANONICAL_COMPONENTS)
    assert set(_CANONICAL_COMPONENTS) <= set(report["components"])


def test_cron_stop_joins_scheduler_thread():
    from jarvis.agent.cron import CronScheduler

    scheduler = CronScheduler()
    scheduler._interval = 0.05
    scheduler.start()
    time.sleep(0.15)
    assert scheduler._thread is not None and scheduler._thread.is_alive()
    scheduler.stop()
    # RED: stop() hanya set event tanpa join -> thread masih hidup
    assert scheduler._thread is None or not scheduler._thread.is_alive()


def test_setup_queue_close_joins_sweeper_thread():
    from jarvis.agent.remote_setup import SetupQueue

    queue = SetupQueue(ttl_s=0.2)   # interval sweeper = 0.1s
    sweeper = queue._sweeper
    assert sweeper.is_alive()
    queue.close()
    # RED: close() hanya set event tanpa join -> sweeper masih menunggu interval
    assert not sweeper.is_alive()


def test_dispatch_worker_releases_leases_in_finally():
    # Kontrak statis: worker task selalu melepas browser/computer/desktop-safe
    # session di blok finally, apa pun hasil task-nya.
    from pathlib import Path

    source = Path("jarvis/agent/dispatch.py").read_text(encoding="utf-8")
    finally_block = source.split("finally:")[1].split("threading.Thread")[0]
    assert "_release_browser_session(session.id)" in finally_block
    assert "_release_computer_session(session.id)" in finally_block
    assert "_clear_desktop_safe_session(session.id)" in finally_block
    assert "REGISTRY.release_slot(bg_task)" in finally_block


def test_subprocess_non_killable_limitation_is_documented():
    # Phase 24 acceptance: batas subprocess non-killable DIDOKUMENTASIKAN,
    # bukan disembunyikan.
    from jarvis.runtime import lifecycle_audit

    assert hasattr(lifecycle_audit, "SUBPROCESS_LIMITATION")
    assert "kill" in lifecycle_audit.SUBPROCESS_LIMITATION.lower()
    assert "jujur" in lifecycle_audit.SUBPROCESS_LIMITATION.lower()
