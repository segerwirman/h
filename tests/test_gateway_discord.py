"""Framework maturity Phase 11 — Discord normalization stays credential-free."""
from __future__ import annotations


def test_discord_normalize_dm_thread_dan_dedup():
    from jarvis.gateway.platforms.discord import DiscordGateway

    from jarvis.gateway.manager import GatewayManager

    received = []
    manager = GatewayManager(on_message=received.append)
    gateway = DiscordGateway(manager)
    assert manager.register(gateway)
    assert manager.pair("discord", "actor")

    assert gateway.receive("m1", "dm-9", "actor", "halo", thread_id="thread-2") is True
    assert gateway.receive("m1", "dm-9", "actor", "halo", thread_id="thread-2") is False
    item = received[0]
    assert item.platform == "discord"
    assert item.conversation_id == "dm-9:thread-2"


def test_discord_health_tidak_memerlukan_token():
    from jarvis.gateway.manager import GatewayManager
    from jarvis.gateway.platforms.discord import DiscordGateway

    gateway = DiscordGateway(GatewayManager(on_message=lambda _item: None))
    assert gateway.health() == {"state": "not_configured"}
    assert gateway.start() is False
