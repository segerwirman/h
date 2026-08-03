"""Phase 9: run the bounded disposable desktop-safe canary matrix.

This wrapper only launches the three isolated local UIA fixtures already used by
acceptance testing. It reports status metadata only; raw fixture stdout/stderr,
UI labels, values, and native errors never enter the summary.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
_FIXTURE_TIMEOUT_S = 90


_FIXTURES = (
    ("click", "cua_safe_click_acceptance.py"),
    ("scroll", "cua_safe_scroll_acceptance.py"),
    ("set_value", "cua_safe_set_value_acceptance.py"),
)


def _fixture_ok(stdout: str) -> bool:
    """Accept only a bounded successful status payload from a fixture."""
    lines = [line.strip() for line in str(stdout).splitlines() if line.strip()]
    if not lines:
        return False
    try:
        payload = ast.literal_eval(lines[-1])
    except (SyntaxError, ValueError):
        return False
    return bool(
        isinstance(payload, dict)
        and payload.get("accepted") is True
        and payload.get("executed") is True
        and payload.get("verified") is True
    )


def run_local_canary(*, runner: Callable[..., Any] = subprocess.run) -> dict:
    """Execute isolated fixtures sequentially and return opaque canary status."""
    scripts = Path(__file__).resolve().parent
    fixtures: list[dict[str, object]] = []
    failed = False
    for name, filename in _FIXTURES:
        if failed:
            fixtures.append({"name": name, "accepted": False, "reason": "canary_fixture_not_run"})
            continue
        try:
            result = runner(
                [sys.executable, str(scripts / filename)],
                capture_output=True,
                text=True,
                check=False,
                timeout=_FIXTURE_TIMEOUT_S,
            )
            accepted = result.returncode == 0 and _fixture_ok(result.stdout)
        except Exception:
            accepted = False
        if accepted:
            fixtures.append({"name": name, "accepted": True, "executed": True, "verified": True})
            continue
        fixtures.append({"name": name, "accepted": False, "reason": "canary_fixture_failed"})
        failed = True
    return {"accepted": not failed, "fixtures": fixtures}


def main() -> int:
    summary = run_local_canary()
    print(summary)
    return 0 if summary["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
