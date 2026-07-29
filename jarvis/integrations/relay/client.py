"""Outbound HTTP client for user-exposed Relay.app endpoints (Fase 5).

Relay.app has no public general read API; what CAN exist is an endpoint the
user deliberately exposes (e.g. a Relay workflow triggered by an inbound
HTTP call that responds with data). Therefore this client never invents
paths: it only calls endpoints listed in ``relay.endpoints`` (config.yaml)
or passed explicitly, against RELAY_BASE_URL.

Hardening: request timeout, bounded retries with exponential backoff +
jitter, Retry-After support on 429, circuit breaker, token redaction.
"""
from __future__ import annotations

import os
import random
import time

from jarvis.core import config, log
from jarvis.core.circuit import CircuitBreaker, CircuitOpenError

_logger = log.get("relay.client")


class RelayClientError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "") or str(config.get(
        "relay." + name.removeprefix("RELAY_").lower(), default) or "")


class RelayClient:
    def __init__(self, base_url: str | None = None, token: str | None = None,
                 timeout_s: float | None = None, max_retries: int | None = None,
                 session=None):
        self.base_url = (base_url if base_url is not None
                         else _env("RELAY_BASE_URL")).rstrip("/")
        self.token = token if token is not None else _env("RELAY_API_TOKEN")
        self.timeout_s = float(timeout_s if timeout_s is not None
                               else _env("RELAY_REQUEST_TIMEOUT_SECONDS", "10"))
        self.max_retries = int(max_retries if max_retries is not None
                               else _env("RELAY_MAX_RETRIES", "2"))
        self._session = session          # injectable for tests
        self.breaker = CircuitBreaker("relay", failure_threshold=4,
                                      reset_timeout_s=60.0)

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _http(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def get_json(self, path: str, params: dict | None = None) -> dict | list:
        """GET {base_url}{path} with retries. Raises RelayClientError."""
        if not self.configured:
            raise RelayClientError("not_configured",
                                   "RELAY_BASE_URL belum dikonfigurasi.")
        if not self.breaker.allow():
            raise RelayClientError("circuit_open",
                                   "Layanan Relay sementara dilewati "
                                   "(terlalu banyak kegagalan beruntun).")
        url = self.base_url + "/" + path.lstrip("/")
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            t0 = time.monotonic()
            try:
                resp = self._http().get(url, params=params or {},
                                        headers=headers,
                                        timeout=self.timeout_s)
            except Exception as e:
                last_err = e
                _logger.warning("relay.request_failed", attempt=attempt,
                                error=str(e)[:100])         # no token in msg
                self._backoff(attempt, None)
                continue

            elapsed = round((time.monotonic() - t0) * 1000)
            if resp.status_code == 200:
                self.breaker.record_success()
                _logger.info("relay.request_ok", path=path, ms=elapsed,
                             attempt=attempt)
                try:
                    return resp.json()
                except ValueError:
                    self.breaker.record_failure()
                    raise RelayClientError("bad_response",
                                           "Respons Relay bukan JSON valid.")
            if resp.status_code in (401, 403):
                self.breaker.record_failure()
                raise RelayClientError("unauthorized",
                                       "Token Relay ditolak (401/403).")
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                _logger.warning("relay.rate_limited", attempt=attempt,
                                retry_after=retry_after)
                if attempt >= self.max_retries:
                    self.breaker.record_failure()
                    raise RelayClientError("rate_limited",
                                           "Relay membatasi laju permintaan.")
                self._backoff(attempt, retry_after)
                continue
            if resp.status_code >= 500:
                last_err = RelayClientError("server_error",
                                            f"HTTP {resp.status_code}")
                _logger.warning("relay.server_error",
                                status=resp.status_code, attempt=attempt)
                self._backoff(attempt, None)
                continue
            self.breaker.record_failure()
            raise RelayClientError("http_error",
                                   f"HTTP {resp.status_code} dari Relay.")

        self.breaker.record_failure()
        if isinstance(last_err, RelayClientError):
            raise last_err
        raise RelayClientError("network_error",
                               f"Gagal menghubungi Relay: "
                               f"{str(last_err)[:80] if last_err else 'timeout'}")

    def get_paginated(self, path: str, params: dict | None = None,
                      item_key: str = "items", cursor_key: str = "next_cursor",
                      max_pages: int = 5, max_items: int = 100) -> list:
        """Cursor pagination helper; bounded pages + items."""
        items: list = []
        params = dict(params or {})
        for _ in range(max_pages):
            data = self.get_json(path, params)
            if isinstance(data, list):
                items.extend(data)
                break
            items.extend(data.get(item_key) or [])
            cursor = data.get(cursor_key)
            if not cursor or len(items) >= max_items:
                break
            params["cursor"] = cursor
        return items[:max_items]

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        if retry_after:
            try:
                time.sleep(min(float(retry_after), 30.0))
                return
            except ValueError:
                pass
        time.sleep(min(2 ** attempt, 15) * 0.5 + random.uniform(0, 0.4))
