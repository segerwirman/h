"""Fase 7 — voice delivery state remains interruptible."""
from __future__ import annotations

import importlib


def test_interrupt_membatalkan_delivery_aktif_dan_menolak_completion_stale():
    try:
        module = importlib.import_module("jarvis.agent.voice_delivery")
    except ModuleNotFoundError:
        module = None

    assert module is not None
    events = []
    controller = module.VoiceDeliveryController(
        publish=lambda event, **payload: events.append((event, payload))
    )

    token = controller.start("Laporan singkat, sir.")
    assert controller.interrupt(token) is True
    assert controller.finish(token) is False
    assert [event for event, _ in events] == [
        "conversation.delivery_started",
        "conversation.delivery_interrupted",
    ]
