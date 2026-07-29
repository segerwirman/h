"""Relay.app inbound webhook (Fase 5) — the official delivery path.

A Relay.app workflow adds an HTTP-request step that POSTs JSON to this
endpoint. Security model (no auth configured → server refuses to start):

  * Shared token — Relay HTTP step sets header ``X-Relay-Token: <secret>``
    (env RELAY_WEBHOOK_SECRET). Compared constant-time.
  * Optional HMAC — if the sender can compute it, header
    ``X-Relay-Signature: sha256=<hex hmac(body, secret)>`` is verified
    instead (stronger: body integrity + replay-resistant with timestamp).
  * Replay window — when the payload carries ``timestamp``, events older
    than RELAY_REPLAY_WINDOW_S (default 300) are rejected.
  * Dedup — event_id is the SQLite primary key; duplicates return 200 with
    ``"duplicate": true`` (idempotent for Relay's retry semantics).

Secrets never reach the logs.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jarvis.core import config, log
from jarvis.integrations.relay.models import PayloadError, parse_event
from jarvis.integrations.relay.store import RelayStore

_logger = log.get("relay.webhook")

TOKEN_HEADER = "X-Relay-Token"
SIGNATURE_HEADER = "X-Relay-Signature"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "") or str(config.get(
        "relay." + name.removeprefix("RELAY_").lower(), default) or "")


def verify_request(headers, body: bytes, secret: str,
                   replay_window_s: float, now: float | None = None
                   ) -> tuple[bool, str]:
    """Pure auth check → (ok, reason). Testable without sockets."""
    if not secret:
        return False, "no_secret_configured"
    sig = headers.get(SIGNATURE_HEADER, "")
    if sig:
        expected = "sha256=" + hmac.new(secret.encode(), body,
                                        hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig.strip(), expected):
            return False, "bad_signature"
    else:
        token = headers.get(TOKEN_HEADER, "")
        if not hmac.compare_digest(token.strip(), secret):
            return False, "bad_token"

    if replay_window_s > 0:
        try:
            obj = json.loads(body.decode("utf-8"))
            from jarvis.integrations.relay.models import _parse_ts
            ts = _parse_ts(obj.get("timestamp")) if isinstance(obj, dict) else 0.0
        except Exception:
            ts = 0.0
        if ts:
            now = now if now is not None else time.time()
            if abs(now - ts) > replay_window_s:
                return False, "replay_window"
    return True, "ok"


class WebhookReceiver:
    def __init__(self, store: RelayStore | None = None,
                 host: str | None = None, port: int | None = None,
                 path: str | None = None, secret: str | None = None):
        self.store = store or RelayStore()
        self.host = host or _env("RELAY_WEBHOOK_HOST", "127.0.0.1")
        self.port = int(port or _env("RELAY_WEBHOOK_PORT", "8791"))
        self.path = path or _env("RELAY_WEBHOOK_PATH", "/relay/webhook")
        self.secret = secret if secret is not None else _env("RELAY_WEBHOOK_SECRET")
        self.replay_window_s = float(_env("RELAY_REPLAY_WINDOW_S", "300"))
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.stats = {"accepted": 0, "duplicates": 0, "rejected": 0}

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> bool:
        if not self.secret:
            _logger.error("relay.webhook_no_secret",
                          detail="RELAY_WEBHOOK_SECRET belum diisi — webhook "
                                 "tidak dijalankan (secure by default).")
            return False
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):     # silence stdlib access log
                pass

            def do_POST(self):
                receiver._handle(self)

            def do_GET(self):
                if self.path.rstrip("/") == receiver.path.rstrip("/") + "/health":
                    receiver._respond(self, 200, {"ok": True,
                                                  "events": receiver.store.count()})
                else:
                    receiver._respond(self, 404, {"error": "not found"})

        try:
            self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        except OSError as e:
            _logger.error("relay.webhook_bind_failed", error=str(e)[:100],
                          host=self.host, port=self.port)
            return False
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True, name="relay-webhook")
        self._thread.start()
        _logger.info("relay.webhook_started", host=self.host, port=self.port,
                     path=self.path)
        return True

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # ── request handling ─────────────────────────────────────────────────────
    @staticmethod
    def _respond(handler, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _handle(self, handler) -> None:
        if handler.path.rstrip("/") != self.path.rstrip("/"):
            self._respond(handler, 404, {"error": "not found"})
            return
        length = int(handler.headers.get("Content-Length", 0) or 0)
        if length <= 0 or length > 256 * 1024:
            self.stats["rejected"] += 1
            self._respond(handler, 400, {"error": "bad content length"})
            return
        body = handler.rfile.read(length)

        ok, reason = verify_request(handler.headers, body, self.secret,
                                    self.replay_window_s)
        if not ok:
            self.stats["rejected"] += 1
            _logger.warning("relay.webhook_rejected", reason=reason)
            self._respond(handler, 401, {"error": "unauthorized"})
            return

        try:
            event = parse_event(body)
        except PayloadError as e:
            self.stats["rejected"] += 1
            _logger.warning("relay.webhook_invalid", reason=str(e)[:80])
            self._respond(handler, 400, {"error": str(e)})
            return

        if self.store.add(event):
            self.stats["accepted"] += 1
            _logger.info("relay.event_stored", event_id=event.event_id,
                         kind=event.kind, workflow=event.workflow or "-")
            self._respond(handler, 200, {"ok": True})
        else:
            self.stats["duplicates"] += 1
            _logger.info("relay.event_duplicate", event_id=event.event_id)
            self._respond(handler, 200, {"ok": True, "duplicate": True})
