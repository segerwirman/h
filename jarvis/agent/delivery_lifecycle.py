"""Shared, safe lifecycle telemetry for conversation delivery.

This boundary owns neither transport nor task execution.  It returns the same
``ConversationDelivery`` consumed by existing ingress adapters while publishing
only non-sensitive metadata to the activity bus.
"""
from __future__ import annotations

from jarvis.agent import conversation_context, interaction, response_composer
from jarvis.core.bus import BUS

_SAFE_SOURCES = frozenset({"voice", "typed", "telegram"})


def success(
    raw_result: str,
    task: str,
    *,
    source: str,
    naturalize: bool = False,
    conversation_id: str | None = None,
) -> interaction.ConversationDelivery:
    """Build and report a successful deterministic delivery."""

    delivery = interaction.success_delivery(raw_result, task)
    if naturalize:
        delivery = response_composer.compose(delivery, task)
    if conversation_id:
        # Title-level continuity for callers without a registry task ID. The
        # adapters that own a task ID bind it AFTER this call with
        # ``STORE.remember_success(task_id=...)``; the store is then written
        # once per task, not twice.
        conversation_context.STORE.remember_success(
            conversation_id, task=task, delivery=delivery
        )
    _publish("completed", "success", _source(source), delivery)
    return delivery


def failure(
    raw_error: object,
    task: str,
    *,
    source: str,
) -> interaction.ConversationDelivery:
    """Build and report a failed deterministic delivery."""

    delivery = interaction.failure_delivery(raw_error, task)
    _publish("failed", "failure", _source(source), delivery)
    return delivery


def acknowledged(source: str, ack: object) -> None:
    """Report an ACK transition without publishing its spoken content."""

    BUS.publish(
        "agent.delivery.acknowledged",
        source=_source(source),
        outcome="ack",
        ack_chars=len(str(ack or "")),
    )


def _source(value: str) -> str:
    return value if value in _SAFE_SOURCES else "unknown"


def _publish(
    stage: str,
    outcome: str,
    source: str,
    delivery: interaction.ConversationDelivery,
) -> None:
    BUS.publish(
        f"agent.delivery.{stage}",
        source=source,
        outcome=outcome,
        mode=delivery.mode,
        display_chars=len(delivery.display_text),
        speech_chars=len(delivery.speech_text),
        anchor_count=len(delivery.factual_anchors),
    )
