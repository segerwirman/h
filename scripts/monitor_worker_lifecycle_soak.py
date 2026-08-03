"""Metadata-only low-N soak for static monitor worker lifecycle fixtures."""
from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

_FIXTURE_TIMEOUT_S = 30
_DEFAULT_ITERATIONS = 3
_FIXTURES = ("enabled", "disabled", "safe_failure", "restart")
_ACCEPTANCE = "monitor_worker_lifecycle_acceptance.py"


def _fixture_ok(stdout: str) -> bool:
    lines = [line.strip() for line in str(stdout).splitlines() if line.strip()]
    if not lines:
        return False
    try:
        payload = ast.literal_eval(lines[-1])
    except (SyntaxError, ValueError):
        return False
    return isinstance(payload, dict) and payload == {"accepted": True, "verified": True}


def run_monitor_worker_soak(*, iterations: int = _DEFAULT_ITERATIONS,
                            runner: Callable[..., Any] = subprocess.run) -> dict:
    """Run the fixed local lifecycle fixture allowlist sequentially and fail closed."""
    total = max(1, int(iterations))
    scripts = Path(__file__).resolve().parent
    fixtures: list[dict[str, object]] = []
    failed = False
    for fixture in _FIXTURES:
        if failed:
            fixtures.append({"fixture": fixture, "status": "not_run", "iterations": total})
            continue
        passed = 0
        for _ in range(total):
            try:
                result = runner(
                    [sys.executable, str(scripts / _ACCEPTANCE), fixture],
                    capture_output=True, text=True, check=False, timeout=_FIXTURE_TIMEOUT_S,
                )
                accepted = result.returncode == 0 and _fixture_ok(result.stdout)
            except Exception:
                accepted = False
            if not accepted:
                break
            passed += 1
        status = "passed" if passed == total else "failed"
        fixtures.append({"fixture": fixture, "status": status, "iterations": total})
        failed = failed or status == "failed"
    return {"accepted": not failed, "fixtures": fixtures}


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Monitor worker lifecycle soak.")
    parser.add_argument("--iterations", type=int, default=_DEFAULT_ITERATIONS)
    args = parser.parse_args()
    summary = run_monitor_worker_soak(iterations=args.iterations)
    print(summary)
    return 0 if summary["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
