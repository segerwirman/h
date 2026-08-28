"""Live Comment Assistant — platform-agnostic, fail-closed core.

Adapters own network I/O. ``CommentManager`` owns bounded collection, explicit
per-session auto activation, per-platform rate/cooldown gates, retries, kill
switches, and audit metadata. Reply text classification lives in the pure
``deterministic_reply`` module.
"""
from __future__ import annotations

import json
import math
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

from jarvis.core import config, log
from jarvis.core.focus_mode import FocusMode

_logger = log.get("comments.manager")


class ReplyMode(str, Enum):
    DRAFT = "draft"
    AUTO = "auto"


@dataclass
class CommentEvent:
    platform: str
    comment_id: str
    author_id: str
    author_name: str
    text: str
    timestamp: float
    stream_id: str = ""
    dedup_id: str = ""
    is_question: bool = False
    is_mention: bool = False
    is_moderator: bool = False
    is_paid: bool = False
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.dedup_id:
            self.dedup_id = f"{self.platform}:{self.comment_id}"


@dataclass
class ReplyResult:
    ok: bool
    detail: str = ""
    reply_id: str = ""
    retryable: bool = False


@dataclass
class PlatformCapabilities:
    """Honest capability report for the currently configured account."""

    can_read: bool
    can_reply: bool
    requires_manual_approval: bool
    notes: str = ""


class PlatformAdapter:
    """Base platform contract; subclasses own any network I/O."""

    name = "base"

    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(False, False, True, "not implemented")

    def is_authenticated(self) -> bool:
        return False

    def poll_comments(self) -> list[CommentEvent]:
        return []

    def send_reply(self, comment: CommentEvent, text: str) -> ReplyResult:
        return ReplyResult(False, "platform adapter does not support replying")

    def connection_health(self) -> dict:
        return {"platform": self.name, "connected": False, "detail": "not implemented"}


class Deduplicator:
    def __init__(self, window_s: float, *, clock=time.time):
        self._window_s = window_s
        self._clock = clock
        self._seen: dict[str, float] = {}
        self._lock = threading.RLock()

    def seen_before(self, dedup_id: str) -> bool:
        now = self._clock()
        with self._lock:
            self._evict(now)
            if dedup_id in self._seen:
                return True
            self._seen[dedup_id] = now
            return False

    def _evict(self, now: float) -> None:
        cutoff = now - self._window_s
        stale = [key for key, timestamp in self._seen.items() if timestamp < cutoff]
        for key in stale:
            del self._seen[key]


class RateLimiter:
    """Injected-clock token bucket; one instance scopes one platform."""

    def __init__(self, max_per_min: float, *, clock=time.monotonic):
        self._max = max(0.001, float(max_per_min))
        self._clock = clock
        self._tokens = self._max
        self._last = self._clock()
        self._lock = threading.RLock()

    def allow(self) -> bool:
        with self._lock:
            now = self._clock()
            elapsed = max(0.0, now - self._last)
            self._last = now
            self._tokens = min(
                self._max,
                self._tokens + elapsed * (self._max / 60.0),
            )
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False


class RetryPolicy:
    def __init__(self, max_attempts: int, base_delay_s: float, max_delay_s: float):
        self.max_attempts = max(1, min(10, int(max_attempts)))
        self._base = max(0.0, float(base_delay_s))
        self._cap = max(self._base, float(max_delay_s))

    def next_delay(self, attempt: int) -> float:
        return min(self._cap, self._base * (2 ** max(0, int(attempt) - 1)))


_SPAM_MARKERS = ("http://bit.ly", "free followers", "click here now", "www.free-")


class ModerationFilter:
    def is_safe(self, text: str) -> bool:
        low = text.lower()
        return not any(marker in low for marker in _SPAM_MARKERS) and len(text) <= 2000


class AuditLog:
    def __init__(self, path_rel: str = "logs/comments_audit.jsonl", *, clock=time.time):
        self._path = config.resolve_path(path_rel)
        self._clock = clock

    def record(self, **fields) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fields.setdefault("ts", self._clock())
            with open(self._path, "a", encoding="utf-8") as file:
                file.write(json.dumps(fields) + "\n")
        except OSError as exc:
            _logger.warning("comments.audit_write_failed", error=type(exc).__name__)


