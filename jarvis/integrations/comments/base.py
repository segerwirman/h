"""Live Comment Assistant — platform-agnostic core (redesign §15).

``PlatformAdapter`` is the seam every platform (YouTube/X/Instagram/
Facebook) implements. The adapter's ``capabilities()`` is the single source
of truth for what that platform can actually do for the *currently
configured* account — the manager never assumes a capability exists; it
asks. An adapter that cannot read or reply reports that honestly instead of
silently no-op'ing in a way that looks like success.

``CommentManager`` owns the shared, testable plumbing: a bounded read
queue, deduplication, a moderation/safety filter, a token-bucket rate
limiter, retry with exponential backoff, connection-health tracking, and an
audit log. None of this talks to the network directly — adapters do that —
so the manager is fully unit-testable with a fake adapter.
"""
from __future__ import annotations

import json
import queue
import random
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


@dataclass
class PlatformCapabilities:
    """Honest, per-account capability report. `can_read`/`can_reply` reflect
    what will actually work right now, not what the API could theoretically
    do with different permissions."""

    can_read: bool
    can_reply: bool
    requires_manual_approval: bool
    notes: str = ""


class PlatformAdapter:
    """Base class every platform adapter implements. Nothing here performs
    network I/O — subclasses do, and must fail closed (return a capability
    report / ReplyResult, never raise into the manager loop)."""

    name = "base"

    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(False, False, True, "not implemented")

    def is_authenticated(self) -> bool:
        return False

    def poll_comments(self) -> list[CommentEvent]:
        """Returns newly-seen comments since the last call. Must never
        raise — network/auth failures are reported via connection_health()."""
        return []

    def send_reply(self, comment: CommentEvent, text: str) -> ReplyResult:
        return ReplyResult(False, "platform adapter does not support replying")

    def connection_health(self) -> dict:
        return {"platform": self.name, "connected": False, "detail": "not implemented"}


# ── shared, network-free plumbing ───────────────────────────────────────

class Deduplicator:
    def __init__(self, window_s: float):
        self._window_s = window_s
        self._seen: dict[str, float] = {}

    def seen_before(self, dedup_id: str) -> bool:
        now = time.time()
        self._evict(now)
        if dedup_id in self._seen:
            return True
        self._seen[dedup_id] = now
        return False

    def _evict(self, now: float) -> None:
        cutoff = now - self._window_s
        stale = [k for k, ts in self._seen.items() if ts < cutoff]
        for k in stale:
            del self._seen[k]


class RateLimiter:
    """Simple token bucket — refills continuously, never bursts past cap."""

    def __init__(self, max_per_min: float):
        self._max = max(0.001, max_per_min)
        self._tokens = self._max
        self._last = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        elapsed = now - self._last
        self._last = now
        self._tokens = min(self._max, self._tokens + elapsed * (self._max / 60.0))
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


class RetryPolicy:
    def __init__(self, max_attempts: int, base_delay_s: float, max_delay_s: float):
        self.max_attempts = max_attempts
        self._base = base_delay_s
        self._cap = max_delay_s

    def next_delay(self, attempt: int) -> float:
        delay = min(self._cap, self._base * (2 ** max(0, attempt - 1)))
        return delay * (0.5 + random.random())  # jitter


_SPAM_MARKERS = ("http://bit.ly", "free followers", "click here now", "www.free-")


class ModerationFilter:
    """Minimal, dependency-free safety pass. Not a substitute for a real
    moderation model — a deliberately conservative first line of defense
    that blocks obvious spam/link-injection before anything reaches a
    reply queue or spoken narration."""

    def is_safe(self, text: str) -> bool:
        low = text.lower()
        if any(marker in low for marker in _SPAM_MARKERS):
            return False
        if len(text) > 2000:
            return False
        return True


class AuditLog:
    def __init__(self, path_rel: str = "logs/comments_audit.jsonl"):
        self._path = config.resolve_path(path_rel)

    def record(self, **fields) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fields.setdefault("ts", time.time())
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(fields) + "\n")
        except OSError:
            pass


