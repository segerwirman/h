"""Fase 8 — Telegram Control native, security, routing, voice, and Settings."""
from __future__ import annotations

import asyncio
import inspect
import os
import sys
import types
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from jarvis.agent.base import ToolResult
from jarvis.agent.router import Route, Tier


def _secret_backend(monkeypatch, *, active: bool = False):
    from jarvis.integrations import telegram_control

    values: dict[str, str] = {}
    settings = {"integrations.telegram.enabled": active}
    monkeypatch.setattr(
        telegram_control.secrets_store, "get", lambda key: values.get(key))
    monkeypatch.setattr(
        telegram_control.secrets_store, "set",
        lambda key, value: values.__setitem__(key, str(value)) or True)
    monkeypatch.setattr(
        telegram_control.secrets_store, "delete",
        lambda key: values.pop(key, None) is not None or True)
    monkeypatch.setattr(
        telegram_control.secrets_store, "backend_label", lambda: "Test encrypted")
    monkeypatch.setattr(
        telegram_control.config, "get",
        lambda key, default=None: settings.get(key, default))

    def _write(key, value):
        settings[key] = value
        return True

    monkeypatch.setattr(telegram_control.config_write, "set_scalar", _write)
    return telegram_control, values, settings


def test_credentials_are_namespaced_encrypted_and_gate_start(monkeypatch):
    control, values, settings = _secret_backend(monkeypatch)

    assert control.enabled() is False
    assert control.set_enabled(True).ok is False
    result = control.save_credentials("123456:bot-token", "42, 42; 77")

    assert result.ok is True
    assert values == {
        control.TOKEN_SECRET: "123456:bot-token",
        control.ALLOWED_IDS_SECRET: "42,77",
    }
    assert control.enabled() is False  # master toggle is behavioral
    assert control.set_enabled(True).ok is True
    assert settings["integrations.telegram.enabled"] is True
    assert control.enabled() is True

    config_text = Path("config.yaml").read_text(encoding="utf-8")
    telegram_block = config_text.split("  telegram:", 1)[1].split("  youtube:", 1)[0]
    assert "bot-token" not in config_text
    assert "allowed_ids" not in telegram_block
    ignored = Path(".gitignore").read_text(encoding="utf-8")
    for item in (".env", "config/api_keys.json", ".jarvis/.keyfile",
                 ".jarvis/secrets.dat"):
        assert item in ignored


def test_invalid_allowlist_never_enables(monkeypatch):
    control, values, _settings = _secret_backend(monkeypatch, active=True)
    assert control.save_credentials("token", "42, everyone").ok is False
    assert values == {}
    assert control.enabled() is False


def test_apply_runtime_uses_manager_bound_telegram_runtime(monkeypatch):
    from jarvis.gateway import runtime
    from jarvis.integrations import telegram_control

    calls = []

    class Runtime:
        def stop(self):
            calls.append("stop")

        def start(self):
            calls.append("start")
            return True

    monkeypatch.setattr(telegram_control, "enabled", lambda: True)
    monkeypatch.setattr(telegram_control.release_controls, "current", lambda: {"gateway": True})
    monkeypatch.setattr(runtime, "telegram_runtime", lambda: Runtime())

    assert telegram_control.apply_runtime() is True
    assert calls == ["stop", "start"]


def test_start_runtime_uses_manager_bound_telegram_runtime(monkeypatch):
    from jarvis.gateway import runtime
    from jarvis.integrations import telegram_control

    calls = []

    class Runtime:
        def start(self):
            calls.append("start")
            return True

    monkeypatch.setattr(telegram_control, "enabled", lambda: True)
    monkeypatch.setattr(telegram_control, "allowed_ids", lambda: ())
    monkeypatch.setattr(telegram_control.release_controls, "current", lambda: {"gateway": True})
    monkeypatch.setattr(runtime, "telegram_runtime", lambda: Runtime())

    assert telegram_control.start_runtime() is True
    assert calls == ["start"]


