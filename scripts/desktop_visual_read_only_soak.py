"""Fase 14.5: repeat static privacy fixtures for visual read-only.

Every child fixture is a static local script with a generated frame or a
controlled privacy/capture-unavailable seam. The runner never captures the
user's screen and reports opaque aggregate status only.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

_FIXTURE_TIMEOUT_S = 30
_DEFAULT_ITERATIONS = 20
_FIXTURES = ("safe_frame", "denylisted", "capture_unavailable")
_ACCEPTANCE = "desktop_visual_read_only_acceptance.py"


def _fixture_ok(stdout: str) -> bool:
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
        and payload.get("verified") is True
    )


def run_visual_soak(*, iterations: int = _DEFAULT_ITERATIONS,
                    runner: Callable[..., Any] = subprocess.run) -> dict:
    """Run static visual privacy fixtures sequentially, fail-closed on one error."""
    total = max(1, int(iterations))
    scripts = Path(__file__).resolve().parent
    fixtures: list[dict[str, object]] = []
    failed = False
    for name in _FIXTURES:
        if failed:
            fixtures.append({"name": name, "accepted": False, "reason": "visual_fixture_not_run"})
            continue
        passed = 0
        for _ in range(total):
            try:
                result = runner(
                    [sys.executable, str(scripts / _ACCEPTANCE), name],
                    capture_output=True, text=True, check=False, timeout=_FIXTURE_TIMEOUT_S,
                )
                accepted = result.returncode == 0 and _fixture_ok(result.stdout)
            except Exception:
                accepted = False
            if not accepted:
                break
            passed += 1
        if passed == total:
            fixtures.append({"name": name, "accepted": True, "iterations": total, "passed": total})
            continue
        fixtures.append({"name": name, "accepted": False, "reason": "visual_fixture_failed",
                         "iterations": total, "passed": passed})
        failed = True
    return {"accepted": not failed, "iterations": total, "fixtures": fixtures}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Visual read-only privacy soak.")
    parser.add_argument("--iterations", type=int, default=_DEFAULT_ITERATIONS)
    args = parser.parse_args()
    summary = run_visual_soak(iterations=args.iterations)
    print(summary)
    return 0 if summary["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
