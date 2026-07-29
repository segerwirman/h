"""Fase 11 — Telegram is registered behind the formal gateway boundary."""
from __future__ import annotations

import importlib


def test_telegram_gateway_menggunakan_dedup_sebelum_handler():
    try:
        telegram = importlib.import_module("jarvis.gateway.platforms.telegram")
    except ModuleNotFoundError:
        telegram = None

    assert telegram is not None
    received = []
    adapter = telegram.TelegramGateway(lambda inbound: received.append(inbound.text))

    assert adapter.receive("m1", "chat", "user", "halo") is True
    assert adapter.receive("m1", "chat", "user", "halo") is False
    assert received == ["halo"]
    assert adapter.toolsets == frozenset({"messaging"})


def test_live_telegram_text_didelegasikan_ke_gateway_manager(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from jarvis.agent.adapters import telegram

    class Manager:
        def __init__(self):
            self.calls = []

        def receive(self, *args):
            self.calls.append(args)
            return False

    message = SimpleNamespace(message_id=17, text="analisis status", replies=[])
    async def _reply(text, **_kwargs):
        message.replies.append(text)
    message.reply_text = _reply
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(id=99),
        message=message,
    )
    service = telegram.TelegramService(gateway_manager=Manager())
    monkeypatch.setattr(service, "_handle_task", lambda *_args: (
        _ for _ in ()).throw(AssertionError("manager denied ingress")))

    asyncio.run(service._on_text(update, SimpleNamespace()))

    assert service._gateway_manager.calls == [
        ("telegram", "17", "99", "42", "analisis status")]
    assert message.replies == []


def test_telegram_polling_tidak_membuang_update_paired_saat_startup():
    from jarvis.agent.adapters import telegram

    assert telegram.polling_options()["drop_pending_updates"] is False


def test_text_manager_bound_merekam_accepted_lalu_deduplicated(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from jarvis.agent.adapters import telegram
    from jarvis.gateway.authz import GatewayAuthz
    from jarvis.gateway.runtime import TelegramGatewayRuntime

    message = SimpleNamespace(message_id=17, text="harmless validation")
    message.reply_text = lambda *_args, **_kwargs: None
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(id=99), message=message,
    )
    service = telegram.TelegramService()
    runtime = TelegramGatewayRuntime(
        service=service, authz=GatewayAuthz(tmp_path / "gateway.sqlite"))
    assert runtime.manager.pair("telegram", "42")

    async def scenario():
        await service._on_text(update, SimpleNamespace())
        await service._on_text(update, SimpleNamespace())

    asyncio.run(scenario())

    assert [item["action"] for item in runtime.manager.recent_events()] == [
        "ingress.accepted", "ingress.deduplicated",
    ]


def test_telegram_remote_stop_command_ditolak_tanpa_membatalkan_task(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from jarvis.agent.adapters import telegram
    from jarvis.agent import dispatch

    class Manager:
        def allowed(self, _platform, _actor_id):
            return True

    cancelled = []
    monkeypatch.setattr(dispatch, "cancel_all", lambda: cancelled.append(True) or 7)
    message = SimpleNamespace(replies=[])

    async def reply_text(text, **_kwargs):
        message.replies.append(text)

    message.reply_text = reply_text
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42), message=message)
    asyncio.run(telegram.TelegramService(gateway_manager=Manager())._cmd_stop(update, SimpleNamespace()))

    assert cancelled == []
    assert message.replies == ["Perintah remote ini harus disetujui dari desktop lokal."]


def test_telegram_runtime_mengikat_lifecycle_service_ke_manager(tmp_path):
    from jarvis.gateway.authz import GatewayAuthz
    from jarvis.gateway.runtime import TelegramGatewayRuntime

    class Service:
        name = "telegram"

        def __init__(self):
            self.running = False
            self.bound = None

        def bind_gateway_manager(self, manager):
            self.bound = manager

        def start(self):
            self.running = True
            return True

        def stop(self):
            self.running = False

        def health(self):
            return {"state": "connected" if self.running else "stopped"}

    service = Service()
    runtime = TelegramGatewayRuntime(
        service=service, authz=GatewayAuthz(tmp_path / "gateway.sqlite"))

    assert service.bound is runtime.manager
    assert runtime.start() is True
    assert runtime.manager.health()["telegram"]["state"] == "connected"
    runtime.stop()
    assert service.running is False


def test_telegram_manager_yang_menerima_menjalankan_task_dengan_context_remote(tmp_path):
    import asyncio
    from types import SimpleNamespace
    from jarvis.agent.adapters import telegram
    from jarvis.gateway.authz import GatewayAuthz
    from jarvis.gateway.runtime import TelegramGatewayRuntime

    async def scenario():
        service = telegram.TelegramService()
        authz = GatewayAuthz(tmp_path / "gateway.sqlite")
        runtime = TelegramGatewayRuntime(service=service, authz=authz)
        assert authz.pair("telegram", "42")
        seen = []

        async def _task(update, text, context):
            seen.append((update, text, context))

        service._handle_task = _task
        message = SimpleNamespace(message_id=17, text="ringkas status")
        message.reply_text = lambda *_args, **_kwargs: None
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=42),
            effective_chat=SimpleNamespace(id=99), message=message,
        )

        await service._on_text(update, SimpleNamespace())
        await asyncio.sleep(0)
        return seen

    seen = asyncio.run(scenario())
    assert len(seen) == 1
    assert seen[0][1] == "ringkas status"
    assert seen[0][2].source == "telegram"
    assert seen[0][2].surface == "remote"
    assert "desktop-control" not in seen[0][2].toolsets


def test_control_telegram_terikat_manager_memakai_pairing_durable(monkeypatch):
    from types import SimpleNamespace
    from jarvis.agent.adapters import telegram

    class Manager:
        def allowed(self, platform, actor_id):
            return (platform, actor_id) == ("telegram", "42")

    monkeypatch.setattr(telegram.telegram_control, "allowed_ids", lambda: ())
    service = telegram.TelegramService(gateway_manager=Manager())
    update = SimpleNamespace(effective_user=SimpleNamespace(id=42))

    assert service._authorized(update) is True


def test_text_klarifikasi_telegram_memenuhi_future_tanpa_menjadi_task_baru():
    import asyncio
    from concurrent.futures import Future
    from types import SimpleNamespace
    from jarvis.agent.adapters import telegram

    class Manager:
        def allowed(self, _platform, _actor_id):
            return True

        def receive(self, *_args):
            raise AssertionError("clarification reply must not dispatch a new task")

    service = telegram.TelegramService(gateway_manager=Manager())
    waiting = Future()
    service._await_text[99] = waiting
    message = SimpleNamespace(message_id=17, text="jawaban klarifikasi")
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=42),
        effective_chat=SimpleNamespace(id=99), message=message,
    )

    asyncio.run(service._on_text(update, SimpleNamespace()))

    assert waiting.result() == "jawaban klarifikasi"