def test_start_runtime_menolak_transport_saat_release_gateway_off(monkeypatch):
    from jarvis.gateway import runtime
    from jarvis.integrations import telegram_control

    calls = []

    class Runtime:
        def start(self):
            calls.append("start")
            return True

    monkeypatch.setattr(telegram_control, "enabled", lambda: True)
    monkeypatch.setattr(telegram_control.release_controls, "current", lambda: {"gateway": False})
    monkeypatch.setattr(runtime, "telegram_runtime", lambda: Runtime())

    assert telegram_control.start_runtime() is False
    assert calls == []


def test_apply_runtime_gateway_off_berhenti_tanpa_memulai_transport(monkeypatch):
    from jarvis.gateway import runtime
    from jarvis.integrations import telegram_control

    calls = []

    class Runtime:
        def stop(self):
            calls.append("stop")

        def start(self):
            calls.append("start")
            return True

    monkeypatch.setattr(telegram_control, "enabled", lambda: True)
    monkeypatch.setattr(telegram_control.release_controls, "current", lambda: {"gateway": False})
    monkeypatch.setattr(runtime, "telegram_runtime", lambda: Runtime())

    assert telegram_control.apply_runtime() is True
    assert calls == ["stop"]


def test_start_runtime_bootstraps_locally_configured_ids_as_durable_pairs(monkeypatch):
    from jarvis.gateway import runtime
    from jarvis.integrations import telegram_control

    pairs = []

    class Runtime:
        class Manager:
            def pair(self, platform, actor_id, *, paired_by):
                pairs.append((platform, actor_id, paired_by))
                return True

        manager = Manager()

        def start(self):
            return True

    monkeypatch.setattr(telegram_control, "enabled", lambda: True)
    monkeypatch.setattr(telegram_control, "allowed_ids", lambda: (42, 77))
    monkeypatch.setattr(telegram_control.release_controls, "current", lambda: {"gateway": True})
    monkeypatch.setattr(runtime, "telegram_runtime", lambda: Runtime())

    assert telegram_control.start_runtime() is True
    assert pairs == [
        ("telegram", "42", "local-telegram-config"),
        ("telegram", "77", "local-telegram-config"),
    ]


def test_legacy_env_is_scrubbed_only_after_encrypted_migration(
        monkeypatch, tmp_path):
    control, values, settings = _secret_backend(monkeypatch)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "KEEP_ME=yes\nTG_BOT_TOKEN=legacy-token\n"
        "TG_ALLOWED_IDS=42\nTG_NOTIFY_CHAT_ID=42\n",
        encoding="utf-8")
    monkeypatch.setattr(control.config, "base_dir", lambda: tmp_path)
    monkeypatch.setenv("TG_BOT_TOKEN", "legacy-token")
    monkeypatch.setenv("TG_ALLOWED_IDS", "42")

    assert control.migrate_legacy() is True

    assert values[control.TOKEN_SECRET] == "legacy-token"
    assert values[control.ALLOWED_IDS_SECRET] == "42"
    assert settings["integrations.telegram.enabled"] is True
    assert env_path.read_text(encoding="utf-8") == "KEEP_ME=yes\n"
    assert "TG_BOT_TOKEN" not in os.environ
    assert "TG_ALLOWED_IDS" not in os.environ


class _Message:
    def __init__(self, text: str = ""):
        self.text = text
        self.replies: list[str] = []
        self.documents: list[str] = []
        self.photos: list[object] = []

    async def reply_text(self, text: str, **_kwargs):
        self.replies.append(text)
        return SimpleNamespace(message_id=91)

    async def reply_document(self, _document, caption: str = ""):
        self.documents.append(caption)

    async def reply_photo(self, photo):
        self.photos.append(photo)


def _update(user_id: int, text: str = "", *, message=None):
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=user_id),
        message=message or _Message(text),
    )


def test_allowlist_is_first_and_unauthorized_user_gets_total_silence(monkeypatch):
    from jarvis.agent.adapters import telegram

    monkeypatch.setattr(telegram.telegram_control, "allowed_ids", lambda: (42,))
    service = telegram.TelegramService()
    reached = []

    async def _task(*args):
        reached.append(args)

    monkeypatch.setattr(service, "_handle_task", _task)
    update = _update(999, "analisis repo")
    asyncio.run(service._on_text(update, SimpleNamespace()))

    assert reached == []
    assert update.message.replies == []


