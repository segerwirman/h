from __future__ import annotations

import sys
from types import SimpleNamespace

from actions import system_monitor
from jarvis.core import quiet


def _spy_swallowed(monkeypatch):
    events = []

    def record(event, exc=None, **context):
        events.append((event, exc, context))

    monkeypatch.setattr(quiet, "swallowed", record)
    return events


def test_pynvml_failure_is_recorded_and_falls_through(monkeypatch):
    events = _spy_swallowed(monkeypatch)
    pynvml = SimpleNamespace(
        nvmlInit=lambda: (_ for _ in ()).throw(RuntimeError("NVML unavailable")),
    )
    monkeypatch.setitem(sys.modules, "pynvml", pynvml)
    monkeypatch.setattr(system_monitor, "_nvml_gpu", lambda: -1.0)

    result = system_monitor._get_gpu_usage()

    assert result == -1.0
    assert [event[0] for event in events] == [
        "actions.system_monitor.gpu_pynvml_failed"
    ]
    assert isinstance(events[0][1], RuntimeError)


def test_psutil_temperature_failure_is_recorded_and_falls_back(monkeypatch):
    events = _spy_swallowed(monkeypatch)
    monkeypatch.setattr(system_monitor, "_OS", "Linux")

    def boom():
        raise OSError("temperature unavailable")

    monkeypatch.setattr(
        system_monitor.psutil, "sensors_temperatures", boom, raising=False
    )

    result = system_monitor._get_cpu_temp()

    assert result == -1.0
    assert [event[0] for event in events] == [
        "actions.system_monitor.cpu_temp_psutil_failed"
    ]
    assert isinstance(events[0][1], OSError)


def test_wmi_temperature_failure_is_recorded_and_keeps_fallback(monkeypatch):
    events = _spy_swallowed(monkeypatch)
    monkeypatch.setattr(system_monitor, "_OS", "Windows")
    monkeypatch.setattr(
        system_monitor.psutil, "sensors_temperatures", lambda: {}, raising=False
    )

    class BrokenWmi:
        def __init__(self, **_kwargs):
            raise RuntimeError("WMI unavailable")

    monkeypatch.setitem(sys.modules, "wmi", SimpleNamespace(WMI=BrokenWmi))

    result = system_monitor._get_cpu_temp()

    assert result == -1.0
    assert [event[0] for event in events] == [
        "actions.system_monitor.cpu_temp_wmi_failed"
    ]
    assert isinstance(events[0][1], RuntimeError)
