"""Fase 14.5 visual soak runner hanya merangkum status fixture metadata-only."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "desktop_visual_read_only_soak.py"


def _module():
    spec = importlib.util.spec_from_file_location("desktop_visual_soak", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_visual_soak_repeats_static_privacy_fixtures_and_reports_opaque_aggregate():
    module = _module()
    calls = []

    def runner(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="{'accepted': True, 'verified': True}", stderr="")

    summary = module.run_visual_soak(iterations=3, runner=runner)

    assert calls == [
        [sys.executable, str(SCRIPT.parent / "desktop_visual_read_only_acceptance.py"), "safe_frame"],
        [sys.executable, str(SCRIPT.parent / "desktop_visual_read_only_acceptance.py"), "safe_frame"],
        [sys.executable, str(SCRIPT.parent / "desktop_visual_read_only_acceptance.py"), "safe_frame"],
        [sys.executable, str(SCRIPT.parent / "desktop_visual_read_only_acceptance.py"), "denylisted"],
        [sys.executable, str(SCRIPT.parent / "desktop_visual_read_only_acceptance.py"), "denylisted"],
        [sys.executable, str(SCRIPT.parent / "desktop_visual_read_only_acceptance.py"), "denylisted"],
        [sys.executable, str(SCRIPT.parent / "desktop_visual_read_only_acceptance.py"), "capture_unavailable"],
        [sys.executable, str(SCRIPT.parent / "desktop_visual_read_only_acceptance.py"), "capture_unavailable"],
        [sys.executable, str(SCRIPT.parent / "desktop_visual_read_only_acceptance.py"), "capture_unavailable"],
    ]
    assert summary == {
        "accepted": True,
        "iterations": 3,
        "fixtures": [
            {"name": "safe_frame", "accepted": True, "iterations": 3, "passed": 3},
            {"name": "denylisted", "accepted": True, "iterations": 3, "passed": 3},
            {"name": "capture_unavailable", "accepted": True, "iterations": 3, "passed": 3},
        ],
    }


def test_visual_soak_fails_closed_and_never_leaks_raw_fixture_content():
    module = _module()
    state = {"count": 0}

    def runner(_command, **_kwargs):
        state["count"] += 1
        if state["count"] == 2:
            return SimpleNamespace(
                returncode=1,
                stdout="{'accepted': False, 'ocr': 'password reset code 123456'}",
                stderr="raw screenshot path C:/private/screen.png",
            )
        return SimpleNamespace(returncode=0, stdout="{'accepted': True, 'verified': True}", stderr="")

    summary = module.run_visual_soak(iterations=3, runner=runner)

    assert summary == {
        "accepted": False,
        "iterations": 3,
        "fixtures": [
            {"name": "safe_frame", "accepted": False, "reason": "visual_fixture_failed",
             "iterations": 3, "passed": 1},
            {"name": "denylisted", "accepted": False, "reason": "visual_fixture_not_run"},
            {"name": "capture_unavailable", "accepted": False, "reason": "visual_fixture_not_run"},
        ],
    }
    assert "password" not in repr(summary).lower()
    assert "screen" not in repr(summary).lower()


def test_visual_soak_normalizes_timeout_without_raw_error():
    module = _module()

    def runner(command, **_kwargs):
        raise subprocess.TimeoutExpired(command, timeout=30)

    summary = module.run_visual_soak(iterations=2, runner=runner)

    assert summary["accepted"] is False
    assert summary["fixtures"][0] == {
        "name": "safe_frame", "accepted": False, "reason": "visual_fixture_failed",
        "iterations": 2, "passed": 0,
    }
    assert all(item["reason"] == "visual_fixture_not_run" for item in summary["fixtures"][1:])


def test_visual_service_does_not_retain_frame_after_many_observations():
    import numpy as np
    from PIL import Image
    from jarvis.automation.visual_observe import VisualObserveService

    frames = []

    def capture():
        frame = Image.fromarray(np.full((8, 8, 3), 128, dtype=np.uint8), "RGB")
        frames.append(frame)
        return frame

    service = VisualObserveService(
        foreground=lambda: ("Fixture", "Fixture"), capture=capture, denylisted=lambda *_: False,
    )
    for _ in range(100):
        report = service.observe(session_id="soak")
        assert set(report) == {"visual_observation_id", "brightness", "complexity", "dominant_tone"}

    assert not {"history", "last_image", "screenshot_ref", "ocr_blocks"} & set(vars(service))
    assert len(frames) == 100


def test_visual_service_capture_exception_does_not_retain_partial_frame():
    from jarvis.automation.visual_observe import VisualObserveService

    calls = []

    def capture():
        calls.append("capture")
        raise RuntimeError("raw image failure")

    service = VisualObserveService(
        foreground=lambda: ("Fixture", "Fixture"), capture=capture, denylisted=lambda *_: False,
    )

    try:
        service.observe(session_id="soak")
    except RuntimeError:
        pass
    else:
        raise AssertionError("capture exception must propagate to tool fail-closed boundary")

    assert calls == ["capture"]
    assert not vars(service).keys() & {"image", "last_image", "history", "screenshot_ref"}


def test_capture_runs_inside_capture_pause_and_closes_it_even_on_failure():
    """Capture wajib berada DI DALAM ``capture_pause``, dan pause wajib tertutup.

    ``capture_pause`` menjeda authority/overlay Screen Control selama pengambilan
    citra. Bila capture dilakukan di luar context manager-nya, jeda itu tak pernah
    terjadi; bila ``with`` tidak menutup, authority bisa nyangkut. Keduanya
    kegagalan authority, bukan sekadar kebocoran memori.

    Tak ada tes yang memakai ``capture_pause`` sebelum 2026-08-31 — mutan yang
    mengeluarkan capture dari ``with`` **selamat** tanpa satu pun tes merah.
    Tes ini menutup celah itu, pada kedua arah: kegagalan dan keberhasilan.
    """
    from jarvis.automation.visual_observe import VisualObserveService

    events: list[str] = []

    class _Pause:
        def __enter__(self):
            events.append("enter")
            return self

        def __exit__(self, exc_type, exc, _tb):
            events.append(f"exit(raised={exc_type is not None})")
            return False              # jangan redam exception

    def boom():
        events.append("capture")
        raise RuntimeError("raw image failure")

    service = VisualObserveService(
        foreground=lambda: ("Fixture", "Fixture"), capture=boom,
        denylisted=lambda *_: False, capture_pause=_Pause,
    )

    with pytest.raises(RuntimeError):
        service.observe(session_id="soak")

    # Urutan membuktikan capture benar-benar terjadi di dalam pause.
    assert events == ["enter", "capture", "exit(raised=True)"], events

    # Dan pause tertutup meski exception sedang melintas.
    assert "exit(raised=True)" in events


def test_visual_soak_source_never_imports_ocr_or_persistence_apis():
    source = (ROOT / "jarvis" / "automation" / "visual_observe.py").read_text(encoding="utf-8").casefold()

    assert "pytesseract" not in source
    assert ".save(" not in source
    assert "screenshot_ref" not in source
    assert "screenawareness" not in source
    assert "imagegrab.grab" in source
