"""Phase 9 canary runner only reports bounded disposable-fixture metadata."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cua_desktop_safe_canary.py"


def _canary_module():
    spec = importlib.util.spec_from_file_location("desktop_safe_canary", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_canary_summarizes_all_disposable_acceptances_as_opaque_statuses():
    module = _canary_module()
    calls = []

    def runner(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout="{'accepted': True, 'executed': True, 'verified': True, 'marker_changed': True}",
            stderr="",
        )

    summary = module.run_local_canary(runner=runner)

    assert calls == [
        [sys.executable, str(SCRIPT.parent / "cua_safe_click_acceptance.py")],
        [sys.executable, str(SCRIPT.parent / "cua_safe_scroll_acceptance.py")],
        [sys.executable, str(SCRIPT.parent / "cua_safe_set_value_acceptance.py")],
    ]
    assert summary == {
        "accepted": True,
        "fixtures": [
            {"name": "click", "accepted": True, "executed": True, "verified": True},
            {"name": "scroll", "accepted": True, "executed": True, "verified": True},
            {"name": "set_value", "accepted": True, "executed": True, "verified": True},
        ],
    }


def test_canary_normalizes_timeout_and_passes_a_bounded_timeout_to_runner():
    module = _canary_module()
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        raise subprocess.TimeoutExpired(command, timeout=90)

    summary = module.run_local_canary(runner=runner)

    assert calls == [(
        [sys.executable, str(SCRIPT.parent / "cua_safe_click_acceptance.py")],
        {"capture_output": True, "text": True, "check": False, "timeout": 90},
    )]
    assert summary == {
        "accepted": False,
        "fixtures": [
            {"name": "click", "accepted": False, "reason": "canary_fixture_failed"},
            {"name": "scroll", "accepted": False, "reason": "canary_fixture_not_run"},
            {"name": "set_value", "accepted": False, "reason": "canary_fixture_not_run"},
        ],
    }


def test_canary_normalizes_fixture_failure_without_leaking_raw_ui_error():
    module = _canary_module()

    def runner(_command, **_kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout="{'accepted': False, 'error': 'password field raw ui text'}",
            stderr="native UIA password field failure",
        )

    summary = module.run_local_canary(runner=runner)

    assert summary == {
        "accepted": False,
        "fixtures": [
            {"name": "click", "accepted": False, "reason": "canary_fixture_failed"},
            {"name": "scroll", "accepted": False, "reason": "canary_fixture_not_run"},
            {"name": "set_value", "accepted": False, "reason": "canary_fixture_not_run"},
        ],
    }
    assert "password" not in repr(summary).lower()