def test_allowlisted_t1_uses_same_router_and_native_light_executor(monkeypatch):
    from jarvis.agent.adapters import telegram, telegram_light
    from jarvis.agent import dispatch

    route = Route(Tier.SINGLE, "light", "light", "single search query", 1.0)
    seen = {}
    monkeypatch.setattr(telegram.telegram_control, "allowed_ids", lambda: (42,))
    monkeypatch.setattr(
        telegram, "classify_execution",
        lambda text, context: seen.update(text=text, context=context) or route)
    monkeypatch.setattr(
        telegram_light, "execute",
        lambda text, chosen, *, context=None: _async_result(
            seen.update(light=(text, chosen, context)) or ToolResult.success("hasil native")))
    monkeypatch.setattr(
        dispatch, "dispatch_async",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("T1 must not enter the agent loop")))

    update = _update(42, "cari cuaca Bandung")
    asyncio.run(telegram.TelegramService()._on_text(update, SimpleNamespace()))

    assert seen["context"] == {"source": "telegram"}
    assert seen["light"] == ("cari cuaca Bandung", route, None)
    assert update.message.replies == ["hasil native"]


def test_light_image_result_is_delivered_as_telegram_photo(monkeypatch, tmp_path):
    from jarvis.agent.adapters import telegram, telegram_light
    from jarvis.agent.base import ToolResult

    image = tmp_path / "generated.png"
    image.write_bytes(b"png")
    monkeypatch.setattr(
        telegram, "classify_execution",
        lambda *_args: Route(Tier.SINGLE, "light", "light", "single image generation", 1.0),
    )
    monkeypatch.setattr(
        telegram_light, "execute",
        lambda *_args, **_kwargs: _async_result(
            ToolResult.success("gambar tersimpan", paths=[str(image)])
        ),
    )
    update = _update(42, "buatkan gambar robot")

    asyncio.run(telegram.TelegramService()._handle_task(update, "buatkan gambar robot"))

    assert update.message.replies == ["gambar tersimpan"]
    assert len(update.message.photos) == 1


async def _async_result(value):
    return value


def test_heavy_ack_progress_final_reuses_same_message(monkeypatch):
    from jarvis.agent.adapters import telegram
    from jarvis.agent import dispatch

    monkeypatch.setattr(
        telegram, "classify_execution",
        lambda *_a, **_k: Route(Tier.AGENT, "heavy", "heavy", "test", 1.0))

    def _dispatch(_task, **kwargs):
        kwargs["on_ack"]("Baik, sedang saya kerjakan.")
        kwargs["on_done"]("Laporan selesai.")
        return True

    monkeypatch.setattr(dispatch, "dispatch_async", _dispatch)
    service = telegram.TelegramService()
    edits = []
    monkeypatch.setattr(
        service, "edit_result",
        lambda chat, message, text: edits.append((chat, message, text)))
    monkeypatch.setattr(
        service, "send_text",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("final must edit the ACK message")))
    update = _update(42, message=_Message())

    asyncio.run(service._handle_task(update, "analisis repo ini"))

    assert update.message.replies == ["Baik, sedang saya kerjakan."]
    assert edits and edits[0][:2] == (42, 91)
    assert "Laporan selesai" in edits[0][2]


def test_long_output_becomes_markdown_document(monkeypatch, tmp_path):
    from jarvis.agent.adapters import telegram

    service = telegram.TelegramService()
    sent = []
    path = tmp_path / "result.md"
    path.write_text("x", encoding="utf-8")
    monkeypatch.setattr(service, "_markdown_file", lambda _text: str(path))
    monkeypatch.setattr(
        service, "send_document",
        lambda chat, document, caption="": sent.append(
            (chat, document, caption)))

    service.send_text(42, "x" * 4001)

    assert sent == [(42, str(path), "Hasil lengkap dikirim sebagai Markdown.")]


