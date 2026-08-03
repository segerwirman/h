"""Phase 17D: boot briefing runs after readiness, never blocks boot."""
from __future__ import annotations


def test_monitor_boot_briefing_is_off_by_default(monkeypatch):
    from jarvis.integrations import boot_briefing
    monkeypatch.setattr(boot_briefing.briefing, "boot_briefing_enabled", lambda: False)
    started = []
    assert boot_briefing.start_if_enabled(lambda text: started.append(text)) is False
    assert started == []


def test_enabled_boot_briefing_starts_background_worker_and_never_sends_telegram(monkeypatch):
    from jarvis.integrations import boot_briefing
    monkeypatch.setattr(boot_briefing.briefing, "boot_briefing_enabled", lambda: True)
    calls = []
    class FakeThread:
        def __init__(self, *, target, daemon, name):
            calls.extend([daemon, name]); self.target = target
        def start(self):
            self.target()
    monkeypatch.setattr(boot_briefing.threading, "Thread", FakeThread)
    monkeypatch.setattr(boot_briefing, "build_local_briefing", lambda: "Monitor aman")
    delivered = []
    assert boot_briefing.start_if_enabled(delivered.append) is True
    assert delivered == ["Monitor aman"]
    assert calls == [True, "boot-briefing"]


def test_boot_briefing_failure_is_swallowed_and_does_not_leak(monkeypatch):
    from jarvis.integrations import boot_briefing
    monkeypatch.setattr(boot_briefing.briefing, "boot_briefing_enabled", lambda: True)
    monkeypatch.setattr(boot_briefing, "build_local_briefing", lambda: (_ for _ in ()).throw(RuntimeError("private db")))
    class InlineThread:
        def __init__(self, *, target, **_): self.target = target
        def start(self): self.target()
    monkeypatch.setattr(boot_briefing.threading, "Thread", InlineThread)
    delivered = []
    assert boot_briefing.start_if_enabled(delivered.append) is True
    assert delivered == []


def test_build_local_briefing_uses_existing_tool_not_monitor_fetch(monkeypatch):
    from jarvis.integrations import boot_briefing
    class FakeTool:
        async def run(self):
            class Result:
                ok = True
                content = {"briefing": "Agenda dan monitor aman"}
            return Result()
    monkeypatch.setattr(boot_briefing, "_tool", lambda: FakeTool())
    assert boot_briefing.build_local_briefing() == "Agenda dan monitor aman"
    source = open(boot_briefing.__file__, encoding="utf-8").read()
    assert "fetch_source" not in source and "send_from_anywhere" not in source
