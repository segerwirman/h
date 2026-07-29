"""Framework maturity Phase 10 — pairing state is bounded and revocable."""
from __future__ import annotations


def test_pair_revoke_menghentikan_actor():
    from jarvis.gateway.authz import GatewayAuthz

    authz = GatewayAuthz()
    assert authz.pair("telegram", "actor-a") is True
    assert authz.allowed("telegram", "actor-a") is True
    authz.revoke("telegram", "actor-a")
    assert authz.allowed("telegram", "actor-a") is False


def test_pair_menolak_platform_atau_actor_kosong():
    from jarvis.gateway.authz import GatewayAuthz

    authz = GatewayAuthz()
    assert authz.pair("", "actor") is False
    assert authz.pair("telegram", "") is False


def test_pairing_durable_restart_dan_safe_metadata(tmp_path):
    from jarvis.gateway.authz import GatewayAuthz

    path = tmp_path / "gateway.sqlite"
    first = GatewayAuthz(path)
    assert first.pair("telegram", "actor-a", paired_by="local-admin")

    second = GatewayAuthz(path)
    assert second.allowed("telegram", "actor-a") is True
    record = second.list_pairs()[0]
    assert record["platform"] == "telegram"
    assert record["state"] == "paired"
    assert "actor-a" not in repr(record)
    assert "local-admin" not in repr(record)


def test_revoke_durable_menolak_actor_setelah_restart(tmp_path):
    from jarvis.gateway.authz import GatewayAuthz

    path = tmp_path / "gateway.sqlite"
    authz = GatewayAuthz(path)
    authz.pair("discord", "actor-a", paired_by="local-admin")
    authz.revoke("discord", "actor-a", revoked_by="local-admin")

    assert GatewayAuthz(path).allowed("discord", "actor-a") is False
