"""Fase 11 — gateway ingress deduplicates platform events."""
from __future__ import annotations

import importlib


def test_gateway_registry_menolak_inbound_duplikat_dan_memberi_toolset_platform(tmp_path):
    try:
        registry = importlib.import_module("jarvis.gateway.registry")
    except ModuleNotFoundError:
        registry = None

    assert registry is not None
    gate = registry.GatewayRegistry(receipt_path=tmp_path / "receipts.sqlite")
    assert gate.accept_inbound("telegram", "message-1", "chat-7") is True
    assert gate.accept_inbound("telegram", "message-1", "chat-7") is False
    assert gate.default_toolsets("telegram") == frozenset({"messaging"})
    assert gate.default_toolsets("unknown") == frozenset()


def test_gateway_registry_menolak_replay_lintas_instance_dengan_receipt_durable(tmp_path):
    from jarvis.gateway.registry import GatewayRegistry

    path = tmp_path / "receipts.sqlite"
    first = GatewayRegistry(receipt_path=path)
    second = GatewayRegistry(receipt_path=path)

    assert first.accept_inbound("telegram", "message-private", "chat-private") is True
    assert second.accept_inbound("telegram", "message-private", "chat-private") is False
    assert "message-private" not in repr(second.receipt_stats())
    assert "chat-private" not in repr(second.receipt_stats())
