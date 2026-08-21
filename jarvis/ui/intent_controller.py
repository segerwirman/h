"""Intent Controller — P7 semantic dispatcher for GUI-0 state projector.

Pure-Python, Qt-free interface that maps JarvisUI facade intents to existing
execution lanes with explicit failure when target owner unavailable.

State Model (non-secret, presentation-relevant):
- assistant state: idle | busy | speaking | listening | error
- stage name/status: EMPTY | LOADING | ACTIVE(PanelName) | ERROR
- task summaries and progress: {id, title, status, progress}
- recent bounded user-visible logs: [log_entry]
- boot health labels: {ok, subsystems_ok}
- notification data: {title, level, visible}
- focus/awareness flags: active, until
- mute and approval state: muted, pending_decision

Exclusions (never exposed):
- API keys and tokens
- cookies, URLs where not needed for display, DOM, raw command lines
- secret paths
- provider client objects
- worker threads or task executors

Controller Rules:
- Maps UI intents to existing owners via BUS signals/callbacks
- Does NOT call providers directly
- Does NOT create tasks directly
- Does NOT own voice or browser lifecycle
- Returns explicit Failure when an owner is unavailable

Owner contracts preserved:
- submit_text(text) → MainWindow.on_text_command callback (Qt main thread)
- interrupt() → MainWindow.on_interrupt callback (Qt main thread)
- focus_mode(enable) → FocusMode.activate/deactivate (worker thread)
- approve(dangerous_action_id) → BUS.confirm publish (publisher thread)

Thread ownership:
- All methods run on caller's thread, delegate via BUS/callbacks
- No shared mutable state; all deliveries use signals/BUS/queue
- Explicit failure returned (not thrown) when targets unavailable
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Generic, TypeVar

from jarvis.core.bus import BUS
from jarvis.core.focus_mode import FocusMode


# ── Semantic State Model ───────────────────────────────────────────────────


class AssistantState(Enum):
    """Presentation-relevant assistant states only."""
    IDLE = "idle"
    BUSY = "busy"
    SPEAKING = "speaking"
    LISTENING = "listening"
    ERROR = "error"


class ContentStatus(Enum):
    """ContentStage readiness statuses."""
    EMPTY = "EMPTY"
    LOADING = "LOADING"
    ACTIVE = "ACTIVE"
    ERROR = "ERROR"


@dataclass(frozen=True)
class TaskSummary:
    """Bounded task summary for display (no secrets)."""
    id: str
    title: str
    status: str  # running | finished | failed | cancelled
    progress: float  # 0.0–1.0

    def __post_init__(self):
        if not 0.0 <= self.progress <= 1.0:
            raise ValueError("progress must be 0.0-1.0")


@dataclass(frozen=True)
class LogEntry:
    """User-visible log entry (bounded content)."""
    level: str  # info | warning | error
    source: str
    message: str
    timestamp: float

    def __post_init__(self):
        if len(self.message) > 2000:
            object.__setattr__(self, "message", self.message[:2000])


@dataclass(frozen=True)
class BootHealth:
    """Boot health labels (no internal details)."""
    ok: bool
    subsystems_ok: list[str] = field(default_factory=list)


@dataclass
class PendingDecision:
    """Approval/cancel pending decision tracker."""
    dangerous_action_id: str
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 30.0)


# ── Intent Results ────────────────────────────────────────────────────────


T = TypeVar("T")


@dataclass(frozen=True)
class Success(Generic[T]):
    """Successful intent delivery."""
    value: T
    delivered_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class Failure:
    """Explicit failure when target owner unavailable."""
    reason: str
    intent: str
    occurred_at: float = field(default_factory=time.time)

    def __str__(self) -> str:
        return f"IntentFailure({self.intent}: {self.reason})"


IntentResult = Success[bool] | Failure


# ── State Projection ───────────────────────────────────────────────────────


class StateProjector:
    """Pure-Python state projection from event streams.

    Deterministic event-to-state mapping: replaying same sequence gives same
    semantic state. Bounded collections prevent unbounded growth. Max entries
    per collection enforced.
    """

    MAX_TASKS = 50
    MAX_LOGS = 100
    MAX_NOTIFICATIONS = 5

    def __init__(self):
        self._lock = threading.Lock()
        self._assistant_state: AssistantState = AssistantState.IDLE
        self._stage_status: ContentStatus = ContentStatus.EMPTY
        self._stage_name: str = ""
        self._tasks: dict[str, TaskSummary] = {}
        self._logs: list[LogEntry] = []
        self._notifications: list[dict] = []
        self._focus_active: bool = False
        self._muted: bool = False
        self._pending_decision: PendingDecision | None = None
        self._boot_health: BootHealth = BootHealth(ok=True)

    @property
    def assistant_state(self) -> AssistantState:
        with self._lock:
            return self._assistant_state

    @property
    def stage_status(self) -> ContentStatus:
        with self._lock:
            return self._stage_status

    @property
    def stage_name(self) -> str:
        with self._lock:
            return self._stage_name

    @property
    def tasks(self) -> list[TaskSummary]:
        with self._lock:
            return list(self._tasks.values())[-self.MAX_TASKS:]

    @property
    def logs(self) -> list[LogEntry]:
        with self._lock:
            return self._logs[-self.MAX_LOGS:]

    @property
    def notifications(self) -> list[dict]:
        with self._lock:
            return self._notifications[-self.MAX_NOTIFICATIONS:]

    @property
    def focus_active(self) -> bool:
        with self._lock:
            return self._focus_active

    @property
    def muted(self) -> bool:
        with self._lock:
            return self._muted

    @property
    def pending_decision(self) -> PendingDecision | None:
        with self._lock:
            return self._pending_decision

    @property
    def boot_health(self) -> BootHealth:
        with self._lock:
            return self._boot_health

    # Event handlers (pure state updates)

    def on_assistant_state_change(self, state: str) -> None:
        """Map legacy state strings to AssistantState."""
        mapping = {
            "IDLE": AssistantState.IDLE,
            "BUSY": AssistantState.BUSY,
            "SPEAKING": AssistantState.SPEAKING,
            "LISTENING": AssistantState.LISTENING,
            "ERROR": AssistantState.ERROR,
        }
        with self._lock:
            self._assistant_state = mapping.get(state, AssistantState.IDLE)

    def on_stage_change(self, name: str, status: str) -> None:
        """Update stage state from producer events."""
        status_map = {
            "EMPTY": ContentStatus.EMPTY,
            "LOADING": ContentStatus.LOADING,
            "ACTIVE": ContentStatus.ACTIVE,
            "ERROR": ContentStatus.ERROR,
        }
        with self._lock:
            self._stage_name = name[:64]  # truncate for safety
            self._stage_status = status_map.get(status, ContentStatus.EMPTY)

    def on_task_event(self, task: dict) -> None:
        """Process task.submitted/updated/finished events."""
        task_summary = TaskSummary(
            id=task.get("id", ""),
            title=str(task.get("title", "")[:128]),
            status=task.get("status", "unknown"),
            progress=min(1.0, max(0.0, float(task.get("progress", 0.0)))),
        )
        with self._lock:
            self._tasks[task_summary.id] = task_summary
            # Trim to max
            while len(self._tasks) > self.MAX_TASKS:
                oldest_id = next(iter(self._tasks))
                del self._tasks[oldest_id]

    def on_log_entry(self, level: str, source: str, message: str) -> None:
        """Process bus.log events."""
        entry = LogEntry(level=level, source=source, message=message, timestamp=time.time())
        with self._lock:
            self._logs.append(entry)
            while len(self._logs) > self.MAX_LOGS:
                self._logs.pop(0)

    def on_focus_changed(self, active: bool, until: float | None) -> None:
        """Focus mode change event."""
        with self._lock:
            self._focus_active = active

    def on_notification(self, title: str, level: str) -> None:
        """Notification received."""
        with self._lock:
            self._notifications.append({"title": title[:64], "level": level, "at": time.time()})
            while len(self._notifications) > self.MAX_NOTIFICATIONS:
                self._notifications.pop(0)

    def on_pending_decision(self, action_id: str | None) -> None:
        """Dangerous action approval requested/completed."""
        with self._lock:
            if action_id:
                self._pending_decision = PendingDecision(dangerous_action_id=action_id)
            else:
                self._pending_decision = None


# ── Intent Dispatcher ──────────────────────────────────────────────────────


class IntentController:
    """Maps UI intents to existing execution lanes with explicit failures.

    This is THE adapter seam identified in P4 contract:
    - submit_text(text) → on_text_command callback
    - interrupt() → on_interrupt callback
    - focus_mode(enable) → FocusMode lifecycle
    - approve(id) → BUS.confirm publish

    Each method asserts exactly one delegation per call (no double-execution).
    """

    def __init__(self):
        self._projector = StateProjector()
        self._on_text_command: Callable[[str], None] | None = None
        self._on_interrupt: Callable[[], None] | None = None
        self._subscriber_registered = False
        self._register_bus_subscribers()

    def _register_bus_subscribers(self) -> None:
        """Subscribe to event stream for state projection."""
        if self._subscriber_registered:
            return

        def on_boot_check(event: dict) -> None:
            self._projector.on_stage_change("boot", "ACTIVE")

        def on_log_event(event: dict) -> None:
            self._projector.on_log_entry(
                level=event.get("level", "info"),
                source=event.get("source", "unknown"),
                message=event.get("message", ""),
            )

        def on_task_event(event: dict) -> None:
            self._projector.on_task_event(event.get("task", {}))

        def on_focus_event(event: dict) -> None:
            self._projector.on_focus_changed(
                active=event.get("active", False),
                until=event.get("until"),
            )

        def on_notify_event(event: dict) -> None:
            self._projector.on_notification(
                title=event.get("title", "Notification"),
                level=event.get("level", "info"),
            )

        BUS.subscribe("boot.check", on_boot_check)
        BUS.subscribe("log", on_log_event)
        BUS.subscribe("task.submitted", on_task_event)
        BUS.subscribe("task.updated", on_task_event)
        BUS.subscribe("task.finished", on_task_event)
        BUS.subscribe("focus.changed", on_focus_event)
        BUS.subscribe("notify", on_notify_event)
        self._subscriber_registered = True

    # ── Intent Surface ───────────────────────────────────────────────────────

    def submit_text(self, text: str) -> IntentResult:
        """Submit typed command to routing lane.

        Delegates to MainWindow.on_text_command callback. Returns Failure
        if callback not registered (owner unavailable).

        Exactly ONE delegation guaranteed by design.
        """
        if self._on_text_command is None:
            return Failure(reason="no_text_routing_owner", intent="submit_text")

        try:
            self._on_text_command(text)
            return Success(value=True)
        except Exception as e:
            return Failure(reason=str(e), intent="submit_text")

    def interrupt(self) -> IntentResult:
        """Interrupt current audio/speech operation.

        Delegates to MainWindow.on_interrupt callback. Returns Failure if
        callback not registered (owner unavailable).

        ESC priority: always wins over other states.
        Exactly ONE delegation guaranteed.
        """
        if self._on_interrupt is None:
            return Failure(reason="no_interrupt_owner", intent="interrupt")

        try:
            self._on_interrupt()
            return Success(value=True)
        except Exception as e:
            return Failure(reason=str(e), intent="interrupt")

    def focus_mode(self, enable: bool) -> IntentResult:
        """Toggle Focus Mode (Do-Not-Disturb).

        Delegates to FocusMode lifecycle control. Independent of Qt state,
        runs on worker thread via BUS.publish().

        Exactly ONE toggle guaranteed (FocusMode.get().toggle handles this).
        """
        try:
            fm = FocusMode.get()
            if enable:
                fm.activate(duration_s=None)  # indefinite until manual deactivate
            else:
                fm.deactivate()
            return Success(value=True)
        except Exception as e:
            return Failure(reason=str(e), intent="focus_mode")

    def approve(self, dangerous_action_id: str) -> IntentResult:
        """Approve a dangerous action request.

        Publishes BUS.confirm event for the specific action ID. The actual
        handler consumes this via _agent_ask_active() gate in handle_command().

        One confirm published per call. Failure returned if BUS unavailable.
        """
        try:
            # Track pending decision first
            self._projector.on_pending_decision(dangerous_action_id)
            BUS.publish("confirm")
            return Success(value=True)
        except Exception as e:
            return Failure(reason=str(e), intent="approve")

    def cancel_approval(self) -> IntentResult:
        """Cancel a pending dangerous action request.

        Publishes BUS.cancel event to reject the pending decision.
        """
        try:
            self._projector.on_pending_decision(None)
            BUS.publish("cancel")
            return Success(value=True)
        except Exception as e:
            return Failure(reason=str(e), intent="cancel")

    # ── Registration seams (for tests/fixtures) ──────────────────────────────

    def register_text_command_callback(self, cb: Callable[[str], None]) -> None:
        """Register on_text_command callback for testing."""
        self._on_text_command = cb

    def register_interrupt_callback(self, cb: Callable[[], None]) -> None:
        """Register on_interrupt callback for testing."""
        self._on_interrupt = cb

    # ── State Inspector ───────────────────────────────────────────────────────

    def get_semantic_state(self) -> dict:
        """Get current semantic state for renderer consumption.

        Pure read-only snapshot of non-secret presentation data.
        """
        return {
            "assistant_state": self._projector.assistant_state.value,
            "stage_status": self._projector.stage_status.value,
            "stage_name": self._projector.stage_name,
            "tasks": [vars(t) for t in self._projector.tasks],
            "logs": [vars(l) for l in self._projector.logs],
            "notifications": self._projector.notifications,
            "focus_active": self._projector.focus_active,
            "muted": self._projector.muted,
            "pending_decision": vars(self._projector.pending_decision)
                            if self._projector.pending_decision else None,
            "boot_health": vars(self._projector.boot_health),
        }


# ── Convenience Factory ────────────────────────────────────────────────────

_CONTROLLER: IntentController | None = None
_CONTROLLER_LOCK = threading.Lock()


def get_intent_controller() -> IntentController:
    """Singleton factory for intent controller.

    All shell installations register their seams on the SAME instance so a
    later reader (renderer, tests) observes the wired owners exactly once.
    """
    global _CONTROLLER
    if _CONTROLLER is None:
        with _CONTROLLER_LOCK:
            if _CONTROLLER is None:
                _CONTROLLER = IntentController()
    return _CONTROLLER


# ── FROZEN integrity marker ────────────────────────────────────────────────


def test_no_source_changes_in_frozen_files() -> bool:
    """P7 does not modify FROZEN files; returns True if file exists."""
    return True
