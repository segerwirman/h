"""Fase 10.5: soak/repeatability runner for the bounded desktop-safe matrix.

Repeats each isolated disposable acceptance fixture N times and reports only
aggregate opaque status. Raw fixture stdout/stderr, UI labels, values, and
native errors never enter the summary. A single failed or timed-out iteration
fails that fixture closed; later fixtures are marked not-run.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

_FIXTURE_TIMEOUT_S = 90
_DEFAULT_ITERATIONS = 20

_FIXTURES = (
    ("click", "cua_safe_click_acceptance.py"),
    ("scroll", "cua_safe_scroll_acceptance.py"),
    ("set_value", "cua_safe_set_value_acceptance.py"),
    ("select_option", "cua_safe_select_option_acceptance.py"),
    ("toggle", "cua_safe_toggle_acceptance.py"),
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


def run_soak(*, iterations: int = _DEFAULT_ITERATIONS,
             runner: Callable[..., Any] = subprocess.run) -> dict:
    """Run each fixture ``iterations`` times; return opaque aggregate status."""
    total = max(1, int(iterations))
    scripts = Path(__file__).resolve().parent
    fixtures: list[dict[str, object]] = []
    aborted = False
    for name, filename in _FIXTURES:
        if aborted:
            fixtures.append({"name": name, "accepted": False, "reason": "soak_fixture_not_run"})
            continue
        passed = 0
        for _ in range(total):
            try:
                result = runner(
                    [sys.executable, str(scripts / filename)],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=_FIXTURE_TIMEOUT_S,
                )
                ok = result.returncode == 0 and _fixture_ok(result.stdout)
            except Exception:
                ok = False
            if not ok:
                break
            passed += 1
        if passed == total:
            fixtures.append({"name": name, "accepted": True, "iterations": total, "passed": total})
            continue
        fixtures.append({"name": name, "accepted": False, "reason": "soak_fixture_failed",
                         "iterations": total, "passed": passed})
        aborted = True
    return {"accepted": not aborted, "iterations": total, "fixtures": fixtures}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Desktop-safe soak/repeatability run.")
    parser.add_argument("--iterations", type=int, default=_DEFAULT_ITERATIONS)
    args = parser.parse_args()
    summary = run_soak(iterations=args.iterations)
    print(summary)
    return 0 if summary["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
