"""Fase 11 — outbound gateway retries are bounded."""
from __future__ import annotations

import importlib


def test_delivery_retry_hanya_sekali_setelah_failure():
    try:
        delivery = importlib.import_module("jarvis.gateway.delivery")
    except ModuleNotFoundError:
        delivery = None

    assert delivery is not None
    attempts = []

    def send():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("temporary")
        return "ok"

    assert delivery.deliver(send, retries=1) == "ok"
    assert len(attempts) == 2


def test_delivery_tidak_melebihi_batas_retry():
    delivery = importlib.import_module("jarvis.gateway.delivery")
    attempts = []

    def send():
        attempts.append(1)
        raise RuntimeError("temporary")

    assert delivery.deliver(send, retries=1) is None
    assert len(attempts) == 2
