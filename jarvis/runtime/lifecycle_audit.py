"""Phase 24 — static runtime lifecycle ownership table.

Canonical contract: every boot-started or task-owned thread/process/lease has
an explicit owner, stop path, join policy, and honest failure state. This
table is the single source of truth verified by tests against canonical boot
modes. It never changes runtime behavior by itself.
"""
from __future__ import annotations

# (component, owner, stop_path, join_policy, failure_state)
LIFECYCLE_OWNERSHIP = (
    ("cron_scheduler", "CronScheduler", "stop()", "join(interval+1)",
     "thread daemon; stop event + bounded join; state jujur"),
    ("telegram_polling", "TelegramService", "stop()", "join(8s)",
     "running flag False; app.stop_running via loop"),
    ("monitor_worker", "MonitorWorker", "stop()", "join(interval+1)",
     "worker joined; jobs safe-fail (17K)"),
    ("screen_awareness", "AwarenessWatcher", "stop()", "join(2s)",
     "awareness.stopped logged"),
    ("voice_pipeline_monitor", "PipelineState", "stop_monitor()", "join(2s)",
     "monitor None setelah stop"),
    ("wake_detector", "WakeDetector", "stop()", "join(2s each)",
     "wake.stopped logged; threads list kosong"),
    ("browser_session", "BrowserSession", "_ensure closing", "join(5s)",
     "state closing; lease owner kosong"),
    ("remote_setup_sweeper", "SetupQueue", "close()", "join(interval+1)",
     "sweeper joined; staging cleanup berhenti"),
    ("dispatch_worker", "agent.dispatch", "n/a", "n/a",
     "slot + browser/computer/desktop-safe leases released di finally"),
    ("response_composer", "fire-and-forget daemon", "n/a", "n/a",
     "single-shot bounded worker"),
    ("ack_composer", "fire-and-forget daemon", "n/a", "n/a",
     "single-shot bounded worker"),
    ("spotify_oauth", "fire-and-forget daemon", "n/a", "n/a",
     "single-shot callback server"),
    ("llm_generate", "fire-and-forget daemon", "n/a", "n/a",
     "single-shot bounded worker"),
    ("boot_sequence", "boot-seq daemon", "n/a", "n/a",
     "single-shot bounded probe"),
    ("skill_curator", "fire-and-forget daemon", "n/a", "n/a",
     "single-shot bounded run"),
    ("tier_classifier", "fire-and-forget daemon", "n/a", "done.wait(budget)",
     "bounded budget; result atau kosong"),
)


def audit_ownership() -> dict:
    """Return the canonical ownership snapshot (metadata only)."""
    return {
        "entries": len(LIFECYCLE_OWNERSHIP),
        "components": [entry[0] for entry in LIFECYCLE_OWNERSHIP],
    }


SUBPROCESS_LIMITATION = (
    "Subprocess eksternal (terminal, code_exec, mcp_client, voice engine, "
    "hermes bridge) tidak dapat di-hard-kill dari dalam proses; stop dilakukan "
    "via cooperative terminate request; bila proses tidak keluar, timeout/"
    "cancel state dilaporkan jujur sebagai terminate_requested — tidak "
    "disembunyikan sebagai sukses."
)


__all__ = ["LIFECYCLE_OWNERSHIP", "audit_ownership", "SUBPROCESS_LIMITATION"]