def test_voice_note_wraps_frozen_stt_and_reenters_router(monkeypatch, tmp_path):
    from jarvis.agent.adapters import jarvis_voice, telegram
    from jarvis.agent import paths

    monkeypatch.setattr(telegram.telegram_control, "allowed_ids", lambda: (42,))
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    seen = []
    monkeypatch.setattr(
        jarvis_voice, "transcribe", lambda path: seen.append(Path(path)) or "halo")

    class Voice:
        file_size = 100

        async def get_file(self):
            async def _download(target):
                Path(target).write_bytes(b"ogg")
            return SimpleNamespace(download_to_drive=_download)

    message = _Message()
    message.voice = Voice()
    update = _update(42, message=message)
    routed = []
    service = telegram.TelegramService()

    async def _handle(_update, text):
        routed.append(text)

    monkeypatch.setattr(service, "_handle_task", _handle)
    asyncio.run(service._on_voice(update, SimpleNamespace()))

    assert routed == ["halo"]
    assert message.replies == ['🎙 "halo"']
    assert seen and not seen[0].exists()
    source = Path("jarvis/agent/adapters/jarvis_voice.py").read_text(encoding="utf-8")
    assert "from core.stt import WhisperSTT" in source


def test_confirm_command_and_session_reset_are_functional(monkeypatch):
    from jarvis.agent.adapters import telegram

    monkeypatch.setattr(telegram.telegram_control, "allowed_ids", lambda: (42,))
    service = telegram.TelegramService()
    future = Future()
    service._pending["abc"] = future
    service._pending_chat["abc"] = 42
    service._pending_confirm[42] = "abc"
    update = _update(42)

    asyncio.run(service._cmd_confirm(update, SimpleNamespace(args=[])))
    first = service._session_id(42)
    second = service._reset_session(42)

    assert future.result() == "Lanjut"
    assert "diterima" in update.message.replies[0].lower()
    assert first != second


def test_screen_todo_and_stop_commands_execute(monkeypatch, tmp_path):
    from jarvis.agent.adapters import telegram
    from jarvis.agent import dispatch, paths

    monkeypatch.setattr(telegram.telegram_control, "allowed_ids", lambda: (42,))
    monkeypatch.setattr(paths, "generated_dir", lambda: tmp_path)
    monkeypatch.setattr(dispatch, "cancel_all", lambda: 3)
    fake_session = SimpleNamespace(todos=[
        {"status": "in_progress", "content": "uji Telegram"}])
    monkeypatch.setattr(
        dispatch, "_active", {"test": SimpleNamespace(session=fake_session)})

    tools = types.ModuleType("mss.tools")

    def _png(_rgb, _size, output):
        Path(output).write_bytes(b"png")

    tools.to_png = _png
    module = types.ModuleType("mss")
    module.__path__ = []
    module.tools = tools

    class Capture:
        monitors = [None, "primary"]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def grab(self, _monitor):
            return SimpleNamespace(rgb=b"rgb", size=(1, 1))

    module.mss = Capture
    monkeypatch.setitem(sys.modules, "mss", module)
    monkeypatch.setitem(sys.modules, "mss.tools", tools)
    service = telegram.TelegramService()

    stop_update = _update(42)
    todo_update = _update(42)
    screen_update = _update(42)
    asyncio.run(service._cmd_stop(stop_update, SimpleNamespace(args=[])))
    asyncio.run(service._cmd_todo(todo_update, SimpleNamespace(args=[])))
    asyncio.run(service._cmd_screen(screen_update, SimpleNamespace(args=[])))

    assert stop_update.message.replies == ["3 tugas dibatalkan."]
    assert "uji Telegram" in todo_update.message.replies[0]
    assert len(screen_update.message.photos) == 1


def test_all_required_commands_are_registered_and_guarded_first():
    from jarvis.agent.adapters import telegram

    source = inspect.getsource(telegram.TelegramService._main)
    for command in ("help", "status", "tools", "stop", "todo", "memory",
                    "cron", "screen", "skills", "session", "confirm"):
        assert f'CommandHandler("{command}"' in source
        handler = getattr(telegram.TelegramService, f"_cmd_{command}")
        first_lines = inspect.getsource(handler).splitlines()[1:4]
        assert any("_authorized" in line for line in first_lines)


def test_command_menu_matches_registered_telegram_commands():
    from jarvis.agent.adapters import telegram

    commands = dict(telegram.command_menu())

    assert set(commands) >= {
        "start", "help", "status", "tools", "stop", "todo", "memory",
        "cron", "screen", "skills", "session", "confirm",
    }
    assert all(description for description in commands.values())


