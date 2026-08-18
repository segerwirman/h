"""Fase 35 Slice 10 — local agent-tool swallow observability."""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

from jarvis.core import quiet


def _spy(monkeypatch):
    events = []

    def record(event, exc=None, **_context):
        events.append((event, type(exc).__name__ if exc is not None else None))

    monkeypatch.setattr(quiet, "swallowed", record)
    return events


def test_execute_code_cleanup_failure_is_recorded(tmp_path, monkeypatch):
    from jarvis.agent.tools import code_exec

    events = _spy(monkeypatch)
    monkeypatch.setattr(code_exec, "data_dir", lambda: tmp_path)

    original_unlink = Path.unlink

    def fail_unlink(path, *args, **kwargs):
        raise OSError("temporary script locked")

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    result = asyncio.run(code_exec.ExecuteCode().run(
        "print(1)", language="python", timeout=5))

    assert result.ok is True
    assert events == [("agent.tools.code_exec.cleanup_failed", "OSError")]
    assert original_unlink is not fail_unlink


def test_process_probe_failure_is_recorded_and_other_rows_survive(monkeypatch):
    from jarvis.agent.tools import terminal

    events = _spy(monkeypatch)

    class NoSuchProcess(Exception):
        pass

    class AccessDenied(Exception):
        pass

    class BrokenProcess:
        @property
        def info(self):
            raise NoSuchProcess("process vanished")

    class HealthyProcess:
        info = {
            "pid": 42,
            "name": "healthy.exe",
            "cpu_percent": 1.5,
            "memory_info": types.SimpleNamespace(rss=2 * 1024 * 1024),
        }

    fake_psutil = types.SimpleNamespace(
        NoSuchProcess=NoSuchProcess,
        AccessDenied=AccessDenied,
        process_iter=lambda _fields: [BrokenProcess(), HealthyProcess()],
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    result = asyncio.run(terminal.ProcessList().run())

    assert result.ok is True
    assert result.display == "1 proses"
    assert "healthy.exe" in result.content
    assert events == [("agent.tools.terminal.process_probe_failed", "NoSuchProcess")]


def test_file_scan_failure_is_recorded_and_other_files_survive(tmp_path, monkeypatch):
    from jarvis.agent.tools import file_ops

    events = _spy(monkeypatch)
    good = tmp_path / "good.txt"
    broken = tmp_path / "broken.txt"
    good.write_text("needle here", encoding="utf-8")
    broken.write_text("needle but unreadable", encoding="utf-8")

    original_read_bytes = Path.read_bytes

    def read_bytes(path, *args, **kwargs):
        if path.name == broken.name:
            raise OSError("file disappeared")
        return original_read_bytes(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    result = asyncio.run(file_ops.FileSearch().run(
        pattern="needle", path=str(tmp_path), glob="*"))

    assert result.ok is True
    assert result.display == "1 hasil"
    assert str(good) in result.content
    assert events == [("agent.tools.file_ops.scan_skip_failed", "OSError")]
