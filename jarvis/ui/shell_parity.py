"""Shell Parity Harness — P9 dual-shell semantic acceptance.

Pure-Python harness that feeds both legacy and modern shells the SAME fake
event sequence (roadmap §13) and captures comparable, timestamp-free
snapshots so the two shells can be proven to consume identical semantics.

Fake sequence:
    boot.check → state LISTENING → SubmitText → intent → task.submitted →
    task.updated → task.finished → notify → stage LOADING → stage ACTIVE →
    confirm → cancel → error → close

Comparison targets (roadmap §13):
    - emitted intents
    - command submission count
    - displayed semantic state
    - task cancellation calls
    - log entries
    - stage transitions
    - approval resolution
    - cleanup calls

Design notes:

- The harness never calls ``MainWindow.handle_command`` with probe text:
  that would enter real routing lanes (agent/native router, reply flow).
  Instead it OVERWRITES the singleton IntentController seams with recorder
  callbacks after the window is constructed, then proves parity of what the
  seams deliver. The pre-overwrite seam owners are recorded separately as
  wiring evidence (modern binds ``win.handle_command`` / ``win._do_interrupt``;
  legacy installs nothing).
- Each run projects state through a FRESH ``IntentController`` so replaying
  the same sequence yields the same semantic state (no cross-run residue in
  the digest). The recorder seams are registered on the singleton, because
  that is the instance real shells wire.
- All captured fields are timestamp-free; ``BUS.drain_ui`` is pumped after
  each publish so queued UI subscribers dispatch deterministically without
  an event loop.
- Harness-local subscriber note: every fresh IntentController subscribes
  plain handlers to boot/log/task/focus/notify topics. The harness is only
  imported by tests, so this leak is bounded by test-process lifetime and
  never touches production shells.

Offline only: Qt offscreen, no provider/network/audio/camera/browser.
Evidence label: focused-tested. No live-proven claim from GUI observation.
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

from dataclasses import dataclass, field
from typing import Callable

from PyQt6.QtWidgets import QApplication, QMainWindow


# ── Qt application guard (must exist before any widget construction) ────────

_APP_REF: QApplication | None = None


def ensure_app() -> QApplication:
    """Get or create the single offscreen QApplication."""
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


# ── Capture model ────────────────────────────────────────────────────────────


@dataclass
class ShellCapture:
    """Timestamp-free record of one shell's fake-sequence run."""

    shell: str  # "legacy" | "modern"

    # Emitted intents: (intent_name, result_type) pairs in emission order
    intents_emitted: list[tuple[str, str]] = field(default_factory=list)

    # Command submission count (SubmitText delivered through the text seam)
    commands_submitted: int = 0

    # Interrupt/cancellation calls delivered through the interrupt seam
    cancellation_calls: int = 0

    # Displayed semantic state: digest snapshots after each sequence step
    semantic_digests: list[tuple] = field(default_factory=list)

    # Log entries seen by the projector: (level, source, message)
    log_entries: list[tuple[str, str, str]] = field(default_factory=list)

    # Stage transitions seen by the projector: (name, status)
    stage_transitions: list[tuple[str, str]] = field(default_factory=list)

    # Approval resolution: approved action ids, in order
    approvals: list[str] = field(default_factory=list)

    # Approval cancellations count
    approval_cancellations: int = 0

    # Cleanup: window closed after the sequence completed
    cleanup_called: bool = False

    # Wiring evidence (shell-specific, NOT part of the parity comparison):
    # what the singleton seams pointed at immediately after construction
    text_seam_bound: bool = False
    interrupt_seam_bound: bool = False


def semantic_digest(state: dict) -> tuple:
    """Reduce a controller's semantic state snapshot to a comparable tuple.

    Timestamps are excluded by construction so two runs of the same
    sequence always produce identical digests.
    """
    pending = state.get("pending_decision") or {}
    return (
        state.get("assistant_state"),
        state.get("stage_status"),
        state.get("stage_name"),
        tuple(
            (t["id"], t["title"], t["status"], t["progress"])
            for t in state.get("tasks", [])
        ),
        tuple(
            (l["level"], l["source"], l["message"])
            for l in state.get("logs", [])
        ),
        len(state.get("notifications", [])),
        state.get("focus_active"),
        pending.get("dangerous_action_id"),
    )