class CommentManager:
    """Own bounded collection and safe reply lifecycle for platform adapters."""

    def __init__(
        self,
        adapters: list[PlatformAdapter] | None = None,
        *,
        clock=time.monotonic,
        sleeper=time.sleep,
        audit=None,
        activation_ttl_s: float | None = None,
        max_replies_per_min: float | None = None,
        author_cooldown_s: float | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        section = config.section("live_comments")
        self.adapters: list[PlatformAdapter] = adapters or []
        self._clock = clock
        self._sleeper = sleeper
        self._lock = threading.RLock()
        self._queue_max = max(1, int(section.get("queue_max", 500)))
        self._read_queue: "queue.Queue[CommentEvent]" = queue.Queue(
            maxsize=self._queue_max,
        )
        self._dedup = Deduplicator(
            float(section.get("dedup_window_s", 120)),
            clock=clock,
        )
        self._moderation = ModerationFilter()
        rate_config = section.get("rate_limit", {}) or {}
        self._max_replies_per_min = _bounded_positive(
            max_replies_per_min
            if max_replies_per_min is not None
            else rate_config.get("max_replies_per_min", 3),
            default=3.0,
            maximum=120.0,
        )
        self._author_cooldown_s = _bounded_non_negative(
            author_cooldown_s
            if author_cooldown_s is not None
            else rate_config.get("author_cooldown_s", 30),
            default=30.0,
            maximum=86400.0,
        )
        self._activation_ttl_s = _bounded_positive(
            activation_ttl_s
            if activation_ttl_s is not None
            else section.get("auto_activation_ttl_s", 900),
            default=900.0,
            maximum=3600.0,
        )
        retry_config = section.get("retry", {}) or {}
        self._retry = retry_policy or RetryPolicy(
            int(retry_config.get("max_attempts", 5)),
            float(retry_config.get("base_delay_s", 1.0)),
            float(retry_config.get("max_delay_s", 60.0)),
        )
        self._audit = audit or AuditLog()
        self._reply_mode = {adapter.name: ReplyMode.DRAFT for adapter in self.adapters}
        self._activation_expires: dict[str, float] = {}
        self._rate_limiters: dict[str, RateLimiter] = {}
        self._author_last_reply: dict[tuple[str, str], float] = {}
        self._global_killed = False
        self._platform_killed: set[str] = set()
        self._paused = False

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def enable_auto_reply(self, platform: str, *, ttl_s: float | None = None) -> bool:
        target = str(platform or "").strip()
        adapter = self._adapter(target)
        if not target or adapter is None or self._killed(target):
            return False
        ttl = _bounded_positive(
            self._activation_ttl_s if ttl_s is None else ttl_s,
            default=self._activation_ttl_s,
            maximum=3600.0,
        )
        with self._lock:
            self._reply_mode[target] = ReplyMode.AUTO
            self._activation_expires[target] = self._clock() + ttl
        self._audit.record(
            event="auto_reply_enabled",
            platform=target,
            expires_in_s=ttl,
        )
        return True

    def disable_auto_reply(self, platform: str, *, reason: str = "disabled") -> None:
        target = str(platform or "").strip()
        with self._lock:
            self._reply_mode[target] = ReplyMode.DRAFT
            self._activation_expires.pop(target, None)
        self._audit.record(event="auto_reply_disabled", platform=target, reason=reason[:64])

    def reply_mode(self, platform: str) -> ReplyMode:
        target = str(platform or "").strip()
        with self._lock:
            mode = self._reply_mode.get(target, ReplyMode.DRAFT)
            expires_at = self._activation_expires.get(target, 0.0)
            expired = mode is ReplyMode.AUTO and self._clock() >= expires_at
            if expired:
                self._reply_mode[target] = ReplyMode.DRAFT
                self._activation_expires.pop(target, None)
                mode = ReplyMode.DRAFT
        if expired:
            self._audit.record(event="auto_reply_expired", platform=target)
        return mode

    def set_global_kill_switch(self, enabled: bool = True) -> None:
        with self._lock:
            self._global_killed = bool(enabled)
            if enabled:
                self._activation_expires.clear()
                for platform in tuple(self._reply_mode):
                    self._reply_mode[platform] = ReplyMode.DRAFT
        self._audit.record(event="reply_global_kill_switch", enabled=bool(enabled))

    def set_platform_kill_switch(self, platform: str, enabled: bool = True) -> None:
        target = str(platform or "").strip()
        with self._lock:
            if enabled:
                self._platform_killed.add(target)
                self._activation_expires.pop(target, None)
                self._reply_mode[target] = ReplyMode.DRAFT
            else:
                self._platform_killed.discard(target)
        self._audit.record(
            event="reply_platform_kill_switch",
            platform=target,
            enabled=bool(enabled),
        )

    def poll_once(self) -> list[CommentEvent]:
        accepted: list[CommentEvent] = []
        for adapter in self.adapters:
            capabilities = adapter.capabilities()
            if not capabilities.can_read:
                continue
            try:
                events = adapter.poll_comments()
            except Exception as exc:
                _logger.warning(
                    "comments.poll_failed",
                    platform=adapter.name,
                    error=type(exc).__name__,
                )
                continue
            for event in events:
                if self._dedup.seen_before(event.dedup_id):
                    continue
                if not self._moderation.is_safe(event.text):
                    self._audit.record(
                        event="moderation_blocked",
                        platform=event.platform,
                        comment_id=event.comment_id,
                    )
                    continue
                if self._read_queue.full():
                    try:
                        self._read_queue.get_nowait()
                    except queue.Empty:
                        _logger.warning("comments.queue_drop_raced")
                self._read_queue.put_nowait(event)
                accepted.append(event)
        return accepted

    def next_for_narration(self) -> CommentEvent | None:
        if self._paused or not FocusMode.get().should_narrate_comments():
            return None
        try:
            return self._read_queue.get_nowait()
        except queue.Empty:
            return None

    def queue_depth(self) -> int:
        return self._read_queue.qsize()

    def reply(self, comment: CommentEvent, text: str, confirmed: bool = False) -> ReplyResult:
        adapter = self._adapter(comment.platform)
        if adapter is None:
            return ReplyResult(False, f"no adapter registered for {comment.platform}")
        if self._killed(comment.platform):
            self._audit.record(
                event="reply_killed",
                platform=comment.platform,
                comment_id=comment.comment_id,
            )
            return ReplyResult(False, "reply kill switch active")
        capabilities = adapter.capabilities()
        if not capabilities.can_reply:
            self._audit.record(
                event="reply_unsupported",
                platform=comment.platform,
                comment_id=comment.comment_id,
            )
            return ReplyResult(
                False,
                f"{comment.platform} reply not supported: {capabilities.notes}",
            )
        if capabilities.requires_manual_approval and not confirmed:
            self._audit.record(
                event="reply_manual_required",
                platform=comment.platform,
                comment_id=comment.comment_id,
            )
            return ReplyResult(False, "manual approval required — draft only")
        mode = self.reply_mode(comment.platform)
        if mode is ReplyMode.DRAFT and not confirmed:
            self._audit.record(
                event="reply_drafted",
                platform=comment.platform,
                comment_id=comment.comment_id,
            )
            return ReplyResult(False, "draft-only mode — awaiting explicit send confirmation")
        if not confirmed:
            gate = self._auto_gate(comment)
            if gate is not None:
                return gate

        last_error = ""
        for attempt in range(1, self._retry.max_attempts + 1):
            if attempt > 1:
                safety_block = self._retry_safety_gate(comment, adapter, confirmed)
                if safety_block is not None:
                    return safety_block
            try:
                result = adapter.send_reply(comment, text)
            except Exception as exc:
                result = ReplyResult(False, type(exc).__name__)
            if result.ok:
                if not confirmed:
                    with self._lock:
                        self._author_last_reply[
                            (comment.platform, comment.author_id)
                        ] = self._clock()
                self._audit.record(
                    event="reply_sent",
                    platform=comment.platform,
                    comment_id=comment.comment_id,
                    attempt=attempt,
                )
                return result
            last_error = str(result.detail or "")[:200]
            if not result.retryable or attempt >= self._retry.max_attempts:
                break
            self._sleeper(self._retry.next_delay(attempt))
        self._audit.record(
            event="reply_failed",
            platform=comment.platform,
            comment_id=comment.comment_id,
            detail=last_error,
        )
        return ReplyResult(False, last_error or "retries exhausted")

    def connection_health(self) -> dict:
        return {adapter.name: adapter.connection_health() for adapter in self.adapters}

    def _adapter(self, platform: str) -> PlatformAdapter | None:
        return next((adapter for adapter in self.adapters if adapter.name == platform), None)

    def _killed(self, platform: str) -> bool:
        with self._lock:
            return self._global_killed or platform in self._platform_killed

    def _retry_safety_gate(
        self,
        comment: CommentEvent,
        adapter: PlatformAdapter,
        confirmed: bool,
    ) -> ReplyResult | None:
        if self._killed(comment.platform):
            self._audit.record(
                event="reply_retry_killed",
                platform=comment.platform,
                comment_id=comment.comment_id,
            )
            return ReplyResult(False, "reply kill switch active")
        capabilities = adapter.capabilities()
        if not capabilities.can_reply:
            return ReplyResult(False, f"reply no longer supported: {capabilities.notes}")
        if capabilities.requires_manual_approval and not confirmed:
            return ReplyResult(False, "manual approval required — retry stopped")
        if not confirmed and self.reply_mode(comment.platform) is not ReplyMode.AUTO:
            return ReplyResult(False, "auto activation expired — retry stopped")
        return None

    def _auto_gate(self, comment: CommentEvent) -> ReplyResult | None:
        now = self._clock()
        key = (comment.platform, comment.author_id)
        with self._lock:
            previous = self._author_last_reply.get(key)
            if previous is not None and now - previous < self._author_cooldown_s:
                blocked_by = "cooldown"
            else:
                limiter = self._rate_limiters.get(comment.platform)
                if limiter is None:
                    limiter = RateLimiter(
                        self._max_replies_per_min,
                        clock=self._clock,
                    )
                    self._rate_limiters[comment.platform] = limiter
                blocked_by = "" if limiter.allow() else "rate_limit"
        if blocked_by == "cooldown":
            self._audit.record(
                event="reply_author_cooldown",
                platform=comment.platform,
                comment_id=comment.comment_id,
            )
            return ReplyResult(False, "author cooldown active")
        if blocked_by == "rate_limit":
            self._audit.record(
                event="reply_rate_limited",
                platform=comment.platform,
                comment_id=comment.comment_id,
            )
            return ReplyResult(False, "rate limit exceeded")
        return None


def _bounded_positive(value, *, default: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if not math.isfinite(result) or result <= 0:
        result = default
    return min(maximum, result)


def _bounded_non_negative(value, *, default: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if not math.isfinite(result) or result < 0:
        result = default
    return min(maximum, result)
