"""Phase WA9 — controlled WhatsApp rollout policy.

Deny-by-default: toggle config + allowlist policy + opt-out/revoke +
rate limiting + daily caps. Policy MURNI lokal — tanpa import SDK,
network, atau file write (live integration di fase terpisah).
"""
from __future__ import annotations

import time

_DENY_REASONS = (
    "wa_rollout_disabled",
    "wa_contact_not_allowlisted",
    "wa_contact_opted_out",
    "wa_rate_limited",
    "wa_daily_cap_reached",
)

RATE_WINDOW_S = 60
DAY_S = 86_400


def _config_get(key: str, default: object = None) -> object:
    try:
        from jarvis.core import config
        return config.get(key, default)
    except Exception:  # noqa: BLE001
        return default


def _now() -> float:
    return time.monotonic()


class WhatsAppRolloutPolicy:
    """Gate outbound WhatsApp lokal; deny-by-default; tanpa live send."""

    def __init__(self) -> None:
        self._opted_out: set[str] = set()
        self._rate_log: list[float] = []
        self._daily: dict[int, int] = {}

    def _enabled(self) -> bool:
        return bool(_config_get("integrations.whatsapp.rollout_enabled",
                                False))

    def _allowlist(self) -> list:
        value = _config_get("integrations.whatsapp.allowlist", [])
        return list(value) if isinstance(value, (list, tuple)) else []

    def _rate_per_minute(self) -> int:
        return int(_config_get("integrations.whatsapp.rate_per_minute", 5))

    def _daily_cap(self) -> int:
        return int(_config_get("integrations.whatsapp.daily_cap", 50))

    def opt_out(self, contact: str) -> bool:
        self._opted_out.add(contact)
        return True

    def revoke_opt_out(self, contact: str) -> bool:
        if contact in self._opted_out:
            self._opted_out.discard(contact)
            return True
        return False

    def allow_outbound(self, contact: str) -> dict:
        if not self._enabled():
            return {"ok": False, "reason": "wa_rollout_disabled"}
        if contact not in self._allowlist():
            return {"ok": False, "reason": "wa_contact_not_allowlisted"}
        if contact in self._opted_out:
            return {"ok": False, "reason": "wa_contact_opted_out"}

        now = _now()
        # Rate limiting: sliding 60s window
        self._rate_log = [t for t in self._rate_log if now - t < RATE_WINDOW_S]
        if len(self._rate_log) >= self._rate_per_minute():
            return {"ok": False, "reason": "wa_rate_limited"}
        # Daily cap: per-hari (UTC day bucket)
        day = int(now) // DAY_S
        used = self._daily.get(day, 0)
        if used >= self._daily_cap():
            return {"ok": False, "reason": "wa_daily_cap_reached"}

        self._rate_log.append(now)
        self._daily[day] = used + 1
        return {"ok": True, "reason": None}


__all__ = ["WhatsAppRolloutPolicy", "_DENY_REASONS", "RATE_WINDOW_S", "DAY_S"]
