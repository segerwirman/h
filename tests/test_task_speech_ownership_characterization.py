"""RED-first contracts for task speech scope and completion ownership."""
from __future__ import annotations

import inspect
import threading
import time
import types

from jarvis.agent import dispatch
from jarvis.agent.loop import RunResult
from jarvis.agent.tasks import REGISTRY, TaskRegistry
from jarvis.integrations import voice_speech, voice_tasks


class _Signal:
    def __init__(self):
        self.values = []

    def emit(self, *values):
        self.values.append(values)


class _Orb:
    def set_state(self, _state):
        return None


class _TypedHarness:
    def __init__(self):
        self.orb = _Orb()
        self._content_sig = _Signal()
        self.logs = []
        self.spoken: list[tuple[str, str, str]] = []
        self.restored = 0
        self.task_results = []

    def write_log(self, text):
        self.logs.append(text)

    def _speak_line(self, text, *, kind="info", turn=""):
        self.spoken.append((text, kind, turn))

    def _restore_orb(self):
        self.restored += 1

    def _record_task_result(self, kind, text):
        self.task_results.append((kind, text))


def _isolate_dispatch(monkeypatch):
    monkeypatch.setattr(dispatch, "available", lambda: True)
    monkeypatch.setattr(dispatch.BUS, "publish", lambda *_a, **_k: None)
    REGISTRY.clear()
    with dispatch._active_lock:
        dispatch._active.clear()


def test_typed_ack_and_final_share_registry_task_id(monkeypatch):
    from jarvis.agent import interactive_dispatch, response_composer
    from jarvis.ui.window import MainWindow

    monkeypatch.setattr(
        response_composer, "compose", lambda delivery, _task, **_: delivery)

    def primitive(_task, **kwargs):
        metadata = types.SimpleNamespace(
            id="T-typed", session_id="S-typed", title="cek build")
        kwargs["on_task"](metadata)
        kwargs["on_ack"]("Baik, saya kerjakan.")
        kwargs["on_done"]("Build selesai.")
        return True

    monkeypatch.setattr(interactive_dispatch.dispatch, "dispatch_async", primitive)
    harness = _TypedHarness()

    MainWindow._run_agent_native(harness, "cek build")

    assert [(_kind, _turn) for _text, _kind, _turn in harness.spoken] == [
        ("ack", "T-typed"),
        ("final", "T-typed"),
    ]


def test_typed_error_uses_the_matching_registry_task_id(monkeypatch):
    from jarvis.agent import interactive_dispatch
    from jarvis.ui.window import MainWindow

    def primitive(_task, **kwargs):
        metadata = types.SimpleNamespace(
            id="T-error", session_id="S-error", title="cek build")
        kwargs["on_task"](metadata)
        kwargs["on_ack"]("Baik, saya kerjakan.")
        kwargs["on_error"]("provider mati")
        return True

    monkeypatch.setattr(interactive_dispatch.dispatch, "dispatch_async", primitive)
    harness = _TypedHarness()

    MainWindow._run_agent_native(harness, "cek build")

    assert harness.spoken[0][1:] == ("ack", "T-error")
    assert harness.spoken[1][1:] == ("final", "T-error")


def test_callback_owned_completion_does_not_enter_voice_tasks(monkeypatch):
    _isolate_dispatch(monkeypatch)
    from jarvis.agent import loop as agent_loop

    voice_tasks.clear_notices()
    done = threading.Event()

    async def fake_run(_task, **_kwargs):
        return RunResult(ok=True, text="done", session_id="callback-owner")

    monkeypatch.setattr(agent_loop, "run", fake_run)
    assert dispatch.dispatch_async("callback task", on_done=lambda _r: done.set())
    assert done.wait(2)

    view = next(item for item in REGISTRY.snapshot() if item.title == "callback task")
    voice_tasks._on_task_finished({"task": view.as_dict()})

    assert view.completion_owner == "caller"
    assert voice_tasks.pending_notices() == 0


