"""Phase 14 — Telegram controlled-rollout checks are credential-safe."""
from __future__ import annotations


def test_telegram_preflight_memerlukan_gateway_running_dan_pair_durable(tmp_path):
    from jarvis.gateway.authz import GatewayAuthz
    from jarvis.gateway.rollout import telegram_preflight
    from jarvis.gateway.runtime import TelegramGatewayRuntime

    class Service:
        name = "telegram"

        def __init__(self):
            self.running = False
            self.bound = None

        def bind_gateway_manager(self, manager):
            self.bound = manager

        def start(self):
            self.running = True
            return True

        def stop(self):
            self.running = False

        def health(self):
            return {"state": "connected" if self.running else "stopped"}

    authz = GatewayAuthz(tmp_path / "gateway.sqlite")
    runtime = TelegramGatewayRuntime(service=Service(), authz=authz)

    blocked = telegram_preflight(runtime, release_flags={"gateway": False})
    assert blocked["ready"] is False
    assert blocked["checks"] == {
        "gateway_enabled": False,
        "manager_bound": True,
        "transport_connected": False,
        "durable_pairing": False,
    }

    assert authz.pair("telegram", "only-for-test")
    assert runtime.start() is True
    ready = telegram_preflight(runtime, release_flags={"gateway": True})

    assert ready["ready"] is True
    assert ready["health"] == {"state": "connected"}
    assert "only-for-test" not in repr(ready)


def test_acceptance_evidence_hanya_merekam_metadata_aman():
    from jarvis.gateway.rollout import acceptance_evidence

    report = acceptance_evidence(
        {"ready": True, "health": {"state": "connected"}},
        [
            {"action": "lifecycle.started", "platform": "telegram"},
            {"action": "ingress.accepted", "platform": "telegram", "trace_hash": "a" * 16},
            {"action": "ingress.deduplicated", "platform": "telegram", "trace_hash": "b" * 16},
            {"action": "lifecycle.stopped", "platform": "telegram"},
        ],
        revision="local-revision",
    )

    assert report["eligible"] is True
    assert report["revision"] == "local-revision"
    assert report["actions"] == ["lifecycle.started", "ingress.accepted", "ingress.deduplicated", "lifecycle.stopped"]
    assert "payload" not in repr(report)


def test_telegram_manager_soak_dedup_dan_restart_tetap_idempoten(tmp_path):
    from jarvis.gateway.authz import GatewayAuthz
    from jarvis.gateway.runtime import TelegramGatewayRuntime

    class Service:
        name = "telegram"

        def __init__(self):
            self.running = False
            self.messages = []

        def bind_gateway_manager(self, _manager):
            pass

        def start(self):
            self.running = True
            return True

        def stop(self):
            self.running = False

        def health(self):
            return {"state": "connected" if self.running else "stopped"}

        def handle_gateway_inbound(self, message):
            self.messages.append(message.message_id)

    service = Service()
    runtime = TelegramGatewayRuntime(
        service=service, authz=GatewayAuthz(tmp_path / "gateway.sqlite"))
    assert runtime.manager.pair("telegram", "trusted-test-actor") is True

    for _ in range(8):
        assert runtime.restart() is True
    for index in range(200):
        assert runtime.manager.receive(
            "telegram", f"message-{index}", "conversation", "trusted-test-actor", "ping") is True
    assert runtime.manager.receive(
        "telegram", "message-0", "conversation", "trusted-test-actor", "duplicate") is False

    assert len(service.messages) == 200
    assert service.running is True
