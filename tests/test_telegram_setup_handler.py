"""Fase 15S end-to-end: Telegram document handler → setup queue → desktop sheet."""
from __future__ import annotations

import asyncio
import json
import types


def _oauth_bytes() -> bytes:
    return json.dumps({
        "installed": {
            "client_id": "abc.apps.googleusercontent.com",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_secret": "HANDLER-SECRET-NOLEAK",
        }
    }).encode()


def _service():
    from jarvis.agent.adapters.telegram import TelegramService
    svc = TelegramService()
    return svc


def _fake_update(*, user_id: int, chat_id: int, filename: str, size: int,
                 downloaded: bytes, replies: list):
    async def _get_file():
        async def _download_to_memory():
            return bytearray(downloaded)
        return types.SimpleNamespace(download_as_bytearray=_download_to_memory)

    document = types.SimpleNamespace(
        file_name=filename, file_size=size, get_file=_get_file)

    async def _reply_text(text):
        replies.append(text)

    message = types.SimpleNamespace(document=document, reply_text=_reply_text)
    return types.SimpleNamespace(
        effective_user=types.SimpleNamespace(id=user_id),
        effective_chat=types.SimpleNamespace(id=chat_id),
        message=message,
    )


def test_document_handler_stages_valid_oauth_and_replies_awaiting(monkeypatch):
    svc = _service()
    monkeypatch.setattr(svc, "_authorized", lambda update: True)
    presented = {}
    monkeypatch.setattr(svc, "_present_setup_on_desktop",
                        lambda request_id: presented.setdefault("id", request_id))

    replies: list = []
    update = _fake_update(user_id=1, chat_id=10, filename="client_secret.json",
                          size=len(_oauth_bytes()), downloaded=_oauth_bytes(), replies=replies)

    asyncio.run(svc._on_document(update, None))

    assert svc._setup_queue.get(presented["id"]) is not None
    joined = " ".join(replies)
    assert "desktop" in joined.lower() or "persetujuan" in joined.lower()
    assert "HANDLER-SECRET-NOLEAK" not in joined
    assert "client_secret" not in joined


def test_document_handler_rejects_unauthorized_silently(monkeypatch):
    svc = _service()
    monkeypatch.setattr(svc, "_authorized", lambda update: False)
    replies: list = []
    update = _fake_update(user_id=999, chat_id=10, filename="client_secret.json",
                          size=len(_oauth_bytes()), downloaded=_oauth_bytes(), replies=replies)

    asyncio.run(svc._on_document(update, None))

    assert replies == []


def test_document_handler_rejects_bad_type_with_reason_code(monkeypatch):
    svc = _service()
    monkeypatch.setattr(svc, "_authorized", lambda update: True)
    replies: list = []
    update = _fake_update(user_id=1, chat_id=10, filename="payload.exe",
                          size=100, downloaded=b"MZ...", replies=replies)

    asyncio.run(svc._on_document(update, None))

    joined = " ".join(replies)
    assert "ditolak" in joined.lower() or "rejected" in joined.lower() or "tidak" in joined.lower()


def test_document_handler_never_leaks_secret_on_bad_payload(monkeypatch):
    svc = _service()
    monkeypatch.setattr(svc, "_authorized", lambda update: True)
    replies: list = []
    web = json.dumps({"web": {"client_secret": "LEAK-XYZ"}}).encode()
    update = _fake_update(user_id=1, chat_id=10, filename="client_secret.json",
                          size=len(web), downloaded=web, replies=replies)

    asyncio.run(svc._on_document(update, None))

    assert "LEAK-XYZ" not in " ".join(replies)


def test_setup_queue_is_shared_singleton_on_service():
    svc = _service()
    assert svc._setup_queue is not None
    from jarvis.agent.remote_setup import SetupQueue
    assert isinstance(svc._setup_queue, SetupQueue)
