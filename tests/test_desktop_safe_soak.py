"""Fase 10.5 soak runner only reports bounded aggregate-fixture metadata."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cua_desktop_safe_soak.py"


def _soak_module():
    spec = importlib.util.spec_from_file_location("desktop_safe_soak", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_soak_repeats_every_fixture_and_reports_opaque_aggregate():
    module = _soak_module()
    calls = []

    def runner(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout="{'accepted': True, 'executed': True, 'verified': True, 'marker_changed': True}",
            stderr="",
        )

    summary = module.run_soak(iterations=3, runner=runner)

    # Each of the four fixtures is exercised exactly `iterations` times.
    assert len(calls) == 15
    assert summary == {
        "accepted": True,
        "iterations": 3,
        "fixtures": [
            {"name": "click", "accepted": True, "iterations": 3, "passed": 3},
            {"name": "scroll", "accepted": True, "iterations": 3, "passed": 3},
            {"name": "set_value", "accepted": True, "iterations": 3, "passed": 3},
            {"name": "select_option", "accepted": True, "iterations": 3, "passed": 3},
            {"name": "toggle", "accepted": True, "iterations": 3, "passed": 3},
        ],
    }


def test_soak_fails_closed_on_a_single_flaky_iteration_without_leaking_raw_error():
    module = _soak_module()
    state = {"count": 0}

    def runner(_command, **_kwargs):
        state["count"] += 1
        # First fixture: pass twice, then flake on the third iteration.
        if state["count"] == 3:
            return SimpleNamespace(
                returncode=1,
                stdout="{'accepted': False, 'error': 'password field raw ui text'}",
                stderr="native UIA password field failure",
            )
        return SimpleNamespace(
            returncode=0,
            stdout="{'accepted': True, 'executed': True, 'verified': True}",
            stderr="",
        )

    summary = module.run_soak(iterations=5, runner=runner)

    assert summary == {
        "accepted": False,
        "iterations": 5,
        "fixtures": [
            {"name": "click", "accepted": False, "reason": "soak_fixture_failed",
             "iterations": 5, "passed": 2},
            {"name": "scroll", "accepted": False, "reason": "soak_fixture_not_run"},
            {"name": "set_value", "accepted": False, "reason": "soak_fixture_not_run"},
            {"name": "select_option", "accepted": False, "reason": "soak_fixture_not_run"},
            {"name": "toggle", "accepted": False, "reason": "soak_fixture_not_run"},
        ],
    }
    assert "password" not in repr(summary).lower()


def test_soak_normalizes_timeout_as_fixture_failure():
    module = _soak_module()

    def runner(command, **_kwargs):
        raise subprocess.TimeoutExpired(command, timeout=90)

    summary = module.run_soak(iterations=4, runner=runner)

    assert summary["accepted"] is False
    assert summary["fixtures"][0] == {
        "name": "click", "accepted": False, "reason": "soak_fixture_failed",
        "iterations": 4, "passed": 0,
    }
    assert all(f["reason"] == "soak_fixture_not_run" for f in summary["fixtures"][1:])