def test_success_with_only_error_callback_stays_registry_owned(monkeypatch):
    _isolate_dispatch(monkeypatch)
    from jarvis.agent import loop as agent_loop

    done = threading.Event()

    async def fake_run(_task, **_kwargs):
        return RunResult(ok=True, text="done", session_id="only-error")

    monkeypatch.setattr(agent_loop, "run", fake_run)
    monkeypatch.setattr(
        REGISTRY._bus,
        "publish",
        lambda topic, **_data: done.set()
        if topic == "task.finished" else None,
    )

    assert dispatch.dispatch_async(
        "success without done consumer",
        on_error=lambda _value: None,
    )
    assert done.wait(2)

    view = next(
        item for item in REGISTRY.snapshot()
        if item.title == "success without done consumer"
    )
    assert view.completion_owner == "registry"


def test_failure_with_only_done_callback_stays_registry_owned(monkeypatch):
    _isolate_dispatch(monkeypatch)
    from jarvis.agent import loop as agent_loop

    finished = threading.Event()

    async def fake_run(_task, **_kwargs):
        return RunResult(ok=False, text="failed", session_id="only-done")

    monkeypatch.setattr(agent_loop, "run", fake_run)
    monkeypatch.setattr(
        REGISTRY._bus,
        "publish",
        lambda topic, **_data: finished.set()
        if topic == "task.finished" else None,
    )

    assert dispatch.dispatch_async(
        "failure without error consumer",
        on_done=lambda _value: None,
    )
    assert finished.wait(2)

    view = next(
        item for item in REGISTRY.snapshot()
        if item.title == "failure without error consumer"
    )
    assert view.completion_owner == "registry"


def test_callback_exception_falls_back_before_finished_publish(monkeypatch):
    events: list[tuple[str, str]] = []

    class Bus:
        def publish(self, topic, **data):
            task = data.get("task") or {}
            if topic == "task.finished":
                events.append((topic, task.get("completion_owner", "")))

    registry = TaskRegistry(bus=Bus())
    task = registry.submit("callback exception")
    assert task is not None

    assert dispatch._finish_with_delivery(
        registry,
        task.id,
        callback=lambda _value: (_ for _ in ()).throw(
            RuntimeError("consumer gone")
        ),
        value="done",
        result="done",
    ) is False

    assert events == [("task.finished", "registry")]


def test_explicit_callback_decline_falls_back_to_registry(monkeypatch):
    events: list[tuple[str, str]] = []

    class Bus:
        def publish(self, topic, **data):
            task = data.get("task") or {}
            if topic == "task.finished":
                events.append((topic, task.get("completion_owner", "")))

    registry = TaskRegistry(bus=Bus())
    task = registry.submit("callback decline")
    assert task is not None

    assert dispatch._finish_with_delivery(
        registry,
        task.id,
        callback=lambda _value: False,
        value="done",
        result="done",
    ) is False

    assert events == [("task.finished", "registry")]


def test_callback_observes_terminal_state_before_finished_publish():
    events: list[tuple[str, str]] = []

    class Bus:
        def publish(self, topic, **data):
            if topic == "task.finished":
                task = data.get("task") or {}
                events.append((topic, task.get("completion_owner", "")))

    registry = TaskRegistry(bus=Bus())
    task = registry.submit("observable terminal")
    assert task is not None

    observed = []

    def callback(_value):
        view = registry.get(task.id)
        observed.append((
            view.status.value,
            view.result,
            view.completion_owner,
        ))
        assert events == []

    assert dispatch._finish_with_delivery(
        registry,
        task.id,
        callback=callback,
        value="done",
        result="done",
    ) is True

    assert observed == [("done", "done", "caller")]
    assert events == [("task.finished", "caller")]


