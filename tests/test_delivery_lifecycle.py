"""Fase 5 — unified delivery lifecycle telemetry lintas ingress."""
from __future__ import annotations

import importlib


def test_success_lifecycle_mengembalikan_delivery_dan_menerbitkan_event_aman(
    monkeypatch,
):
    try:
        lifecycle = importlib.import_module("jarvis.agent.delivery_lifecycle")
    except ModuleNotFoundError:
        lifecycle = None
    assert lifecycle is not None

    published = []
    monkeypatch.setattr(
        lifecycle.BUS,
        "publish",
        lambda event, **payload: published.append((event, payload)),
    )

    delivery = lifecycle.success(
        '**Video "Deddy Corbuzier Episode 123" sudah diputar.**\n'
        "URL: https://youtube.com/watch?v=abc123",
        "putar video terbaru",
        source="voice",
    )

    assert delivery.mode == "deterministic"
    assert delivery.display_text.startswith('Video "Deddy Corbuzier')
    assert published == [(
        "agent.delivery.completed",
        {
            "source": "voice",
            "outcome": "success",
            "mode": "deterministic",
            "display_chars": len(delivery.display_text),
            "speech_chars": len(delivery.speech_text),
            "anchor_count": len(delivery.factual_anchors),
        },
    )]


def test_failure_lifecycle_mengembalikan_delivery_dan_menerbitkan_event_aman(
    monkeypatch,
):
    lifecycle = importlib.import_module("jarvis.agent.delivery_lifecycle")
    published = []
    monkeypatch.setattr(
        lifecycle.BUS,
        "publish",
        lambda event, **payload: published.append((event, payload)),
    )

    delivery = lifecycle.failure(
        "permission denied for C:/reports/private.txt (403)",
        "simpan laporan",
        source="telegram",
    )

    assert delivery.mode == "deterministic"
    assert "permission denied" in delivery.display_text
    assert published == [(
        "agent.delivery.failed",
        {
            "source": "telegram",
            "outcome": "failure",
            "mode": "deterministic",
            "display_chars": len(delivery.display_text),
            "speech_chars": len(delivery.speech_text),
            "anchor_count": len(delivery.factual_anchors),
        },
    )]


def test_success_lifecycle_opsional_naturalize_sebelum_menerbitkan_event(
    monkeypatch,
):
    lifecycle = importlib.import_module("jarvis.agent.delivery_lifecycle")
    deterministic = lifecycle.interaction.success_delivery(
        "Laporan build 123 selesai.", "cek build", address="sir"
    )
    natural = lifecycle.interaction.ConversationDelivery(
        display_text=deterministic.display_text,
        speech_text="Build 123 sudah selesai, sir.",
        factual_anchors=deterministic.factual_anchors,
        mode="natural",
    )
    published = []
    monkeypatch.setattr(lifecycle.response_composer, "compose", lambda *_args: natural)
    monkeypatch.setattr(
        lifecycle.BUS,
        "publish",
        lambda event, **payload: published.append((event, payload)),
    )

    delivery = lifecycle.success(
        "Laporan build 123 selesai.",
        "cek build",
        source="typed",
        naturalize=True,
    )

    assert delivery is natural
    assert published[0][0] == "agent.delivery.completed"
    assert published[0][1]["source"] == "typed"
    assert published[0][1]["mode"] == "natural"


def test_acknowledged_menerbitkan_metadata_aman_tanpa_isi_ack(monkeypatch):
    lifecycle = importlib.import_module("jarvis.agent.delivery_lifecycle")
    published = []
    monkeypatch.setattr(
        lifecycle.BUS,
        "publish",
        lambda event, **payload: published.append((event, payload)),
    )

    lifecycle.acknowledged("voice", "Baik, sir. Saya kerjakan.")

    assert published == [(
        "agent.delivery.acknowledged",
        {"source": "voice", "outcome": "ack", "ack_chars": 25},
    )]


def test_success_lifecycle_merekam_continuity_hanya_dengan_conversation_id(
    monkeypatch,
):
    lifecycle = importlib.import_module("jarvis.agent.delivery_lifecycle")
    remembered = []
    monkeypatch.setattr(
        lifecycle.conversation_context.STORE,
        "remember_success",
        lambda conversation_id, *, task, delivery: remembered.append(
            (conversation_id, task, delivery)
        ),
    )

    delivery = lifecycle.success(
        "Build 123 selesai.", "cek build", source="voice", conversation_id="voice-1"
    )

    assert remembered == [("voice-1", "cek build", delivery)]