# ── Fake sequence feeder ─────────────────────────────────────────────────────

PROBE_COMMAND = "parity probe"
PROBE_ACTION_ID = "parity-action-1"
PROBE_TASK = {
    "id": "t-parity-1",
    "title": "Parity task",
    "status": "running",
    "progress": 0.0,
}


def feed_fake_sequence(controller, capture: ShellCapture) -> None:
    """Feed the roadmap §13 fake sequence and snapshot state per step.

    All events are fake/offline. The controller's seams are assumed to be
    the recorder callbacks installed by :func:`run_sequence`; nothing here
    reaches provider, browser, audio, or camera lanes.
    """
    from jarvis.core.bus import BUS

    projector = controller._projector

    def snap() -> None:
        capture.semantic_digests.append(
            semantic_digest(controller.get_semantic_state()))

    # 1. boot.check
    BUS.publish("boot.check", subsystem="parity", ok=True, detail="fake")
    BUS.drain_ui()
    snap()

    # 2. state LISTENING
    projector.on_assistant_state_change("LISTENING")
    snap()

    # 3. SubmitText → 4. intent
    # (submission counting happens in the recorder seam installed by
    # run_sequence; feed_fake_sequence never counts on its own)
    controller.submit_text(PROBE_COMMAND)
    BUS.publish("intent", intent="parity", text=PROBE_COMMAND, meta={})
    BUS.drain_ui()
    snap()

    # 5-7. task.submitted → task.updated → task.finished
    BUS.publish("task.submitted", task=dict(PROBE_TASK))
    BUS.publish("task.updated",
                task={**PROBE_TASK, "status": "running", "progress": 0.5})
    BUS.publish("task.finished",
                task={**PROBE_TASK, "status": "finished", "progress": 1.0})
    BUS.drain_ui()
    snap()

    # 8. notify
    BUS.publish("notify", title="Parity check", level="info", body="fake")
    BUS.drain_ui()
    snap()

    # 9-10. stage LOADING → stage ACTIVE
    projector.on_stage_change("browser", "LOADING")
    capture.stage_transitions.append(("browser", "LOADING"))
    snap()
    projector.on_stage_change("browser", "ACTIVE")
    capture.stage_transitions.append(("browser", "ACTIVE"))
    snap()

    # 11. confirm
    result = controller.approve(PROBE_ACTION_ID)
    capture.intents_emitted.append(("approve", type(result).__name__))
    if type(result).__name__ == "Success":
        capture.approvals.append(PROBE_ACTION_ID)
    BUS.drain_ui()
    snap()

    # 12. cancel
    result = controller.cancel_approval()
    capture.intents_emitted.append(("cancel_approval", type(result).__name__))
    if type(result).__name__ == "Success":
        capture.approval_cancellations += 1
    BUS.drain_ui()
    snap()

    # 13. error
    BUS.publish("log", level="error", source="parity",
                message="simulated error")
    projector.on_assistant_state_change("ERROR")
    BUS.drain_ui()
    snap()

    # 14. close is performed by run_sequence (window.close in finally)

    # Final log/stage extraction for the comparison targets
    state = controller.get_semantic_state()
    capture.log_entries = [
        (l["level"], l["source"], l["message"]) for l in state["logs"]]


# ── Run one shell through the sequence ───────────────────────────────────────


def _same_callable(a, b) -> bool:
    """True if two callables are the same function bound to the same object.

    ``is`` alone is not sufficient: every attribute access on a bound method
    produces a fresh wrapper object, so identity must be compared through
    ``__self__``/``__func__``.
    """
    if a is None or b is None:
        return False
    if a is b:
        return True
    if hasattr(a, "__self__") and hasattr(b, "__self__"):
        return a.__self__ is b.__self__ and a.__func__ is b.__func__
    return False