def test_callback_signal_never_exposes_wrong_provisional_owner():
    registry = TaskRegistry(bus=types.SimpleNamespace(publish=lambda *_a, **_k: None))
    task = registry.submit("callback signal")
    assert task is not None
    released = threading.Event()
    observed = []

    def reader():
        assert released.wait(1)
        view = registry.get(task.id)
        observed.append((view.status.value, view.completion_owner))

    thread = threading.Thread(target=reader)
    thread.start()

    def callback(_value):
        released.set()
        thread.join(1)

    assert dispatch._finish_with_delivery(
        registry,
        task.id,
        callback=callback,
        value="done",
        result="done",
    ) is True
    thread.join(1)

    assert observed == [("done", "caller")]


def test_direct_finish_cannot_publish_over_pending_callback_resolution():
    events: list[str] = []

    class Bus:
        def publish(self, topic, **data):
            if topic == "task.finished":
                events.append((data.get("task") or {}).get("completion_owner", ""))

    registry = TaskRegistry(bus=Bus())
    task = registry.submit("pending callback")
    assert task is not None

    def callback(_value):
        concurrent = registry.finish(
            task.id,
            error="late competing finish",
            completion_owner="registry",
        )
        assert concurrent is not None
        assert concurrent.completion_owner == "caller"
        assert concurrent.result == "done"
        assert events == []

    assert dispatch._finish_with_delivery(
        registry,
        task.id,
        callback=callback,
        value="done",
        result="done",
    ) is True

    view = registry.get(task.id)
    assert view is not None
    assert view.result == "done"
    assert view.error == ""
    assert view.completion_owner == "caller"
    assert events == ["caller"]


def test_callback_decline_replaces_provisional_owner_before_publish():
    events: list[str] = []

    class Bus:
        def publish(self, topic, **data):
            if topic == "task.finished":
                events.append((data.get("task") or {}).get("completion_owner", ""))

    registry = TaskRegistry(bus=Bus())
    task = registry.submit("declined provisional")
    assert task is not None
    observed = []

    def callback(_value):
        observed.append(registry.get(task.id).completion_owner)
        return False

    assert dispatch._finish_with_delivery(
        registry,
        task.id,
        callback=callback,
        value="done",
        result="done",
    ) is False

    assert observed == ["caller"]
    assert registry.get(task.id).completion_owner == "registry"
    assert events == ["registry"]


def test_finish_installs_owner_atomically_and_terminal_repeat_is_immutable():
    events: list[str] = []

    class Bus:
        def publish(self, topic, **data):
            task = data.get("task") or {}
            if topic == "task.finished":
                events.append(task.get("completion_owner", ""))

    registry = TaskRegistry(bus=Bus())
    task = registry.submit("atomic owner")
    assert task is not None

    first = registry.finish(
        task.id,
        result="done",
        completion_owner="caller",
    )
    second = registry.finish(
        task.id,
        error="late error",
        completion_owner="registry",
    )

    assert first is not None and first.completion_owner == "caller"
    assert second is not None and second.completion_owner == "caller"
    assert events == ["caller"]


def test_registry_owned_task_emits_one_notice_even_after_repeated_finish(monkeypatch):
    _isolate_dispatch(monkeypatch)

    voice_tasks.clear_notices()
    monkeypatch.setattr(voice_tasks.config, "get", lambda _key, default=None: default)
    monkeypatch.setattr(
        REGISTRY._bus, "publish",
        lambda topic, **data: voice_tasks._on_task_finished(data)
        if topic == "task.finished" else None,
    )
    task = REGISTRY.submit(
        "registry task", completion_owner="registry", source="voice-task-tool")
    assert task is not None

    REGISTRY.finish(task.id, result="done")
    REGISTRY.finish(task.id, result="done again")

    view = REGISTRY.get(task.id)
    assert view is not None
    assert view.completion_owner == "registry"
    assert voice_tasks.pending_notices() == 1


