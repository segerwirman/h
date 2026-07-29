"""Framework maturity Phase 10 — manager owns adapter health and ingress auth."""
from __future__ import annotations


class _Adapter:
    name = "fake"

    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1
        return True

    def stop(self):
        self.stopped += 1

    def health(self):
        return {"state": "connected"}


def test_manager_menolak_ingress_sebelum_actor_di_pair(tmp_path):
    from jarvis.gateway.authz import GatewayAuthz
    from jarvis.gateway.manager import GatewayManager

    received = []
    manager = GatewayManager(on_message=received.append,
                             authz=GatewayAuthz(tmp_path / "gateway.sqlite"))
    manager.register(_Adapter())

    assert manager.receive("fake", "m1", "chat", "actor", "halo") is False
    assert received == []


def test_manager_pair_actor_lalu_dedup_dan_kirim_context():
    from jarvis.gateway.manager import GatewayManager

    received = []
    manager = GatewayManager(on_message=received.append)
    adapter = _Adapter()
    manager.register(adapter)
    assert manager.start("fake") is True
    assert manager.pair("fake", "actor") is True

    assert manager.receive("fake", "m1", "chat", "actor", "halo") is True
    assert manager.receive("fake", "m1", "chat", "actor", "halo") is False
    assert adapter.started == 1
    assert received[0].execution_context().surface == "remote"
    assert manager.health()["fake"]["state"] == "connected"
    manager.stop("fake")
    assert adapter.stopped == 1


def test_gateway_manager_observability_aman_mencatat_accept_dedup_dan_lifecycle(tmp_path):
    from jarvis.gateway.authz import GatewayAuthz
    from jarvis.gateway.manager import GatewayManager

    manager = GatewayManager(
        on_message=lambda _message: None,
        authz=GatewayAuthz(tmp_path / "gateway.sqlite"),
    )
    manager.register(_Adapter())
    assert manager.start("fake") is True
    assert manager.pair("fake", "actor-private") is True
    assert manager.receive("fake", "message-private", "chat-private", "actor-private", "payload-private")
    assert not manager.receive("fake", "message-private", "chat-private", "actor-private", "payload-private")
    manager.stop("fake")

    events = manager.recent_events()
    assert [event["action"] for event in events] == [
        "lifecycle.started", "ingress.accepted", "ingress.deduplicated", "lifecycle.stopped",
    ]
    assert all(event["platform"] == "fake" for event in events)
    assert all("trace_hash" in event for event in events[1:3])
    assert "actor-private" not in repr(events)
    assert "message-private" not in repr(events)
    assert "chat-private" not in repr(events)
    assert "payload-private" not in repr(events)


def test_gateway_manager_tidak_mengekspos_singleton_noop():
    from jarvis.gateway import manager

    assert not hasattr(manager, "MANAGER")
