"""A58: Telegram text → bounded proposal ingress → BUS metadata-only publish.

Regression: allowlisted remote phrases (e.g. "putar media") were routed
straight into task handling without a local approval step. The fix stages a
bounded proposal via remote_proposal_ingress and publishes only opaque
metadata (proposal_id/actor/session) — never the raw text.
"""
from __future__ import annotations

import asyncio
import types


def _service():
    from jarvis.agent.adapters.telegram import TelegramService
    return TelegramService()


def _fake_update(*, chat_id: int, text: str, replies: list):
    async def _reply_text(value):
        replies.append(value)

    message = types.SimpleNamespace(text=text, message_id=7, reply_text=_reply_text)
    return types.SimpleNamespace(
        effective_user=types.SimpleNamespace(id=1),
        effective_chat=types.SimpleNamespace(id=chat_id),
        message=message,
    )


def _spy_publish(monkeypatch, seen: list):
    from jarvis.core import bus
    original = bus.BUS.publish

    def spy(event, **kwargs):
        if event == "remote_proposal.pending":
            seen.append(kwargs)
        return original(event, **kwargs)

    monkeypatch.setattr(bus.BUS, "publish", spy)


def test_allowlisted_text_is_staged_and_published_metadata_only(monkeypatch):
    from jarvis.agent import remote_proposals

    svc = _service()
    assert svc._gateway_manager is None
    monkeypatch.setattr(svc, "_authorized", lambda update: True)
    seen: list = []
    _spy_publish(monkeypatch, seen)
    replies: list = []
    update = _fake_update(chat_id=42, text="putar media", replies=replies)

    asyncio.run(svc._on_text(update, None))

    assert seen, "harus publish remote_proposal.pending"
    payload = seen[0]
    assert payload["proposal_id"]
    assert payload["actor_id"] == "telegram:42"
    assert payload["session_id"]
    blob = str(payload)
    assert "putar" not in blob and "media" not in blob, \
        "BUS hanya membawa metadata opaque, bukan teks mentah"
    queue = remote_proposals.get_queue()
    staged = queue.get(payload["proposal_id"], actor_id="telegram:42",
                       session_id=payload["session_id"])
    assert staged is not None and staged.action == "media_play"
    joined = " ".join(replies)
    assert "persetujuan" in joined or "menunggu" in joined


def test_unknown_text_never_enters_proposal_lane(monkeypatch):
    svc = _service()
    monkeypatch.setattr(svc, "_authorized", lambda update: True)
    seen: list = []
    _spy_publish(monkeypatch, seen)
    replies: list = []
    update = _fake_update(chat_id=42, text="hello dunia", replies=replies)

    asyncio.run(svc._on_text(update, None))

    assert seen == [], "teks non-allowlist tidak boleh di-stage"


def test_unauthorized_text_is_silent(monkeypatch):
    svc = _service()
    monkeypatch.setattr(svc, "_authorized", lambda update: False)
    seen: list = []
    _spy_publish(monkeypatch, seen)
    replies: list = []
    update = _fake_update(chat_id=42, text="putar media", replies=replies)

    asyncio.run(svc._on_text(update, None))

    assert seen == []
    assert replies == []
