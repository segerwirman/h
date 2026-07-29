"""Focused Phase 1 tests for the shared tier-router dispatch seams."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

from jarvis.agent.router import Route, Tier


def _route(tier: Tier, reason: str = "test route") -> Route:
    heavy = tier >= Tier.AGENT
    return Route(
        tier=tier,
        lane="heavy" if heavy else "light",
        model_profile="heavy" if heavy else "light",
        reason=reason,
        confidence=1.0,
    )


class _ReplyFlow:
    def handle_utterance(self, _text: str) -> bool:
        return False


def _window_module():
    import jarvis.ui.window as window
    return window


def _typed_window() -> SimpleNamespace:
    legacy = SimpleNamespace(calls=[])

    def _legacy_classify(text: str):
        from jarvis.core.router import Intent

        legacy.calls.append(text)
        return SimpleNamespace(intent=Intent.CHAT, slots={})

    legacy.classify = _legacy_classify
    fake = SimpleNamespace(
        _CONFIRM_WORDS=("confirm", "konfirmasi"),
        _CANCEL_WORDS=("cancel", "batalkan aksi"),
        _pending_close_decision=None,
        _skip_next_intercept=False,
        reply_flow=_ReplyFlow(),
        router=legacy,
        logs=[],
        agent_tasks=[],
        dispatched=[],
    )
    fake.write_log = fake.logs.append
    # DIAGNOSIS_2 MASALAH 2 menambahkan langkah "jawaban klarifikasi" di awal
    # handle_command. Metode ASLI-nya dipasang ke stub (bukan no-op) agar
    # jalur baru itu ikut teruji: tanpa pertanyaan tertunda ia mengembalikan
    # False dan routing berjalan seperti sebelumnya.
    fake._handle_clarify_answer = (
        lambda text: _window_module().MainWindow._handle_clarify_answer(
            fake, text)
    )
    # Idem untuk konfirmasi "matikan dirimu" (DIAGNOSIS_2 MASALAH 3): tanpa
    # permintaan tertunda, metode aslinya mengembalikan False dan routing
    # berjalan seperti sebelumnya.
    fake._confirm_self_shutdown = (
        lambda text: _window_module().MainWindow._confirm_self_shutdown(
            fake, text)
    )
    fake._run_agent_native = fake.agent_tasks.append
    fake._try_in_frame_agent = lambda _text, _intent: False
    fake._dispatch_command = (
        lambda _intent, text: fake.dispatched.append(text)
    )
    return fake


def test_typed_heavy_uses_native_agent_before_legacy_intent(monkeypatch):
    import jarvis.ui.window as window

    seen = {}
    monkeypatch.setattr(window, "_agent_ask_active", lambda: False)
    monkeypatch.setattr(window.BUS, "publish", lambda *a, **k: None)
    monkeypatch.setattr(
        window,
        "classify_execution",
        lambda text, context: (
            seen.update(text=text, context=context) or _route(Tier.AGENT)
        ),
    )
    fake = _typed_window()

    window.MainWindow.handle_command(fake, "riset lalu buat tabel")

    assert seen == {
        "text": "riset lalu buat tabel",
        "context": {"source": "text"},
    }
    assert fake.agent_tasks == ["riset lalu buat tabel"]
    assert fake.router.calls == []
    assert fake.dispatched == []


def test_typed_light_preserves_legacy_intent_path(monkeypatch):
    import jarvis.ui.window as window

    monkeypatch.setattr(window, "_agent_ask_active", lambda: False)
    monkeypatch.setattr(window.BUS, "publish", lambda *a, **k: None)
    monkeypatch.setattr(
        window, "classify_execution",
        lambda _text, context: _route(Tier.SINGLE),
    )
    fake = _typed_window()

    window.MainWindow.handle_command(fake, "jam berapa")

    assert fake.agent_tasks == []
    assert fake.router.calls == ["jam berapa"]
    assert fake.dispatched == ["jam berapa"]


def test_light_legacy_messaging_intent_uses_native_agent(monkeypatch):
    import jarvis.ui.window as window
    from jarvis.agent.adapters import telegram

    monkeypatch.setattr(
        telegram.TelegramService,
        "get",
        classmethod(lambda cls: SimpleNamespace(running=False)),
    )
    fake = SimpleNamespace(logs=[], spoken=[], agent_tasks=[])
    fake.write_log = fake.logs.append
    fake._speak_line = fake.spoken.append
    fake._run_agent_native = fake.agent_tasks.append

    window.MainWindow.run_native_task(
        fake,
        {
            "tier": 2,
            "action": "send",
            "platform": "telegram",
            "text": "halo",
        },
        "kirim pesan ke telegram: halo",
    )

    assert fake.agent_tasks
    assert "adapter native telegram" in fake.agent_tasks[0].lower()


def test_dispatch_command_uses_native_messaging_boundary():
    import jarvis.ui.window as window
    from jarvis.core.router import Intent

    seen = {}
    fake = SimpleNamespace(
        run_native_task=lambda slots, text: seen.update(
            slots=slots, text=text
        )
    )
    classified = SimpleNamespace(
        intent=Intent.NATIVE_AGENT_TASK,
        slots={"tier": 2, "action": "send"},
    )

    window.MainWindow._dispatch_command(fake, classified, "kirim pesan")

    assert seen["text"] == "kirim pesan"


def test_typed_single_message_keeps_tier_router_authoritative(monkeypatch):
    import jarvis.ui.window as window
    from jarvis.core.router import IntentRouter

    monkeypatch.setattr(window, "_agent_ask_active", lambda: False)
    monkeypatch.setattr(window.BUS, "publish", lambda *a, **k: None)
    fake = _typed_window()
    fake.router = IntentRouter()
    seen = {}
    fake.run_native_task = lambda slots, text: seen.update(
        slots=slots, text=text
    )
    fake._dispatch_command = lambda classified, text: (
        window.MainWindow._dispatch_command(fake, classified, text)
    )

    window.MainWindow.handle_command(
        fake, "kirim pesan ke telegram: halo"
    )

    assert fake.agent_tasks == []
    assert seen["slots"]["action"] == "send"


def test_posthoc_voice_intercept_suppresses_heavy_legacy_action(monkeypatch):
    import jarvis.ui.window as window

    seen = {}
    monkeypatch.setattr(
        window,
        "classify_execution",
        lambda text, context: (
            seen.update(text=text, context=context) or _route(Tier.AGENT)
        ),
    )
    legacy = SimpleNamespace(
        classify=lambda _text: (_ for _ in ()).throw(
            AssertionError("legacy voice action must be suppressed")
        )
    )
    fake = SimpleNamespace(reply_flow=_ReplyFlow(), router=legacy)

    window.MainWindow._voice_intercept(fake, "buka dan putar video terbaru")

    assert seen["context"] == {"source": "voice"}


class _TelegramMessage:
    def __init__(self):
        self.replies: list[str] = []

    async def reply_text(self, text: str):
        self.replies.append(text)
        return SimpleNamespace(
            message_id=17,
            edit_text=self._edit_text,
        )

    async def _edit_text(self, text: str) -> None:
        self.replies.append(text)


def _telegram_update() -> SimpleNamespace:
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=42),
        message=_TelegramMessage(),
    )


def test_telegram_light_uses_configured_lane_and_never_agent(monkeypatch):
    import jarvis.agent.adapters.telegram as telegram
    from jarvis.agent import dispatch, model_routing
    from jarvis.core import llm

    class _LightClient:
        def __init__(self):
            self.calls = []

        def generate(self, prompt, system=None):
            self.calls.append((prompt, system))
            return "Volume adalah ukuran suara."

    client = _LightClient()
    monkeypatch.setattr(model_routing, "light_client", lambda: client)
    monkeypatch.setattr(
        llm, "generate",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Telegram light lane must not bypass model routing")),
    )
    monkeypatch.setattr(
        dispatch, "dispatch_async",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("light Telegram command must not start agent")
        ),
    )
    update = _telegram_update()

    asyncio.run(
        telegram.TelegramService()._handle_task(update, "apa itu volume?")
    )

    assert update.message.replies == ["Volume adalah ukuran suara."]
    assert client.calls and client.calls[0][0] == "apa itu volume?"


def test_telegram_reflex_never_uses_llm_or_agent(monkeypatch):
    import jarvis.agent.adapters.telegram as telegram
    import actions.open_app as open_app_action
    from jarvis.agent import dispatch
    from jarvis.core import llm

    monkeypatch.setattr(
        llm, "generate",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("T0 Telegram must not use an LLM")
        ),
    )
    monkeypatch.setattr(
        dispatch, "dispatch_async",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("T0 Telegram must not start an agent")
        ),
    )
    launched = []
    monkeypatch.setattr(
        open_app_action, "open_app",
        lambda params: launched.append(params["app_name"]) or "Opened Spotify.",
    )
    update = _telegram_update()

    asyncio.run(telegram.TelegramService()._handle_task(update, "buka Spotify"))

    assert launched == ["Spotify"]
    assert update.message.replies == ["Opened Spotify."]


def test_telegram_tool_backed_t1_degrades_honestly_without_agent(monkeypatch):
    import jarvis.agent.adapters.telegram as telegram
    from jarvis.agent import dispatch
    from jarvis.core import llm

    monkeypatch.setattr(
        llm, "generate",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("tool-backed T1 must not hallucinate via Gemini")
        ),
    )
    monkeypatch.setattr(
        dispatch, "dispatch_async",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("tool-backed T1 must not start an agent")
        ),
    )
    update = _telegram_update()

    asyncio.run(
        telegram.TelegramService()._handle_task(update, "acara kalender hari ini")
    )

    assert "google calendar belum aktif" in update.message.replies[0].lower()


def test_telegram_image_request_stays_native_t1(monkeypatch):
    import jarvis.agent.adapters.telegram_light as telegram_light
    from jarvis.agent.base import ToolResult

    route = _route(Tier.SINGLE, "single image generation")
    seen = {}

    async def _tool(name, args, *, context=None):
        seen.update(name=name, args=args, context=context)
        return ToolResult.success("gambar tersimpan", paths=["image.png"])

    monkeypatch.setattr(telegram_light, "_tool", _tool)
    context = SimpleNamespace(surface="remote")

    result = asyncio.run(telegram_light.execute(
        "buatkan gambar kucing astronaut bergaya sinematik", route,
        context=context,
    ))

    assert result.ok is True
    assert seen == {
        "name": "image_generate",
        "args": {"prompt": "kucing astronaut bergaya sinematik"},
        "context": context,
    }


def test_telegram_youtube_search_stays_native_t1(monkeypatch):
    import jarvis.agent.adapters.telegram_light as telegram_light
    from jarvis.agent.base import ToolResult

    route = _route(Tier.SINGLE, "single search query")
    seen = {}

    async def _tool(name, args, *, context=None):
        seen.update(name=name, args=args, context=context)
        return ToolResult.success("hasil video")

    monkeypatch.setattr(telegram_light, "_tool", _tool)
    context = SimpleNamespace(surface="remote")
    text = "cari video YouTube tentang sejarah Majapahit"

    result = asyncio.run(telegram_light.execute(text, route, context=context))

    assert result.ok is True
    assert seen == {
        "name": "web_search",
        "args": {"query": "video YouTube tentang sejarah Majapahit",
                 "max_results": 6},
        "context": context,
    }


def test_telegram_heavy_uses_existing_native_dispatch(monkeypatch):
    import jarvis.agent.adapters.telegram as telegram
    from jarvis.agent import dispatch

    seen = {}
    monkeypatch.setattr(
        telegram, "classify_execution",
        lambda text, context: (
            seen.update(text=text, context=context) or _route(Tier.AGENT)
        ),
    )

    def _dispatch(task: str, **kwargs) -> bool:
        seen["task"] = task
        seen["adapter"] = kwargs.get("adapter")
        kwargs["on_ack"]("Baik, sir. Saya kerjakan.")
        return True

    monkeypatch.setattr(dispatch, "dispatch_async", _dispatch)
    update = _telegram_update()

    asyncio.run(
        telegram.TelegramService()._handle_task(update, "analisis repo ini")
    )

    assert seen["context"] == {"source": "telegram"}
    assert seen["task"] == "analisis repo ini"
    assert isinstance(seen["adapter"], telegram.TelegramAdapter)
    assert update.message.replies == ["Baik, sir. Saya kerjakan."]


def _dashboard_method():
    source = Path("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    jarvis_live = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "JarvisLive"
    )
    method = next(
        node for node in jarvis_live.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_process_dashboard_commands"
    )
    module = ast.fix_missing_locations(
        ast.Module(body=[method], type_ignores=[])
    )
    namespace = {"asyncio": asyncio, "_slog": None}
    exec(compile(module, "main.py", "exec"), namespace)
    return namespace["_process_dashboard_commands"]


class _Dashboard:
    def __init__(self):
        self._command_queue: asyncio.Queue[str] = asyncio.Queue()
        self.broadcasts: list[dict] = []
        self.broadcasted = asyncio.Event()

    async def broadcast(self, message: dict) -> None:
        self.broadcasts.append(message)
        self.broadcasted.set()


class _LiveSession:
    def __init__(self):
        self.sent: list[dict] = []
        self.sent_event = asyncio.Event()

    async def send_client_content(self, **kwargs) -> None:
        self.sent.append(kwargs)
        self.sent_event.set()


def test_dashboard_heavy_bypasses_gemini_live(monkeypatch):
    from jarvis.agent import dispatch, router

    monkeypatch.setattr(router, "classify", lambda *a, **k: _route(Tier.AGENT))
    dispatched: list[str] = []

    def _dispatch(task: str, **kwargs) -> bool:
        dispatched.append(task)
        kwargs["on_ack"]("Baik, sir. Saya kerjakan.")
        kwargs["on_done"]("hasil agent")
        return True

    monkeypatch.setattr(dispatch, "dispatch_async", _dispatch)

    async def _run() -> tuple[_Dashboard, _LiveSession]:
        dashboard = _Dashboard()
        session = _LiveSession()
        harness = SimpleNamespace(
            _dashboard=dashboard,
            session=session,
            ui=SimpleNamespace(write_log=lambda _line: None),
        )
        await dashboard._command_queue.put("riset dan buat laporan")
        task = asyncio.create_task(_dashboard_method()(harness))
        async def _wait_for_report():
            while len(dashboard.broadcasts) < 2:
                await asyncio.sleep(0)

        await asyncio.wait_for(_wait_for_report(), timeout=1.0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return dashboard, session

    dashboard, session = asyncio.run(_run())

    assert dispatched == ["riset dan buat laporan"]
    assert session.sent == []
    assert dashboard.broadcasts[0]["text"] == "Baik, sir. Saya kerjakan."
    assert "hasil agent" in dashboard.broadcasts[-1]["text"]
    assert "sir" in dashboard.broadcasts[-1]["text"].casefold()


def test_dashboard_light_preserves_gemini_live(monkeypatch):
    from jarvis.agent import dispatch, router

    monkeypatch.setattr(router, "classify", lambda *a, **k: _route(Tier.SINGLE))
    monkeypatch.setattr(
        dispatch, "dispatch_async",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("light dashboard command must not start agent")
        ),
    )

    async def _run() -> _LiveSession:
        dashboard = _Dashboard()
        session = _LiveSession()
        harness = SimpleNamespace(
            _dashboard=dashboard,
            session=session,
            ui=SimpleNamespace(write_log=lambda _line: None),
        )
        await dashboard._command_queue.put("halo jarvis")
        task = asyncio.create_task(_dashboard_method()(harness))
        await asyncio.wait_for(session.sent_event.wait(), timeout=1.0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        return session

    session = asyncio.run(_run())

    assert session.sent == [{
        "turns": {"parts": [{"text": "halo jarvis"}]},
        "turn_complete": True,
    }]
