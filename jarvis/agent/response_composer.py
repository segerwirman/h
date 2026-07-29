"""Optional, fact-grounded naturalization for deterministic conversation delivery.

The composer never owns a result: it only proposes a new ``speech_text`` for a
verified ``ConversationDelivery``.  Any unavailable provider, timeout, malformed
reply, or anchor mismatch returns the original deterministic value unchanged.
"""
from __future__ import annotations

import re
import threading
from collections.abc import Callable

from jarvis.agent import auxiliary
from jarvis.agent.interaction import (ConversationDelivery, sanitize_for_speech,
                                      speech_limit, speech_sentence_limit)
from jarvis.core import config, log

_logger = log.get("agent.response_composer")
_IN_FLIGHT = threading.BoundedSemaphore(value=1)
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]?(?=\s|$)")

_SYSTEM_PROMPT = """You compose a concise spoken update for JARVIS.
Use only the verified spoken brief below. Preserve every required factual anchor
exactly, do not invent facts, do not add URLs or file paths, and return only one
or two natural sentences with no markdown or prefacing."""


def compose(
    delivery: ConversationDelivery,
    task: str,
    *,
    enabled: bool | None = None,
    timeout_s: float | None = None,
    client_factory: Callable[[], object] | None = None,
) -> ConversationDelivery:
    """Return a natural spoken variant, or the original deterministic delivery.

    The display report and full factual-anchor inventory are immutable at this
    boundary.  The function is synchronous but returns by the configured local
    deadline; a timed-out background request cannot block a later delivery.
    """

    if not _enabled(enabled):
        return delivery

    required = _speech_anchors(delivery)
    request = _request(task, delivery.speech_text, required)
    factory = client_factory or (lambda: auxiliary.client_for("response_composer"))
    candidate = _run_bounded(
        lambda: _chat(factory(), request), _timeout(timeout_s)
    )
    natural = _validated_speech(candidate, delivery, required)
    if not natural:
        return delivery
    return ConversationDelivery(
        display_text=delivery.display_text,
        speech_text=natural,
        factual_anchors=delivery.factual_anchors,
        mode="natural",
    )


def _enabled(value: bool | None) -> bool:
    if value is not None:
        return bool(value)
    return bool(config.get("auxiliary.response_composer.enabled", False))


def _timeout(value: float | None) -> float:
    raw = value if value is not None else config.get(
        "auxiliary.response_composer.timeout_s", 2.0
    )
    try:
        return max(0.001, min(float(raw), 10.0))
    except (TypeError, ValueError):
        return 2.0


def _request(task: str, speech: str, anchors: tuple[str, ...]) -> list[dict]:
    anchor_text = ", ".join(anchors) if anchors else "(none)"
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Task: {str(task or '')[:500]}\n"
            f"Verified spoken brief: {speech}\n"
            f"Required exact anchors: {anchor_text}"
        )},
    ]


def _chat(client: object, messages: list[dict]) -> str:
    try:
        response = client.chat(messages, temperature=0.2, max_tokens=_max_tokens())
    except Exception as exc:  # noqa: BLE001 - optional enhancement only
        _logger.info("response_composer.call_failed", error_type=type(exc).__name__)
        return ""
    if not getattr(response, "ok", False):
        return ""
    return str(getattr(response, "content", "") or "")


def _max_tokens() -> int:
    try:
        return max(16, min(int(config.get(
            "auxiliary.response_composer.max_tokens", 120
        )), 256))
    except (TypeError, ValueError):
        return 120


def _run_bounded(call: Callable[[], str], timeout_s: float) -> str:
    """Run one optional call without letting a provider stall delivery."""

    if not _IN_FLIGHT.acquire(blocking=False):
        _logger.info("response_composer.skipped", reason="busy")
        return ""

    done = threading.Event()
    result: list[str] = [""]

    def _worker() -> None:
        try:
            result[0] = call()
        except Exception as exc:  # noqa: BLE001 - optional enhancement only
            _logger.info("response_composer.call_failed", error_type=type(exc).__name__)
        finally:
            _IN_FLIGHT.release()
            done.set()

    threading.Thread(target=_worker, name="jarvis-response-composer",
                     daemon=True).start()
    if not done.wait(timeout_s):
        _logger.info("response_composer.skipped", reason="timeout")
        return ""
    return result[0]


def _speech_anchors(delivery: ConversationDelivery) -> tuple[str, ...]:
    speech = delivery.speech_text
    return tuple(anchor for anchor in delivery.factual_anchors if anchor in speech)


def _validated_speech(candidate: str, delivery: ConversationDelivery,
                       required: tuple[str, ...]) -> str:
    text = _two_sentences(candidate)
    if not text or len(text) > speech_limit():
        return ""
    if any(not _contains_anchor(text, anchor) for anchor in required):
        _logger.info("response_composer.rejected", reason="anchor_mismatch")
        return ""
    # Anchors intentionally omitted by deterministic speech (notably URL/path)
    # must not be promoted into a spoken dump by the optional composer.
    omitted = set(delivery.factual_anchors) - set(required)
    if any(anchor in text for anchor in omitted):
        _logger.info("response_composer.rejected", reason="disallowed_anchor")
        return ""
    return text


def _contains_anchor(text: str, anchor: str) -> bool:
    """Match numeric/word anchors as tokens, not arbitrary substrings."""

    if re.fullmatch(r"[\w.-]+", anchor or ""):
        return bool(re.search(rf"(?<!\w){re.escape(anchor)}(?!\w)", text))
    return anchor in text


def _two_sentences(value: object) -> str:
    cleaned = sanitize_for_speech(value, speech_limit())
    sentences = [match.group(0).strip() for match in _SENTENCE_RE.finditer(cleaned)]
    return " ".join(sentence for sentence in sentences[:speech_sentence_limit()]
                    if sentence)