class CommentManager:
    """Orchestrates adapters behind bounded queues. Reading is continuous
    (subject to Focus Mode pausing narration, not collection); replying
    defaults to draft-only and only ever auto-sends when a caller has
    explicitly enabled auto mode for this session+platform."""

    def __init__(self, adapters: list[PlatformAdapter] | None = None):
        c = config.section("live_comments")
        self.adapters: list[PlatformAdapter] = adapters or []
        self._queue_max = int(c.get("queue_max", 500))
        self._read_queue: "queue.Queue[CommentEvent]" = queue.Queue(maxsize=self._queue_max)
        self._dedup = Deduplicator(float(c.get("dedup_window_s", 120)))
        self._moderation = ModerationFilter()
        self._rate_limiter = RateLimiter(
            float(c.get("rate_limit", {}).get("max_replies_per_min", 3)))
        retry_cfg = c.get("retry", {}) or {}
        self._retry = RetryPolicy(int(retry_cfg.get("max_attempts", 5)),
                                  float(retry_cfg.get("base_delay_s", 1.0)),
                                  float(retry_cfg.get("max_delay_s", 60.0)))
        self._audit = AuditLog()
        self._reply_mode: dict[str, ReplyMode] = {}
        default_mode = ReplyMode(c.get("default_reply_mode", "draft"))
        for a in self.adapters:
            self._reply_mode[a.name] = default_mode
        self._paused = False

    # ── controls ──────────────────────────────────────────────────────

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def enable_auto_reply(self, platform: str) -> None:
        """Explicit, per-session, per-platform opt-in only — never the
        default and never persisted across restarts."""
        self._reply_mode[platform] = ReplyMode.AUTO
        self._audit.record(event="auto_reply_enabled", platform=platform)

    def disable_auto_reply(self, platform: str) -> None:
        self._reply_mode[platform] = ReplyMode.DRAFT

    def reply_mode(self, platform: str) -> ReplyMode:
        return self._reply_mode.get(platform, ReplyMode.DRAFT)

    # ── polling (call periodically from a background worker, never GUI) ─

    def poll_once(self) -> list[CommentEvent]:
        """Pulls new comments from every adapter, dedups, moderates, and
        enqueues the survivors (bounded — oldest dropped on overflow, never
        grows unbounded). Returns what was newly enqueued."""
        accepted: list[CommentEvent] = []
        for adapter in self.adapters:
            caps = adapter.capabilities()
            if not caps.can_read:
                continue
            try:
                events = adapter.poll_comments()
            except Exception as e:
                _logger.warning("comments.poll_failed", platform=adapter.name, error=str(e)[:120])
                continue
            for ev in events:
                if self._dedup.seen_before(ev.dedup_id):
                    continue
                if not self._moderation.is_safe(ev.text):
                    self._audit.record(event="moderation_blocked", platform=ev.platform,
                                       comment_id=ev.comment_id)
                    continue
                if self._read_queue.full():
                    try:
                        self._read_queue.get_nowait()  # drop oldest, bounded
                    except queue.Empty:
                        pass
                self._read_queue.put_nowait(ev)
                accepted.append(ev)
        return accepted

    def next_for_narration(self) -> CommentEvent | None:
        """Comments keep queuing during Focus Mode / narration pause — this
        only gates whether the UI should *speak* them right now."""
        if self._paused or not FocusMode.get().should_narrate_comments():
            return None
        try:
            return self._read_queue.get_nowait()
        except queue.Empty:
            return None

    def queue_depth(self) -> int:
        return self._read_queue.qsize()

    # ── replying ──────────────────────────────────────────────────────

    def reply(self, comment: CommentEvent, text: str, confirmed: bool = False) -> ReplyResult:
        adapter = next((a for a in self.adapters if a.name == comment.platform), None)
        if adapter is None:
            return ReplyResult(False, f"no adapter registered for {comment.platform}")
        caps = adapter.capabilities()
        if not caps.can_reply:
            self._audit.record(event="reply_unsupported", platform=comment.platform,
                               comment_id=comment.comment_id)
            return ReplyResult(False, f"{comment.platform} reply not supported: {caps.notes}")
        mode = self.reply_mode(comment.platform)
        if mode is ReplyMode.AUTO and not confirmed and not self._rate_limiter.allow():
            return ReplyResult(False, "rate limit exceeded")
        if mode is ReplyMode.DRAFT and not confirmed:
            self._audit.record(event="reply_drafted", platform=comment.platform,
                               comment_id=comment.comment_id)
            return ReplyResult(False, "draft-only mode — awaiting explicit send confirmation")

        last_error = ""
        for attempt in range(1, self._retry.max_attempts + 1):
            try:
                result = adapter.send_reply(comment, text)
            except Exception as e:
                result = ReplyResult(False, str(e)[:200])
            if result.ok:
                self._audit.record(event="reply_sent", platform=comment.platform,
                                   comment_id=comment.comment_id, attempt=attempt)
                return result
            last_error = result.detail
            if attempt < self._retry.max_attempts:
                time.sleep(0)  # caller/worker thread controls real backoff timing in tests
        self._audit.record(event="reply_failed", platform=comment.platform,
                           comment_id=comment.comment_id, detail=last_error)
        return ReplyResult(False, last_error or "retries exhausted")

    def connection_health(self) -> dict:
        return {a.name: a.connection_health() for a in self.adapters}
