"""Credential-safe rollout checks for manager-owned gateway transports."""
from __future__ import annotations

from jarvis.core import release_controls


def telegram_preflight(runtime, *, release_flags: dict | None = None) -> dict:
    """Inspect only safe readiness metadata; never start a transport or read secrets."""
    manager = runtime.manager
    health = dict(manager.health().get("telegram", {"state": "unknown"}))
    checks = {
        "gateway_enabled": bool((release_flags or release_controls.current()).get("gateway", False)),
        "manager_bound": bool(manager.registered("telegram")),
        "transport_connected": health.get("state") == "connected",
        "durable_pairing": manager.paired_count("telegram") > 0,
    }
    return {"platform": "telegram", "ready": all(checks.values()),
            "checks": checks, "health": health}


def acceptance_evidence(preflight: dict, events: list[dict], *, revision: str) -> dict:
    """Reduce deterministic rollout evidence to safe, payload-free metadata."""
    allowed = ("lifecycle.started", "ingress.accepted", "ingress.deduplicated",
               "lifecycle.stopped")
    actions = [str(event.get("action", "")) for event in events
               if str(event.get("action", "")) in allowed]
    required = set(allowed)
    return {
        "platform": "telegram",
        "revision": str(revision)[:80],
        "preflight_ready": bool(preflight.get("ready", False)),
        "health_state": str(dict(preflight.get("health") or {}).get("state", "unknown"))[:32],
        "actions": actions,
        "eligible": bool(preflight.get("ready", False)) and required.issubset(actions),
    }