"""Fail-closed, dependency-free policy for dashboard exposure."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit


class DashboardSecurityError(ValueError):
    """Raised when an explicit dashboard LAN configuration is unsafe."""


class FixedWindowRateLimiter:
    """Bounded, payload-free per-client fixed-window limiter."""

    def __init__(self, *, limit: int, window_seconds: float, now=monotonic,
                 max_clients: int = 1024) -> None:
        self._limit = max(1, int(limit))
        self._window_seconds = max(1.0, float(window_seconds))
        self._now = now
        self._max_clients = max(1, int(max_clients))
        self._buckets: dict[str, tuple[float, int]] = {}
        self._lock = Lock()

    def allow(self, client_key: str) -> bool:
        key = str(client_key or "unknown")[:128]
        now = float(self._now())
        with self._lock:
            opened, count = self._buckets.get(key, (now, 0))
            if now - opened >= self._window_seconds:
                opened, count = now, 0
            if count >= self._limit:
                return False
            if key not in self._buckets and len(self._buckets) >= self._max_clients:
                oldest = next(iter(self._buckets))
                self._buckets.pop(oldest, None)
            self._buckets[key] = (opened, count + 1)
            return True


@dataclass(frozen=True)
class DashboardExposure:
    host: str
    port: int
    lan_enabled: bool
    read_only: bool
    origins: frozenset[str]
    tls_required: bool
    needs_firewall: bool

    @property
    def allows_remote_mutation(self) -> bool:
        return False

    def allows_origin(self, origin: str) -> bool:
        """Allow only normalized origins explicitly configured for LAN mode."""
        return bool(self.lan_enabled and str(origin or "").strip().lower() in self.origins)


def exposure_from_config(raw: dict | None, *, tls_available: bool) -> DashboardExposure:
    """Resolve dashboard exposure with loopback as the only implicit mode."""
    settings = raw or {}
    port = int(settings.get("port", 8000) or 8000)
    if not 1 <= port <= 65535:
        raise DashboardSecurityError("Dashboard port must be between 1 and 65535.")
    if not bool(settings.get("lan_enabled", False)):
        return DashboardExposure(
            host="127.0.0.1",
            port=port,
            lan_enabled=False,
            read_only=True,
            origins=frozenset(),
            tls_required=False,
            needs_firewall=False,
        )

    if not tls_available or not bool(settings.get("require_tls_for_lan", True)):
        raise DashboardSecurityError("Dashboard LAN mode requires TLS.")
    if not bool(settings.get("lan_read_only", True)):
        raise DashboardSecurityError("Dashboard LAN mode must remain read-only.")
    origins = _origins(settings.get("lan_allowed_origins", ()))
    if not origins:
        raise DashboardSecurityError("Dashboard LAN mode requires an allowed origin.")
    return DashboardExposure(
        host="0.0.0.0",
        port=port,
        lan_enabled=True,
        read_only=True,
        origins=origins,
        tls_required=True,
        # Binding LAN does not authorize OS firewall/UAC changes.
        needs_firewall=False,
    )


def _origins(values: object) -> frozenset[str]:
    if isinstance(values, str) or not isinstance(values, (list, tuple, set, frozenset)):
        raise DashboardSecurityError("Dashboard LAN origins must be a list of exact HTTPS origins.")
    normalized: set[str] = set()
    for value in values:
        parsed = urlsplit(str(value).strip())
        if (parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/")
                or parsed.query or parsed.fragment or parsed.username or parsed.password):
            raise DashboardSecurityError("Dashboard LAN origin must be an exact HTTPS origin.")
        normalized.add(f"https://{parsed.netloc.lower()}")
    return frozenset(normalized)