def test_registry_owned_voice_callback_keeps_side_effects_but_suppresses_speech():
    ordinary: list[str] = []
    queued: list[tuple[str, str, str]] = []
    callback_effects: list[str] = []

    class Live:
        def speak(self, text):
            ordinary.append(text)
            return "legacy"

    legacy = types.SimpleNamespace(JarvisLive=Live)
    assert voice_speech.install(legacy) is True
    live = Live()
    live.ui = types.SimpleNamespace(
        _win=types.SimpleNamespace(
            _speak_line=lambda text, *, kind="info", turn="": queued.append(
                (text, kind, turn))))

    def callback(value):
        callback_effects.append(value)
        live.speak(value)

    assert dispatch._safe_callback(
        callback,
        "registry will announce",
        task_id="T-registry-voice",
        kind="final",
        speech_enabled=False,
    ) is True

    assert callback_effects == ["registry will announce"]
    assert ordinary == []
    assert queued == []


def test_scoped_live_speak_routes_without_changing_ordinary_speech():
    ordinary: list[str] = []
    queued: list[tuple[str, str, str]] = []

    class Live:
        def speak(self, text):
            ordinary.append(text)
            return "legacy"

    legacy = types.SimpleNamespace(JarvisLive=Live)
    assert voice_speech.install(legacy) is True
    live = Live()
    live.ui = types.SimpleNamespace(
        _win=types.SimpleNamespace(
            _speak_line=lambda text, *, kind="info", turn="": queued.append(
                (text, kind, turn))))

    assert live.speak("ordinary") == "legacy"
    with voice_speech.delivery_scope(task_id="T-voice", kind="ack"):
        assert live.speak("acknowledged") is None

    assert ordinary == ["ordinary"]
    assert queued == [("acknowledged", "ack", "T-voice")]


def test_source_scope_is_context_local_and_resets():
    assert dispatch.current_source_scope() is None

    with dispatch.source_scope(
        "voice-native",
        completion_owner="registry",
    ) as outer:
        assert dispatch.current_source_scope() == outer
        with dispatch.source_scope("typed", completion_owner="caller") as inner:
            assert dispatch.current_source_scope() == inner
        assert dispatch.current_source_scope() == outer

    assert dispatch.current_source_scope() is None


def test_source_scope_isolated_across_threads():
    observed: list[tuple[str, str]] = []
    ready = threading.Barrier(3)

    def worker(source: str) -> None:
        with dispatch.source_scope(source):
            ready.wait()
            scope = dispatch.current_source_scope()
            observed.append((source, scope.source if scope is not None else ""))
            ready.wait()
        assert dispatch.current_source_scope() is None

    threads = [
        threading.Thread(target=worker, args=("voice-native",)),
        threading.Thread(target=worker, args=("typed",)),
    ]
    for thread in threads:
        thread.start()
    ready.wait()
    assert dispatch.current_source_scope() is None
    ready.wait()
    for thread in threads:
        thread.join(1)

    assert sorted(observed) == [
        ("typed", "typed"),
        ("voice-native", "voice-native"),
    ]


def test_voice_native_installer_composes_source_scope_once(monkeypatch):
    from jarvis.integrations import voice_native_tools

    observed = []

    class Live:
        async def _execute_tool(self, _fc):
            return None

        async def run(self):
            return None

        def _dispatch_native_agent(self, task, **_kwargs):
            scope = dispatch.current_source_scope()
            observed.append(
                (task, scope.source, scope.completion_owner)
                if scope is not None else (task, "", "")
            )
            return True, "started"

    legacy = types.SimpleNamespace(
        JarvisLive=Live,
        TOOL_DECLARATIONS=[],
        types=types.SimpleNamespace(FunctionResponse=dict),
        _load_system_prompt=lambda: "persona",
    )
    monkeypatch.setattr(voice_tasks, "ensure_subscribed", lambda: None)
    monkeypatch.setattr(voice_tasks, "declarations", lambda: [])

    voice_native_tools.install(legacy)
    wrapped = Live._dispatch_native_agent
    voice_native_tools.install(legacy)

    assert Live._dispatch_native_agent is wrapped
    assert Live()._dispatch_native_agent("cek build") == (True, "started")
    assert observed == [("cek build", "voice-native", "registry")]
    assert dispatch.current_source_scope() is None


