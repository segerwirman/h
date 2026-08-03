"""17D main boot callback wires local briefing only after readiness."""
from __future__ import annotations
from pathlib import Path


def test_main_boot_done_starts_local_boot_briefing_with_drawer_and_tts():
    source = Path("jarvis/main.py").read_text(encoding="utf-8")
    assert "boot_briefing.start_if_enabled" in source
    assert "_record_task_result" in source
    assert "_speak_line" in source
    assert "send_from_anywhere" not in source


def test_boot_wiring_occurs_after_ready_log_not_before_boot_sequence():
    source = Path("jarvis/main.py").read_text(encoding="utf-8")
    callback = source[source.index("def on_boot_done"):source.index("BootSequence(on_boot_done).start()")]
    assert callback.index("CORE ONLINE") < callback.index("boot_briefing.start_if_enabled")
    assert "fetch_source" not in callback and "MonitorScheduler" not in callback
