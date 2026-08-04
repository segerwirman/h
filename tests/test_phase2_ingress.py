"""Phase 2 lifecycle wiring at the typed, voice, and Telegram seams."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path


def _method_from_main(name: str):
    source = Path("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == "JarvisLive")
    method = next(node for node in cls.body
                  if isinstance(node, ast.FunctionDef) and node.name == name)
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    namespace = {}
    exec(compile(module, "main.py", "exec"), namespace)
    return namespace[name]


class _Signal:
    def __init__(self):
        self.values = []

    def emit(self, *values):
        self.values.append(values)


class _Orb:
    def __init__(self):
        self.states = []

    def set_state(self, state):
        self.states.append(state)


class _TypedHarness:
    def __init__(self):
        self.orb = _Orb()
        self._content_sig = _Signal()
        self.logs = []
        self.spoken = []
        self.restored = 0
        self.task_results = []

    def write_log(self, text):
        self.logs.append(text)

    def _speak_line(self, text):
        self.spoken.append(text)

    def _restore_orb(self):
        self.restored += 1

    def _record_task_result(self, kind, text):
        """Drawer hasil task F1 (window.py:2002). Produk memanggilnya di jalur
        T2; stub harus menyediakannya agar yang teruji tetap alur nyata."""
        self.task_results.append((kind, text))


def test_typed_t2_speaks_ack_then_concrete_report(monkeypatch):
    from jarvis.agent import interactive_dispatch, response_composer
    from jarvis.ui.window import MainWindow

    # S-15 — `auxiliary.response_composer.enabled` bernilai true di config
    # repo, jadi tanpa stub ini test benar-benar menembak provider di tengah
    # suite: lambat, bergantung jaringan, dan gagal acak ketika generasi
    # terpotong token cap. Test unit tidak boleh memanggil LLM sungguhan.
    monkeypatch.setattr(response_composer, "compose",
                        lambda delivery, task, **_: delivery)

    events = []
    result = (
        '**Video "Deddy Corbuzier Episode 123" sudah diputar.**\n'
        "URL: https://youtube.com/watch?v=abc123\n"
        r"Path: C:\Jarvis\reports\episode-123.txt"
    )

    def primitive(_task, **kwargs):
        kwargs["on_ack"]("Baik, sir. Saya kerjakan.")
        events.append("work")
        kwargs["on_done"](result)
        return True

    monkeypatch.setattr(
        interactive_dispatch.dispatch, "dispatch_async", primitive)
    # Seam ACK PINDAH: dulu ``interactive_dispatch.render_ack``, kini
    # ``ack_composer.compose_ack`` (interactive_dispatch.py:66). Teks yang
    # diucapkan adalah hasil composer, bukan ``raw`` dari primitive — dan
    # render_ack memilih dari daftar template, jadi tanpa penambatan ini
    # assert teks persis akan flaky.
    from jarvis.agent import ack_composer
    monkeypatch.setattr(
        ack_composer, "compose_ack",
        lambda _task, **_kwargs: "Baik, sir. Saya kerjakan.")

    harness = _TypedHarness()
    MainWindow._run_agent_native(harness, "tolong putar video terbaru")

    assert harness.spoken[0] == "Baik, sir. Saya kerjakan."
    assert events == ["work"]
    assert "Deddy Corbuzier" in harness.spoken[1]
    assert "https://youtube.com" not in harness.spoken[1]
    assert harness.spoken[1].casefold().endswith("sir.")
    assert harness._content_sig.values == [(
        "AGENT — hasil tugas",
        'Video "Deddy Corbuzier Episode 123" sudah diputar.\n'
        "URL: https://youtube.com/watch?v=abc123\n"
        r"Path: C:\Jarvis\reports\episode-123.txt",
    )]
    assert harness.restored == 1


def test_typed_t2_memakai_speech_composer_opsional(monkeypatch):
    from jarvis.agent import interactive_dispatch, response_composer
    from jarvis.agent.interaction import ConversationDelivery
    from jarvis.ui.window import MainWindow

    def primitive(_task, **kwargs):
        kwargs["on_done"]("Video terbaru Deddy Corbuzier sudah diputar.")
        return True

    def natural(delivery, task):
        assert "Deddy Corbuzier" in delivery.speech_text
        assert "putar video" in task
        return ConversationDelivery(
            display_text=delivery.display_text,
            speech_text="Video terbaru Deddy Corbuzier telah saya siapkan, sir.",
            factual_anchors=delivery.factual_anchors,
            mode="natural",
        )

    monkeypatch.setattr(interactive_dispatch.dispatch, "dispatch_async", primitive)
    monkeypatch.setattr(response_composer, "compose", natural)
    harness = _TypedHarness()

    MainWindow._run_agent_native(harness, "tolong putar video terbaru")

    assert harness.spoken == ["Video terbaru Deddy Corbuzier telah saya siapkan, sir."]


def test_typed_t2_melaporkan_completion_melalui_delivery_lifecycle(monkeypatch):
    from jarvis.agent import delivery_lifecycle, interactive_dispatch
    from jarvis.agent.interaction import ConversationDelivery
    from jarvis.ui.window import MainWindow

    calls = []

    def primitive(_task, **kwargs):
        kwargs["on_done"]("Laporan build 123 selesai.")
        return True

    def lifecycle_success(raw, task, *, source, naturalize):
        calls.append((raw, task, source, naturalize))
        return ConversationDelivery(
            display_text=raw,
            speech_text="Build 123 telah selesai, sir.",
            factual_anchors=("123",),
            mode="natural",
        )

    monkeypatch.setattr(interactive_dispatch.dispatch, "dispatch_async", primitive)
    monkeypatch.setattr(delivery_lifecycle, "success", lifecycle_success)
    harness = _TypedHarness()

    MainWindow._run_agent_native(harness, "cek build")

    assert calls == [("Laporan build 123 selesai.", "cek build", "typed", True)]
    assert harness.spoken == ["Build 123 telah selesai, sir."]


class _VoiceUI:
    def __init__(self):
        self.logs = []
        self.states = []

    def write_log(self, text):
        self.logs.append(text)

    def set_state(self, state):
        self.states.append(state)


class _VoiceHarness:
    def __init__(self):
        self.ui = _VoiceUI()
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)


def test_voice_t2_queues_brief_ack_before_work_and_deterministic_report(monkeypatch):
    from jarvis.agent import dispatch

    events = []

    def primitive(_task, **kwargs):
        kwargs["on_ack"]("Baik, sir. Saya kerjakan.")
        events.append("work")
        kwargs["on_done"]("Video terbaru Deddy Corbuzier sudah diputar.")
        return True

    monkeypatch.setattr(dispatch, "dispatch_async", primitive)
    harness = _VoiceHarness()

    started, status = _method_from_main("_dispatch_native_agent")(
        harness, "buka dan putar youtube deddy corbuzier terbaru")

    assert started is True
    assert "dialihkan" in status
    assert events == ["work"]
    assert "Baik, sir. Saya kerjakan." in harness.spoken[0]
    assert "PERSIS" not in harness.spoken[0]
    assert "Deddy Corbuzier" in harness.spoken[1]
    assert "sudah diputar" in harness.spoken[1]


def test_voice_t2_memakai_speech_composer_opsional(monkeypatch):
    from jarvis.agent import dispatch, response_composer
    from jarvis.agent.interaction import ConversationDelivery

    def primitive(_task, **kwargs):
        kwargs["on_done"]("Video terbaru Deddy Corbuzier sudah diputar.")
        return True

    def natural(delivery, task):
        assert "Deddy Corbuzier" in delivery.speech_text
        assert "putar youtube" in task
        return ConversationDelivery(
            display_text=delivery.display_text,
            speech_text="Video terbaru Deddy Corbuzier sudah siap, sir.",
            factual_anchors=delivery.factual_anchors,
            mode="natural",
        )

    monkeypatch.setattr(dispatch, "dispatch_async", primitive)
    monkeypatch.setattr(response_composer, "compose", natural)
    harness = _VoiceHarness()

    started, _ = _method_from_main("_dispatch_native_agent")(
        harness, "buka dan putar youtube deddy corbuzier terbaru")

    assert started is True
    assert harness.spoken == ["Video terbaru Deddy Corbuzier sudah siap, sir."]


def test_voice_t2_melaporkan_completion_melalui_delivery_lifecycle(monkeypatch):
    from jarvis.agent import delivery_lifecycle, dispatch
    from jarvis.agent.interaction import ConversationDelivery

    calls = []
    acknowledgements = []

    def primitive(_task, **kwargs):
        kwargs["on_ack"]("Baik, sir. Saya kerjakan.")
        kwargs["on_done"]("Laporan build 123 selesai.")
        return True

    def lifecycle_success(raw, task, *, source, naturalize):
        calls.append((raw, task, source, naturalize))
        return ConversationDelivery(
            display_text=raw,
            speech_text="Build 123 telah selesai, sir.",
            factual_anchors=("123",),
            mode="natural",
        )

    monkeypatch.setattr(dispatch, "dispatch_async", primitive)
    monkeypatch.setattr(delivery_lifecycle, "success", lifecycle_success)
    monkeypatch.setattr(
        delivery_lifecycle, "acknowledged",
        lambda source, ack: acknowledgements.append((source, ack)),
    )
    harness = _VoiceHarness()

    started, _ = _method_from_main("_dispatch_native_agent")(harness, "cek build")

    assert started is True
    assert acknowledgements == [("voice", "Baik, sir. Saya kerjakan.")]
    assert calls == [("Laporan build 123 selesai.", "cek build", "voice", True)]
    assert harness.spoken == ["Baik, sir. Saya kerjakan.", "Build 123 telah selesai, sir."]


def test_voice_unavailable_defers_honest_report_without_false_ack(monkeypatch):
    from jarvis.agent import dispatch

    monkeypatch.setattr(dispatch, "dispatch_async", lambda *a, **k: False)
    harness = _VoiceHarness()

    started, notice = _method_from_main("_dispatch_native_agent")(
        harness, "please research and create a report")

    assert started is False
    assert harness.spoken == []
    assert "PERSIS" not in notice
    assert "Sorry, sir" in notice
    assert "not configured" in notice


def test_telegram_t2_ack_precedes_work_and_sends_concrete_report(monkeypatch):
    from jarvis.agent import dispatch
    from jarvis.agent.adapters import telegram
    from jarvis.agent.router import Route, Tier

    monkeypatch.setattr(
        telegram, "classify_execution",
        lambda *_a, **_k: Route(Tier.AGENT, "heavy", "heavy", "test", 1.0))
    events = []
    result = (
        '**Video "Deddy Corbuzier Episode 123" sudah diputar.**\n'
        "URL: https://youtube.com/watch?v=abc123\n"
        r"Path: C:\Jarvis\reports\episode-123.txt"
    )

    def primitive(_task, **kwargs):
        kwargs["on_ack"]("Baik, sir. Saya kerjakan.")
        events.append("work")
        kwargs["on_done"](result)
        return True

    monkeypatch.setattr(dispatch, "dispatch_async", primitive)

    class Message:
        def __init__(self):
            self.replies = []

        async def reply_text(self, text):
            self.replies.append(text)
            return type("Progress", (), {"message_id": 9})()

    message = Message()
    update = type("Update", (), {
        "effective_chat": type("Chat", (), {"id": 42})(),
        "message": message,
    })()
    service = telegram.TelegramService()
    sent = []
    monkeypatch.setattr(service, "send_text",
                        lambda chat_id, text: sent.append((chat_id, text)))

    asyncio.run(service._handle_task(
        update, "buka dan putar youtube deddy corbuzier terbaru"))

    assert message.replies == ["Baik, sir. Saya kerjakan."]
    assert events == ["work"]
    assert sent and sent[0][0] == 42
    assert sent[0][1] == (
        'Video "Deddy Corbuzier Episode 123" sudah diputar.\n'
        "URL: https://youtube.com/watch?v=abc123\n"
        r"Path: C:\Jarvis\reports\episode-123.txt"
    )


def test_telegram_t2_melaporkan_completion_melalui_delivery_lifecycle(monkeypatch):
    from jarvis.agent import delivery_lifecycle, dispatch
    from jarvis.agent.adapters import telegram
    from jarvis.agent.interaction import ConversationDelivery
    from jarvis.agent.router import Route, Tier

    monkeypatch.setattr(
        telegram, "classify_execution",
        lambda *_a, **_k: Route(Tier.AGENT, "heavy", "heavy", "test", 1.0),
    )
    calls = []

    def primitive(_task, **kwargs):
        kwargs["on_ack"]("Baik, sir. Saya kerjakan.")
        kwargs["on_done"]("Laporan build 123 selesai.")
        return True

    def lifecycle_success(raw, task, *, source, naturalize=False):
        calls.append((raw, task, source, naturalize))
        return ConversationDelivery(raw, "Build 123 selesai, sir.", ("123",))

    monkeypatch.setattr(dispatch, "dispatch_async", primitive)
    monkeypatch.setattr(delivery_lifecycle, "success", lifecycle_success)

    class Message:
        async def reply_text(self, _text):
            return type("Progress", (), {"message_id": 9})()

    update = type("Update", (), {
        "effective_chat": type("Chat", (), {"id": 42})(),
        "message": Message(),
    })()
    service = telegram.TelegramService()
    sent = []
    monkeypatch.setattr(service, "send_text", lambda chat_id, text: sent.append((chat_id, text)))

    asyncio.run(service._handle_task(update, "cek build"))

    assert calls == [("Laporan build 123 selesai.", "cek build", "telegram", False)]
    assert sent == [(42, "Laporan build 123 selesai.")]