def test_marked_native_exec_still_repairs_missing_source_scope(monkeypatch):
    from jarvis.integrations import voice_native_tools

    observed = []

    async def marked_exec(self, _fc):
        return None

    marked_exec._jarvis_native_tools = True

    class Live:
        _execute_tool = marked_exec

        async def run(self):
            return None

        def _dispatch_native_agent(self, task, **_kwargs):
            scope = dispatch.current_source_scope()
            observed.append(
                (task, scope.source, scope.completion_owner)
                if scope is not None else (task, "", "")
            )
            return True, "started"

    legacy = types.SimpleNamespace(
        JarvisLive=Live,
        TOOL_DECLARATIONS=[],
        types=types.SimpleNamespace(FunctionResponse=dict),
        _load_system_prompt=lambda: "persona",
    )
    monkeypatch.setattr(voice_tasks, "ensure_subscribed", lambda: None)
    monkeypatch.setattr(voice_tasks, "declarations", lambda: [])

    voice_native_tools.install(legacy)

    assert Live._execute_tool is marked_exec
    assert getattr(Live.run, "_jarvis_task_flusher", False) is True
    assert getattr(
        Live._dispatch_native_agent, "_jarvis_voice_task_source", False
    ) is True
    assert Live()._dispatch_native_agent("cek build") == (True, "started")
    assert observed == [("cek build", "voice-native", "registry")]


def test_voice_speech_installer_wraps_speak_once():
    class Live:
        def speak(self, text):
            return text

    legacy = types.SimpleNamespace(JarvisLive=Live)
    original = Live.speak

    assert voice_speech.install(legacy) is True
    wrapped = Live.speak
    assert wrapped is not original
    assert voice_speech.install(legacy) is False
    assert Live.speak is wrapped
    assert getattr(wrapped, "_jarvis_voice_speech_scope", False) is True


def test_voice_native_dispatch_keeps_registry_speech_owner_and_source(monkeypatch):
    _isolate_dispatch(monkeypatch)
    from jarvis.agent import loop as agent_loop

    terminal = threading.Event()
    callback_seen: list[str] = []

    async def fake_run(_task, **_kwargs):
        return RunResult(ok=True, text="done", session_id="voice-native-owner")

    monkeypatch.setattr(agent_loop, "run", fake_run)
    monkeypatch.setattr(
        REGISTRY._bus,
        "publish",
        lambda topic, **_data: terminal.set()
        if topic == "task.finished" else None,
    )

    with dispatch.source_scope(
        "voice-native",
        completion_owner="registry",
    ):
        assert dispatch.dispatch_async(
            "voice native task",
            on_done=lambda value: callback_seen.append(value),
        )

    assert terminal.wait(2)
    view = next(
        item for item in REGISTRY.snapshot()
        if item.title == "voice native task"
    )
    assert callback_seen == ["done"]
    assert view.source == "voice-native"
    assert view.completion_owner == "registry"


def test_dispatch_activates_task_scope_for_ack_and_final(monkeypatch):
    _isolate_dispatch(monkeypatch)
    from jarvis.agent import loop as agent_loop

    captured: list[tuple[str, str]] = []
    done = threading.Event()

    async def fake_run(_task, **_kwargs):
        return RunResult(ok=True, text="done", session_id="voice-scope")

    def capture(kind: str):
        def callback(_value: str) -> None:
            scope = voice_speech.current_delivery_scope()
            captured.append((scope.kind, scope.task_id))
            if kind == "final":
                done.set()

        return callback

    monkeypatch.setattr(agent_loop, "run", fake_run)
    assert dispatch.dispatch_async(
        "voice task",
        on_ack=capture("ack"),
        on_done=capture("final"),
    ) is True
    assert done.wait(2)

    assert [kind for kind, _task_id in captured] == ["ack", "final"]
    assert captured[0][1].startswith("T-")
    assert captured[1][1] == captured[0][1]


