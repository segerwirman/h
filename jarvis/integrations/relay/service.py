"""RelayService — read-only facade used by the agent, UI, and health checks.

Data sources, in order of preference:
  1. Local store fed by the inbound webhook (official Relay → JARVIS path).
  2. Optional outbound client, only when the user exposed an endpoint
     (RELAY_BASE_URL + relay.endpoints in config.yaml).

Mutations (triggering Relay workflows) are deliberately NOT exposed to the
agent; ``trigger_workflow`` exists for future UI use, is disabled unless
RELAY_ALLOW_ACTIONS=1, and still requires ``confirmed=True`` per call.
"""
from __future__ import annotations

import os
import threading

from jarvis.core import config, log
from jarvis.integrations.relay.client import RelayClient, RelayClientError
from jarvis.integrations.relay.store import RelayStore
from jarvis.integrations.relay.webhook import WebhookReceiver

_logger = log.get("relay.service")


def _enabled() -> bool:
    raw = os.environ.get("RELAY_ENABLED")
    if raw is not None:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    return bool(config.get("relay.enabled", False))


class RelayService:
    _instance: "RelayService | None" = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "RelayService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = RelayService()
            return cls._instance

    def __init__(self):
        self.enabled = _enabled()
        self.store = RelayStore()
        self.client = RelayClient()
        self.webhook: WebhookReceiver | None = None
        self.webhook_running = False

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> None:
        if not self.enabled:
            _logger.info("relay.disabled")
            return
        self.webhook = WebhookReceiver(store=self.store)
        self.webhook_running = self.webhook.start()

    def stop(self) -> None:
        if self.webhook is not None:
            self.webhook.stop()
            self.webhook_running = False

    # ── read-only operations ─────────────────────────────────────────────────
    def status(self) -> dict:
        s = {
            "enabled": self.enabled,
            "webhook_running": self.webhook_running,
            "events_stored": self.store.count(),
            "client_configured": self.client.configured,
            "circuit": self.client.breaker.state,
        }
        if self.webhook is not None:
            s["webhook_stats"] = dict(self.webhook.stats)
        return s

    def sources(self) -> list[dict]:
        """Workflows/sources seen via webhook + any configured endpoints."""
        out = [{"type": "workflow", "name": w} for w in self.store.workflows()]
        for name in (config.section("relay.endpoints") or {}):
            out.append({"type": "endpoint", "name": name})
        return out

    def recent_events(self, limit: int = 10) -> list[dict]:
        limit = max(1, min(int(limit), 25))          # bounded output
        return [e.summary() for e in self.store.recent(limit)]

    def workflow_result(self, workflow: str) -> dict | None:
        rows = self.store.by_workflow(workflow, limit=1)
        if rows:
            return rows[0].summary(max_chars=800)
        # optional pull path — only if the user exposed an endpoint with
        # this exact name in config.yaml (never an invented URL)
        endpoints = config.section("relay.endpoints") or {}
        path = endpoints.get(workflow)
        if path and self.client.configured:
            try:
                data = self.client.get_json(path)
                return {"workflow": workflow, "source": "endpoint",
                        "data": str(data)[:800]}
            except RelayClientError as e:
                return {"workflow": workflow, "error": e.code,
                        "message": str(e)[:160]}
        return None

    # ── guarded mutation (NOT exposed to the agent) ──────────────────────────
    def trigger_workflow(self, path: str, payload: dict, *,
                         confirmed: bool = False) -> dict:
        allow = os.environ.get("RELAY_ALLOW_ACTIONS", "").strip().lower() \
            in ("1", "true", "yes", "on")
        if not allow:
            raise PermissionError(
                "Aksi Relay dinonaktifkan. Set RELAY_ALLOW_ACTIONS=1 untuk "
                "mengaktifkan mode action-enabled.")
        if not confirmed:
            raise PermissionError(
                "Aksi Relay membutuhkan konfirmasi eksplisit pengguna.")
        raise NotImplementedError(
            "Trigger workflow belum diaktifkan — sediakan endpoint tujuan "
            "di relay.endpoints dan implement sesuai kebutuhan.")
