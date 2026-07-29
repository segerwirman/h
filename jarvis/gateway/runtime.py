"""Application-owned Telegram runtime bound to the formal gateway manager."""
from __future__ import annotations

import threading

from jarvis.gateway.authz import GatewayAuthz
from jarvis.gateway.manager import GatewayManager
from jarvis.gateway.registry import GatewayRegistry


class TelegramGatewayRuntime:
    """Own the manager/service binding without constructing transport credentials."""

    def __init__(self, *, service, authz: GatewayAuthz | None = None,
                 registry: GatewayRegistry | None = None) -> None:
        self.service = service
        effective_authz = authz or GatewayAuthz()
        effective_registry = registry or GatewayRegistry(
            receipt_path=effective_authz.path.with_name("gateway_receipts.sqlite"))
        self.manager = GatewayManager(
            on_message=self._on_message,
            authz=effective_authz,
            registry=effective_registry,
        )
        if not self.manager.register(service):
            raise ValueError("Telegram service tidak dapat didaftarkan ke gateway manager")
        bind = getattr(service, "bind_gateway_manager", None)
        if callable(bind):
            bind(self.manager)

    def _on_message(self, message) -> None:
        handler = getattr(self.service, "handle_gateway_inbound", None)
        if callable(handler):
            handler(message)

    def start(self) -> bool:
        return self.manager.start("telegram")

    def stop(self) -> None:
        self.manager.stop("telegram")

    def restart(self) -> bool:
        self.stop()
        return self.start()


_runtime_lock = threading.Lock()
_runtime: TelegramGatewayRuntime | None = None


def telegram_runtime() -> TelegramGatewayRuntime:
    """Return the one application-owned runtime for the singleton service."""
    global _runtime
    from jarvis.agent.adapters.telegram import TelegramService

    service = TelegramService.get()
    with _runtime_lock:
        if _runtime is None or _runtime.service is not service:
            _runtime = TelegramGatewayRuntime(service=service)
        return _runtime