def test_scoped_agent_result_notice_defers_to_task_speech_owner(monkeypatch):
    from jarvis.integrations import voice_notices

    voice_notices._reset_for_tests()
    monkeypatch.setattr(voice_notices, "_enabled", lambda: True)

    with voice_speech.delivery_scope(task_id="T-voice", kind="final"):
        assert voice_notices.remember_agent_result(
            "cek build", "Build hijau", ok=True
        ) is False

    assert voice_notices.pending_count() == 0


def test_unscoped_agent_result_notice_remains_legacy_fallback(monkeypatch):
    from jarvis.integrations import voice_notices

    voice_notices._reset_for_tests()
    monkeypatch.setattr(voice_notices, "_enabled", lambda: True)

    assert voice_notices.remember_agent_result(
        "cek build", "Build hijau", ok=True
    ) is True
    assert voice_notices.pending_count() == 1


def test_registry_notice_ignores_typed_and_remote_sources(monkeypatch):
    voice_tasks.clear_notices()
    monkeypatch.setattr(voice_tasks.config, "get", lambda _key, default=None: default)

    for source in ("typed", "ui", "telegram", "cron"):
        voice_tasks._on_task_finished({
            "task": {
                "id": f"T-{source}",
                "title": "private task",
                "status": "done",
                "result": "private result",
                "error": "",
                "completion_owner": "registry",
                "source": source,
            }
        })

    assert voice_tasks.pending_notices() == 0


def test_allowed_voice_notice_redacts_secrets_and_private_paths(monkeypatch):
    voice_tasks.clear_notices()
    monkeypatch.setattr(voice_tasks.config, "get", lambda _key, default=None: default)

    voice_tasks._on_task_finished({
        "task": {
            "id": "T-private",
            "title": r"audit C:\\Users\\alice\\secrets.txt",
            "status": "done",
            "result": (
                "Authorization: Bearer abc.def.ghi "
                "api_key=sk-thismustnotleak "
                r"saved C:\\Users\\alice\\result.txt"
            ),
            "error": "",
            "completion_owner": "registry",
            "source": "voice-task-tool",
        }
    })

    with voice_tasks._notices_lock:
        notice = voice_tasks._notices[0][1]
    assert "abc.def.ghi" not in notice
    assert "sk-thismustnotleak" not in notice
    assert "alice" not in notice
    assert "[REDACTED]" in notice
    assert "[private path]" in notice


def test_task_notice_deduplicates_by_task_id_not_completion_text(monkeypatch):
    voice_tasks.clear_notices()
    monkeypatch.setattr(voice_tasks.config, "get", lambda _key, default=None: default)
    first = {
        "id": "T-one", "title": "riset satu", "status": "done",
        "result": "hasil identik", "error": "", "completion_owner": "registry",
        "source": "voice-task-tool",
    }
    second = {
        "id": "T-two", "title": "riset dua", "status": "done",
        "result": "hasil identik", "error": "", "completion_owner": "registry",
        "source": "voice-task-tool",
    }

    voice_tasks._on_task_finished({"task": first})
    voice_tasks._on_task_finished({"task": first})
    voice_tasks._on_task_finished({"task": second})

    assert voice_tasks.pending_notices() == 2


def test_interactive_missing_terminal_consumer_returns_declined_receipt(monkeypatch):
    from jarvis.agent import interactive_dispatch

    receipts: list[bool] = []

    def primitive(_task, **kwargs):
        receipts.append(kwargs["on_done"]("done"))
        return True

    monkeypatch.setattr(interactive_dispatch.dispatch, "dispatch_async", primitive)

    assert interactive_dispatch.start("no consumer") is True
    assert receipts == [False]