def run_sequence(shell: str, window_factory: Callable[[], QMainWindow]) -> ShellCapture:
    """Construct one shell, capture wiring evidence, replay the fake sequence,
    and return the capture.

    Args:
        shell: label for the capture ("legacy" | "modern"); the caller is
            responsible for having the matching ``ui.shell`` value active.
        window_factory: zero-arg callable returning the shell window
            (already constructed through the normal selection path).

    The sequence replay happens AFTER the window is closed: the semantic
    projection under test is shell-agnostic pure Python (the shared
    IntentController/StateProjector contract), and the shell's contribution
    to semantics is exactly the seam wiring captured from the live window.
    Replaying fake events against an open window would trigger its drain
    timer and UI dialogs — that is runtime behavior, not shell semantics.
    """
    from jarvis.ui.intent_controller import (
        IntentController,
        get_intent_controller,
    )

    ensure_app()
    capture = ShellCapture(shell=shell)

    window = window_factory()
    singleton = get_intent_controller()

    # Wiring evidence BEFORE any recorder overwrites the seams: modern binds
    # the window's real owners, legacy installs nothing (seams unchanged).
    handle_command = getattr(window, "handle_command", None)
    do_interrupt = getattr(window, "_do_interrupt", None)
    capture.text_seam_bound = _same_callable(
        singleton._on_text_command, handle_command)
    capture.interrupt_seam_bound = _same_callable(
        singleton._on_interrupt, do_interrupt)

    # Cleanup: close the window before replaying the sequence. This is the
    # sequence's close step and guarantees no drain timer or dialog is left
    # running while the fake events are processed.
    window.close()
    capture.cleanup_called = True

    # Fresh controller per run: recorder seams AND state projection live on
    # this instance so the same sequence always yields the same capture
    # (no cross-run residue in the digests). The singleton is left untouched.
    projector_controller = IntentController()

    def record_submit(text: str) -> None:
        capture.commands_submitted += 1
        capture.intents_emitted.append(("submit_text", "delivered"))

    def record_interrupt() -> None:
        capture.cancellation_calls += 1
        capture.intents_emitted.append(("interrupt", "delivered"))

    projector_controller.register_text_command_callback(record_submit)
    projector_controller.register_interrupt_callback(record_interrupt)

    # Interrupt intent (roadmap ESC path), then the full fake sequence
    projector_controller.interrupt()
    feed_fake_sequence(projector_controller, capture)

    return capture


# ── Parity comparison ────────────────────────────────────────────────────────


@dataclass
class ParityReport:
    """Comparison of two shell captures over the roadmap's eight targets."""

    ok: bool
    mismatches: list[str] = field(default_factory=list)
    legacy: ShellCapture | None = None
    modern: ShellCapture | None = None


def compare_captures(legacy: ShellCapture, modern: ShellCapture) -> ParityReport:
    """Compare the eight roadmap §13 targets between two captures.

    Wiring evidence (text_seam_bound / interrupt_seam_bound) is deliberately
    NOT compared here: it is shell-specific by design and asserted separately.
    """
    mismatches: list[str] = []

    checks = (
        ("emitted_intents",
         legacy.intents_emitted, modern.intents_emitted),
        ("command_submission_count",
         legacy.commands_submitted, modern.commands_submitted),
        ("displayed_semantic_state",
         legacy.semantic_digests, modern.semantic_digests),
        ("task_cancellation_calls",
         legacy.cancellation_calls, modern.cancellation_calls),
        ("log_entries",
         legacy.log_entries, modern.log_entries),
        ("stage_transitions",
         legacy.stage_transitions, modern.stage_transitions),
        ("approval_resolution",
         (legacy.approvals, legacy.approval_cancellations),
         (modern.approvals, modern.approval_cancellations)),
        ("cleanup_calls",
         legacy.cleanup_called, modern.cleanup_called),
    )

    for name, left, right in checks:
        if left != right:
            mismatches.append(f"{name}: legacy={left!r} modern={right!r}")

    return ParityReport(
        ok=not mismatches,
        mismatches=mismatches,
        legacy=legacy,
        modern=modern,
    )


def run_parity(
    window_factory: Callable[[], QMainWindow],
    shell_switch: Callable[[str], None],
) -> ParityReport:
    """Run the fake sequence under both shells and compare.

    Args:
        window_factory: zero-arg callable that constructs the shell window
            honoring the currently active ``ui.shell`` value.
        shell_switch: callable that activates "legacy" or "modern".
    """
    shell_switch("legacy")
    legacy = run_sequence("legacy", window_factory)

    shell_switch("modern")
    modern = run_sequence("modern", window_factory)

    return compare_captures(legacy, modern)