def test_unknown_telegram_command_returns_help_hint(monkeypatch):
    from jarvis.agent.adapters import telegram

    monkeypatch.setattr(telegram.telegram_control, "allowed_ids", lambda: (42,))
    update = _update(42, "/tidak_ada")

    asyncio.run(
        telegram.TelegramService()._on_unknown_command(update, SimpleNamespace())
    )

    assert update.message.replies == [
        "Perintah tidak dikenal. Ketik / untuk menu atau /help untuk bantuan."
    ]


def test_connection_uses_ptb_sdk_and_returns_bot_name(monkeypatch):
    import telegram as ptb
    from jarvis.integrations import telegram_control

    monkeypatch.setattr(telegram_control, "token", lambda: "secret")
    monkeypatch.setattr(telegram_control, "allowed_ids", lambda: (42,))

    class Bot:
        def __init__(self, token):
            assert token == "secret"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get_me(self):
            return SimpleNamespace(username="jarvis_mk50_bot")

    monkeypatch.setattr(ptb, "Bot", Bot)
    result = asyncio.run(telegram_control.test_connection())
    assert result.ok is True
    assert result.bot_name == "jarvis_mk50_bot"


_QT_APP = None


def test_messaging_settings_uses_layouts_mask_and_real_toggle(monkeypatch):
    global _QT_APP
    from PyQt6.QtWidgets import QApplication, QFormLayout, QLineEdit, QWidget
    from jarvis.ui.settings_messaging import MessagingSettingsSheet
    from jarvis.integrations import telegram_control

    _QT_APP = QApplication.instance() or QApplication([])
    state = {
        "configured": False, "token_saved": False, "allowed_count": 0,
        "master_enabled": False, "running": False,
        "state": "Not configured", "backend": "Test encrypted",
    }
    monkeypatch.setattr(telegram_control, "status", lambda: dict(state))
    monkeypatch.setattr(telegram_control, "credentials_ready", lambda: False)
    host = QWidget()
    sheet = MessagingSettingsSheet(host)

    assert sheet.findChild(QFormLayout) is not None
    assert sheet._token.echoMode() is QLineEdit.EchoMode.Password
    assert sheet._master.isEnabled() is False
    assert sheet._token_badge.text() == "NOT SAVED"
    sheet.open_centered(900, 600)
    _QT_APP.processEvents()
    assert not sheet._token.geometry().intersects(sheet._allowed.geometry())
    assert not sheet._save_button.geometry().intersects(
        sheet._test_button.geometry())


def test_messaging_settings_shows_light_lane_and_restart_control(monkeypatch):
    global _QT_APP
    from PyQt6.QtWidgets import QApplication, QWidget
    from jarvis.agent import model_routing
    from jarvis.ui.settings_messaging import MessagingSettingsSheet
    from jarvis.integrations import telegram_control

    _QT_APP = QApplication.instance() or QApplication([])
    monkeypatch.setattr(telegram_control, "status", lambda: {
        "configured": True, "token_saved": True, "allowed_count": 1,
        "master_enabled": True, "running": True,
        "state": "Connected", "backend": "Test encrypted",
    })
    monkeypatch.setattr(telegram_control, "credentials_ready", lambda: True)
    monkeypatch.setattr(model_routing, "role_statuses", lambda: {
        "light": {"provider": "openai_oauth", "model": "gpt-light",
                  "configured": True, "reason": "routing.light: openai_oauth"},
    })

    host = QWidget()
    sheet = MessagingSettingsSheet(host)

    assert "LIGHT LANE: openai_oauth (gpt-light)" == sheet._light_status.text()
    assert sheet._restart_button.text() == "RESTART TELEGRAM GATEWAY"


def test_active_telegram_runtime_has_no_hermes_imports():
    for path in (
        "jarvis/agent/adapters/telegram.py",
        "jarvis/agent/adapters/telegram_light.py",
        "jarvis/integrations/telegram_control.py",
    ):
        source = Path(path).read_text(encoding="utf-8").casefold()
        assert "hermes" not in source