def test_interactive_callback_exception_returns_declined_receipt(monkeypatch):
    from jarvis.agent import interactive_dispatch

    receipts: list[bool] = []

    def primitive(_task, **kwargs):
        receipts.append(kwargs["on_done"]("done"))
        return True

    monkeypatch.setattr(interactive_dispatch.dispatch, "dispatch_async", primitive)

    assert interactive_dispatch.start(
        "broken consumer",
        on_done=lambda _raw, _report: (_ for _ in ()).throw(
            RuntimeError("ui gone")
        ),
    ) is True
    assert receipts == [False]


def test_missing_voice_scope_module_still_invokes_callback(monkeypatch):
    original_import = __import__
    called: list[str] = []

    def fail_voice_scope(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "jarvis.integrations.voice_speech":
            raise ImportError("scope unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fail_voice_scope)
    dispatch._safe_callback(
        called.append,
        "delivered",
        task_id="T-fallback",
        kind="final",
    )

    assert called == ["delivered"]


def test_voice_native_installer_scopes_conversation_id_for_seam_bind(monkeypatch):
    """Fase 38 — the editable voice seam propagates ``conversation_id="voice-live"``
    so dispatch can bind the real registry task ID into immediate context even
    though FROZEN main.py cannot pass ``on_task``."""
    from jarvis.integrations import voice_native_tools

    observed = []

    class Live:
        async def _execute_tool(self, _fc):
            return None

        async def run(self):
            return None

        def _dispatch_native_agent(self, task, **_kwargs):
            scope = dispatch.current_source_scope()
            observed.append(
                (task, scope.source, scope.completion_owner, scope.conversation_id)
                if scope is not None else (task, "", "", "")
            )
            return True, "started"

    legacy = types.SimpleNamespace(
        JarvisLive=Live,
        TOOL_DECLARATIONS=[],
        types=types.SimpleNamespace(FunctionResponse=dict),
        _load_system_prompt=lambda: "persona",
    )
    monkeypatch.setattr(voice_tasks, "ensure_subscribed", lambda: None)
    monkeypatch.setattr(voice_tasks, "declarations", lambda: [])

    voice_native_tools.install(legacy)

    assert Live()._dispatch_native_agent("cek build") == (True, "started")
    assert observed == [("cek build", "voice-native", "registry", "voice-live")]
    assert dispatch.current_source_scope() is None


def test_dispatch_binds_registry_id_via_ingress_conversation_scope(monkeypatch):
    """Fase 38 — when no ``on_task`` callback is supplied (the FROZEN voice seam),
    dispatch still binds the real registry task ID into immediate context from
    the ingress scope's ``conversation_id`` before ACK."""
    _isolate_dispatch(monkeypatch)
    from jarvis.agent import loop as agent_loop
    from jarvis.agent import conversation_context

    bound: list[tuple[str, str]] = []
    real_bind = conversation_context.STORE.begin_task
    monkeypatch.setattr(
        conversation_context.STORE,
        "begin_task",
        lambda conversation_id, task_id, task, source: bound.append(
            (conversation_id, task_id)
        ) or real_bind(
            conversation_id, task_id=task_id, task=task, source=source
        ),
    )

    async def fake_run(_task, **_kwargs):
        return RunResult(ok=True, text="done", session_id="seam-bind")

    monkeypatch.setattr(agent_loop, "run", fake_run)

    with dispatch.source_scope(
        "voice-native",
        completion_owner="registry",
        conversation_id="voice-live",
    ):
        assert dispatch.dispatch_async("seam bind task") is True

    assert len(bound) == 1
    cid, tid = bound[0]
    assert cid == "voice-live"
    assert tid.startswith("T-")

    active = conversation_context.STORE.active_tasks("voice-live")
    assert any(a["task_id"] == tid for a in active)
    assert any(a["source"] == "voice-native" for a in active)
    assert dispatch.current_source_scope() is None

    # This characterization dispatches through a daemon worker. Drain its
    # active handle before the next test may replace the loop seam.
    deadline = time.monotonic() + 2.0
    while dispatch.active_count() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert dispatch.active_count() == 0
    REGISTRY.clear()
    with dispatch._active_lock:
        dispatch._active.clear()
