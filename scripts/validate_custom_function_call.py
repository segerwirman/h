"""Run a synthetic live FunctionCall probe against the custom provider."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json

from jarvis.agent.function_call_probe import run_custom_probe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-insecure-http",
        action="store_true",
        help="Allow the configured public HTTP endpoint for this probe.",
    )
    args = parser.parse_args()
    result = run_custom_probe(allow_insecure_http=args.allow_insecure_http)
    print(json.dumps(asdict(result), ensure_ascii=True, sort_keys=True))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
