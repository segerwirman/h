"""Safe Gemini Live failure classification and reconnect state."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
from typing import Callable, Iterator

MAX_STATUS_LENGTH = 64
_INITIAL_BACKOFF_S = 3
_MAX_BACKOFF_S = 60
_STATUS_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_INVALID_KEY_MARKERS = (
    "api key not valid",
    "api_key_invalid",
    "invalid api key",
)
_NETWORK_MARKERS = (
    "timeout",
    "timed out",
    "getaddrinfo",
    "connectionrefused",
    "cannot connect",
    "connection reset",
    "connection closed",
    "socket closed",
    "dns",
)
_SESSION_MARKERS = (
    "websocket",
    "protocol",
    "invalid frame",
    "session expired",
    "session closed",
    "1007",
    "1008",
)
_SERVER_STATUSES = {
    "INTERNAL",
    "UNAVAILABLE",
    "DEADLINE_EXCEEDED",
    "RESOURCE_EXHAUSTED",
}
_SESSION_STATUSES = {
    "ABORTED",
    "CANCELLED",
    "FAILED_PRECONDITION",
    "OUT_OF_RANGE",
}


@dataclass(frozen=True)
class LiveFailure:
    kind: str
    leaf_type: str
    code: int | None = None
    status: str = ""
    auth_confirmed: bool = False

    def safe_fields(self) -> dict[str, object]:
        fields: dict[str, object] = {
            "kind": self.kind,
            "leaf_type": self.leaf_type,
        }
        if self.code is not None:
            fields["code"] = self.code
        if self.status:
            fields["status"] = self.status
        return fields


class ReconnectBackoff:
    """Escalate failures until an observable healthy session milestone."""

    def __init__(self) -> None:
        self._current = reset_backoff()
        self._has_failed = False

    @property
    def current(self) -> int:
        return self._current

    def connected(self) -> int:
        """WebSocket acceptance is not proof that the session is healthy."""
        return self._current

    def failed(self) -> int:
        if self._has_failed:
            self._current = next_backoff(self._current)
        self._has_failed = True
        return self._current

    def healthy(self) -> int:
        self._current = reset_backoff()
        self._has_failed = False
        return self._current


class ConnectionTracker:
    """Identify first connection and first healthy connect after failure."""

    def __init__(self) -> None:
        self._connected_once = False
        self._failed = False

    def connected(self) -> str:
        if not self._connected_once:
            self._connected_once = True
            self._failed = False
            return "initial"
        if self._failed:
            self._failed = False
            return "restored"
        return "connected"

    def failed(self) -> None:
        if self._connected_once:
            self._failed = True


def leaves(exc: BaseException) -> Iterator[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        for nested in exc.exceptions:
            yield from leaves(nested)
        return
    yield exc


def _status(value: object) -> str:
    cleaned = _STATUS_RE.sub("_", str(value or "").strip()).strip("_")
    return cleaned[:MAX_STATUS_LENGTH]


def _code(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _classify_leaf(exc: BaseException) -> LiveFailure:
    leaf_type = type(exc).__name__
    code = _code(getattr(exc, "code", None))
    status = _status(getattr(exc, "status", ""))
    low_status = status.upper()
    text = str(getattr(exc, "message", "") or exc).casefold()

    auth = (
        code == 401
        or low_status == "UNAUTHENTICATED"
        or any(marker in text for marker in _INVALID_KEY_MARKERS)
    )
    if auth:
        kind = "auth"
    elif code is not None and code >= 500 or low_status in _SERVER_STATUSES:
        kind = "server"
    elif low_status in _SESSION_STATUSES or any(
        marker in text for marker in _SESSION_MARKERS
    ):
        kind = "session"
    elif isinstance(exc, (ConnectionError, TimeoutError, OSError)) or any(
        marker in text for marker in _NETWORK_MARKERS
    ):
        kind = "network"
    else:
        kind = "local"
    return LiveFailure(kind, leaf_type, code, status, auth)


def classify(exc: BaseException) -> LiveFailure:
    failures = [_classify_leaf(leaf) for leaf in leaves(exc)]
    priority = {"auth": 0, "server": 1, "network": 2, "session": 3, "local": 4}
    return min(failures, key=lambda item: priority[item.kind])


def next_backoff(current_s: float | int) -> int:
    try:
        current = int(current_s)
    except (TypeError, ValueError):
        current = 0
    if current <= 0:
        return _INITIAL_BACKOFF_S
    return min(_MAX_BACKOFF_S, max(_INITIAL_BACKOFF_S, current * 2))


def reset_backoff() -> int:
    return _INITIAL_BACKOFF_S


async def wait_until(
    ready: Callable[[], bool],
    should_stop: Callable[[], bool],
    *,
    poll_s: float = 0.25,
) -> bool:
    while not ready():
        if should_stop():
            return False
        await asyncio.sleep(max(0.0, poll_s))
    return True


__all__ = [
    "ConnectionTracker",
    "LiveFailure",
    "MAX_STATUS_LENGTH",
    "ReconnectBackoff",
    "classify",
    "leaves",
    "next_backoff",
    "reset_backoff",
    "wait_until",
]
