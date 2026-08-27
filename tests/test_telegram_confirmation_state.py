"""Task 3 — Telegram confirmation ownership and exact aliases (offline)."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from jarvis.agent.adapters.telegram import (
    ConfirmationStore,
    TelegramService,
)


class FakeClock:
    def __init__(self, value: float = 100.0):
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeMessage:
    def __init__(self, text: str = "", message_id: int = 1):
        self.text = text
        self.message_id = message_id
        self.replies: list[str] = []

    async def reply_text(self, text: str, **_kwargs):
        self.replies.append(text)
        return SimpleNamespace(message_id=99)


class FakeCallback:
    def __init__(self, data: str, text: str = "Pertanyaan"):
        self.data = data
        self.message = SimpleNamespace(text=text)
        self.answers = 0
        self.edits: list[str] = []

    async def answer(self):
        self.answers += 1

    async def edit_message_text(self, text: str):
        self.edits.append(text)


def update(
    chat_id: int, text: str = "", *, callback=None, user_id: int | None = None,
):
    return SimpleNamespace(
        effective_user=SimpleNamespace(
            id=chat_id if user_id is None else user_id),
        effective_chat=SimpleNamespace(id=chat_id),
        message=FakeMessage(text),
        callback_query=callback,
    )


@pytest.fixture
def service(monkeypatch) -> TelegramService:
    from jarvis.agent.adapters import telegram

    monkeypatch.setattr(
        telegram.telegram_control, "allowed_ids", lambda: (42,),
    )
    return TelegramService()


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("ya", "Lanjut"),
        (" IYA ", "Lanjut"),
        ("LANJUT", "Lanjut"),
        ("tidak", "Batal"),
        (" BATAL ", "Batal"),
    ],
)
def test_exact_alias_resolves_without_gateway_task(
    service, typed, expected,
):
    pending = service._confirmations.register(
        42, ["Lanjut", "Batal"], 300,
    )
    routed: list[str] = []
    service.bind_gateway_manager(SimpleNamespace(
        allowed=lambda platform, actor_id: (
            platform == "telegram" and actor_id == "42"),
    ))
    service._receive_gateway_text = lambda _u, text: routed.append(text) or True
    incoming = update(42, typed)

    asyncio.run(service._on_text(incoming, SimpleNamespace()))

    assert pending.future.result() == expected
    assert routed == []
    assert len(service._confirmations) == 0
    assert incoming.message.replies == [f"Konfirmasi diterima: {expected}."]


@pytest.mark.parametrize("typed", ["iya lanjut", "tidak dulu", "yakin", "batal?"])
def test_non_exact_text_reaches_gateway(service, typed):
    service._confirmations.register(42, ["Lanjut", "Batal"], 300)
    routed: list[str] = []
    service.bind_gateway_manager(SimpleNamespace(
        allowed=lambda platform, actor_id: (
            platform == "telegram" and actor_id == "42"),
    ))
    service._receive_gateway_text = lambda _u, text: routed.append(text) or True

    asyncio.run(service._on_text(update(42, typed), SimpleNamespace()))

    assert routed == [typed]
    assert service._confirmations.active_for_chat(42) is not None


def test_confirmation_alias_runs_before_free_text_clarification(service):
    confirmation = service._confirmations.register(
        42, ["Lanjut", "Batal"], 300,
    )
    clarification = Future()
    service._await_text[42] = clarification
    service.bind_gateway_manager(SimpleNamespace(
        allowed=lambda platform, actor_id: (
            platform == "telegram" and actor_id == "42"),
    ))
    routed: list[str] = []
    service._receive_gateway_text = lambda _u, text: routed.append(text) or True

    asyncio.run(service._on_text(update(42, "iya"), SimpleNamespace()))

    assert confirmation.future.result() == "Lanjut"
    assert not clarification.done()
    assert service._await_text[42] is clarification
    assert routed == []


def test_unknown_text_still_resolves_clarification(service):
    clarification = Future()
    service._await_text[42] = clarification
    service.bind_gateway_manager(SimpleNamespace(
        allowed=lambda platform, actor_id: (
            platform == "telegram" and actor_id == "42"),
    ))
    routed: list[str] = []
    service._receive_gateway_text = lambda _u, text: routed.append(text) or True

    asyncio.run(service._on_text(
        update(42, "jelaskan bagian kedua"), SimpleNamespace()))

    assert clarification.result() == "jelaskan bagian kedua"
    assert routed == []
    assert 42 not in service._await_text


def test_command_callback_and_alias_share_cleanup(service):
    by_command = service._confirmations.register(
        42, ["Lanjut", "Batal"], 300, qid="command",
    )
    command_update = update(42)
    asyncio.run(service._cmd_confirm(command_update, SimpleNamespace()))
    assert by_command.future.result() == "Lanjut"
    assert service._confirmations.active_for_chat(42) is None

    by_button = service._confirmations.register(
        42, ["Lanjut", "Batal"], 300, qid="button",
    )
    callback = FakeCallback("ask:button:Batal")
    callback_update = update(42, callback=callback)
    asyncio.run(service._on_callback(callback_update, SimpleNamespace()))
    assert by_button.future.result() == "Batal"
    assert callback.answers == 1
    assert callback.edits == ["Pertanyaan\n→ Batal"]
    assert service._confirmations.active_for_chat(42) is None

    by_alias = service._confirmations.register(
        42, ["Lanjut", "Batal"], 300, qid="alias",
    )
    asyncio.run(service._on_text(update(42, "ya"), SimpleNamespace()))
    assert by_alias.future.result() == "Lanjut"
    assert service._confirmations.active_for_chat(42) is None


def test_double_resolve_is_noop():
    store = ConfirmationStore()
    pending = store.register(42, ["Lanjut", "Batal"], 300, qid="abc")

    first = store.resolve("abc", "Lanjut")
    second = store.resolve("abc", "Batal")

    assert first.resolved is True
    assert second.resolved is False
    assert pending.future.result() == "Lanjut"
    assert len(store) == 0


def test_expiry_cleans_both_indexes_and_resolves_none():
    clock = FakeClock()
    store = ConfirmationStore(now_fn=clock)
    pending = store.register(42, ["Lanjut", "Batal"], 5, qid="abc")

    assert store.expire("abc") is False
    clock.advance(6)
    assert store.expire("abc") is True

    assert pending.future.result() is None
    assert pending.state == "expired"
    assert store.active_for_chat(42) is None
    assert len(store) == 0
    assert store.expire("abc") is False


def test_alias_after_expiry_is_not_consumed_and_cleans_state():
    clock = FakeClock()
    store = ConfirmationStore(now_fn=clock)
    pending = store.register(42, ["Lanjut", "Batal"], 5, qid="abc")
    clock.advance(6)

    assert store.resolve_alias(42, "ya").resolved is False
    assert pending.future.result() is None
    assert pending.state == "expired"
    assert store.active_for_chat(42) is None


def test_callback_resolution_is_bound_to_confirmation_chat(service):
    pending = service._confirmations.register(
        42, ["Lanjut", "Batal"], 300, qid="abc",
    )
    callback = FakeCallback("ask:abc:Lanjut")

    asyncio.run(service._on_callback(
        update(99, callback=callback, user_id=42), SimpleNamespace()))

    assert not pending.future.done()
    assert callback.answers == 1
    assert callback.edits == []
    assert service._confirmations.active_for_chat(42) is pending


def test_replacement_cancels_previous_exactly_once():
    store = ConfirmationStore()
    old = store.register(42, ["Lanjut", "Batal"], 300, qid="old")
    newer = store.register(42, ["Lanjut", "Batal"], 300, qid="new")

    assert old.future.result() is None
    assert old.state == "cancelled"
    assert store.resolve("old", "Lanjut").resolved is False
    assert store.active_for_chat(42) is newer
    assert store.resolve_alias(42, "iya").resolved is True
    assert newer.future.result() == "Lanjut"
    assert len(store) == 0


def test_session_reset_cancels_confirmation_and_clarification(service):
    confirmation = service._confirmations.register(
        42, ["Lanjut", "Batal"], 300,
    )
    clarification = Future()
    service._await_text[42] = clarification

    service._reset_session(42)

    assert confirmation.future.result() is None
    assert clarification.result() is None
    assert service._confirmations.active_for_chat(42) is None
    assert 42 not in service._await_text


def test_unauthorized_alias_is_silent_and_does_not_resolve(service):
    pending = service._confirmations.register(
        42, ["Lanjut", "Batal"], 300,
    )
    incoming = update(999, "ya")

    asyncio.run(service._on_text(incoming, SimpleNamespace()))

    assert not pending.future.done()
    assert incoming.message.replies == []
    assert service._confirmations.active_for_chat(42) is pending
