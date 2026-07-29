"""Conversation, durable-memory, and sub-agent continuity boundaries."""
from __future__ import annotations

import asyncio

import pytest


@pytest.fixture()
def isolated_memory(tmp_path, monkeypatch):
    from jarvis.agent import memory_store

    monkeypatch.setattr(memory_store, "db_path", lambda: tmp_path / "agent.sqlite")
    monkeypatch.setattr(memory_store, "_embed", lambda _texts: None)
    return memory_store


def _remote_context(actor: str):
    from jarvis.agent.execution_context import ExecutionContext

    return ExecutionContext.create(
        source="telegram",
        actor_id=actor,
        session_id="chat-1",
        surface="remote",
        toolsets={"agent", "memory", "messaging", "skills", "web"},
    )


def test_system_prompt_retrieves_only_same_remote_actor_memory(
    isolated_memory, monkeypatch,
):
    from jarvis.agent import loop

    isolated_memory.write(
        "semantic", "Preferensi rahasia actor A", scope="platform-actor",
        owner="telegram:actor-a",
    )
    isolated_memory.write(
        "semantic", "Preferensi rahasia actor B", scope="platform-actor",
        owner="telegram:actor-b",
    )
    monkeypatch.setattr(isolated_memory, "get_reflective", lambda **_kwargs: [])

    prompt = loop._system_prompt(
        "ingat preferensi", "telegram", execution_context=_remote_context("actor-a"),
    )

    assert "actor A" in prompt
    assert "actor B" not in prompt


def test_memory_tool_remote_write_is_scoped_to_the_same_actor(isolated_memory):
    from jarvis.agent.tools.memory_tools import MemoryWrite

    result = asyncio.run(MemoryWrite().run(
        "Saya suka jawaban singkat.", _context=_remote_context("actor-a"),
    ))

    assert result.ok is True
    assert isolated_memory.search(
        "jawaban singkat", scope="platform-actor", owner="telegram:actor-a",
    )
    assert isolated_memory.search(
        "jawaban singkat", scope="platform-actor", owner="telegram:actor-b",
    ) == []


def test_memory_tool_rejects_sensitive_content(isolated_memory):
    from jarvis.agent.tools.memory_tools import MemoryWrite

    result = asyncio.run(MemoryWrite().run(
        "access_token=secret-value", _context=_remote_context("actor-a"),
    ))

    assert result.ok is False


def test_telegram_memory_command_is_scoped_to_effective_actor(monkeypatch):
    from types import SimpleNamespace
    from jarvis.agent.adapters.telegram import TelegramService
    from jarvis.agent import memory_store

    seen = {}

    def search(query, mtype=None, limit=8, **kwargs):
        seen.update(query=query, mtype=mtype, limit=limit, **kwargs)
        return [{"type": "semantic", "content": "Preferensi actor yang benar"}]

    service = TelegramService()
    monkeypatch.setattr(service, "_authorized", lambda _update: True)
    monkeypatch.setattr(memory_store, "search", search)
    replies = []

    async def reply_text(text):
        replies.append(text)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=777),
        effective_chat=SimpleNamespace(id=101),
        message=SimpleNamespace(reply_text=reply_text),
    )
    context = SimpleNamespace(args=["preferensi"])

    asyncio.run(service._cmd_memory(update, context))

    assert seen == {
        "query": "preferensi", "mtype": None, "limit": 6,
        "scope": "platform-actor", "owner": "telegram:777",
    }
    assert replies == ["[semantic] Preferensi actor yang benar"]


def test_subagent_inherits_bounded_parent_conversation_context(monkeypatch):
    from jarvis.agent.adapters.base import NullAdapter
    from jarvis.agent.base import ToolResult
    from jarvis.agent.session import Session
    from jarvis.agent.tools.delegate import DelegateTask

    captured = {}

    async def fake_run(task, **kwargs):
        captured.update(task=task, context=kwargs.get("context"))
        return type("Result", (), {"ok": True, "text": "selesai", "iterations": 1})()

    from jarvis.agent import loop
    monkeypatch.setattr(loop, "run", fake_run)
    parent = Session(task="Riset framework agent dan buat laporan", adapter_name="telegram")
    parent.conversation_context = (
        "Tugas sebelumnya: bandingkan framework agent. "
        "Hasil terakhir: dua kandidat sudah dipilih."
    )
    context = _remote_context("actor-a")

    result = asyncio.run(DelegateTask().run(
        "verifikasi kandidat pertama", _session=parent, _adapter=NullAdapter(),
        _context=context,
    ))

    assert result.ok is True
    assert "Tugas sebelumnya: bandingkan framework agent" in captured["task"]
    assert captured["context"].source == "telegram"
    assert captured["context"].actor_id == "actor-a"


def test_voice_context_tracks_active_task_until_success():
    from jarvis.agent.conversation_context import ConversationContextStore
    from jarvis.agent.interaction import ConversationDelivery

    store = ConversationContextStore()
    store.begin_task("voice-live", "buat laporan status proyek")

    assert store.active_task("voice-live") == "buat laporan status proyek"

    store.remember_success(
        "voice-live", task="buat laporan status proyek",
        delivery=ConversationDelivery(
            display_text="Laporan selesai di C:/private/report.txt",
            speech_text="Laporan status proyek selesai, sir.",
            factual_anchors=("proyek",),
        ),
    )

    assert store.active_task("voice-live") == ""
    assert "laporan status proyek" in store.augment("voice-live", "lanjutkan")
