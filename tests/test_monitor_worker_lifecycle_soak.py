"""17L metadata-only monitor worker lifecycle soak contract."""
from __future__ import annotations


class _Result:
    def __init__(self, returncode=0, stdout="{'accepted': True, 'verified': True}"):
        self.returncode = returncode
        self.stdout = stdout


def test_soak_repeats_fixed_lifecycle_fixtures_and_returns_only_safe_metadata():
    from scripts.monitor_worker_lifecycle_soak import run_monitor_worker_soak

    calls = []
    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return _Result()

    summary = run_monitor_worker_soak(iterations=2, runner=runner)
    assert summary == {
        "accepted": True,
        "fixtures": [
            {"fixture": "enabled", "status": "passed", "iterations": 2},
            {"fixture": "disabled", "status": "passed", "iterations": 2},
            {"fixture": "safe_failure", "status": "passed", "iterations": 2},
            {"fixture": "restart", "status": "passed", "iterations": 2},
        ],
    }
    assert len(calls) == 8
    assert all(call[1]["timeout"] == 30 and call[1]["capture_output"] is True for call in calls)
    assert all(call[0][-1] in {"enabled", "disabled", "safe_failure", "restart"} for call in calls)
    assert "stdout" not in str(summary).lower() and "exception" not in str(summary).lower()


def test_soak_fails_closed_and_marks_later_fixtures_not_run_without_child_output():
    from scripts.monitor_worker_lifecycle_soak import run_monitor_worker_soak

    def runner(command, **kwargs):
        if command[-1] == "disabled":
            return _Result(returncode=1, stdout="Traceback private url https://secret.invalid")
        return _Result()

    assert run_monitor_worker_soak(iterations=2, runner=runner) == {
        "accepted": False,
        "fixtures": [
            {"fixture": "enabled", "status": "passed", "iterations": 2},
            {"fixture": "disabled", "status": "failed", "iterations": 2},
            {"fixture": "safe_failure", "status": "not_run", "iterations": 2},
            {"fixture": "restart", "status": "not_run", "iterations": 2},
        ],
    }


def test_soak_runner_has_fixed_no_shell_fixture_allowlist():
    from scripts import monitor_worker_lifecycle_soak as soak

    source = open(soak.__file__, encoding="utf-8").read()
    assert soak._FIXTURES == ("enabled", "disabled", "safe_failure", "restart")
    for forbidden in ("shell=True", "agent.cron", "dispatch.run_sync", "webbrowser", "raw_result", "exception_text"):
        assert forbidden not in source
    assert "monitor_worker_lifecycle_acceptance.py" in source
