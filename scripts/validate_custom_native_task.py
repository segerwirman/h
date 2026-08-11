"""Run one synthetic long native task through the configured heavy provider."""

from __future__ import annotations

import argparse
import json
import time

from jarvis.agent import dispatch, model_routing
from jarvis.agent.tasks import REGISTRY, TaskStatus


_PROMPT = (
    "Create a synthetic read-only validation report with thirty numbered items. "
    "Do not use tools, files, URLs, credentials, or repository data. "
    "Return the complete report as the final answer."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    client, provider_name, reason = model_routing.heavy_resolution()
    if client is None or provider_name != "custom":
        print(json.dumps({
            "ok": False,
            "provider": provider_name,
            "error": reason or "heavy provider is not custom",
        }, sort_keys=True))
        return 1

    task = dispatch.dispatch_task(
        _PROMPT,
        title="Synthetic custom-provider validation",
        timeout_s=args.timeout,
        allowed_tools=[],
    )
    if task is None:
        print(json.dumps({
            "ok": False,
            "provider": provider_name,
            "error": "native task did not start",
        }, sort_keys=True))
        return 1

    deadline = time.monotonic() + args.timeout + 5.0
    terminal = {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED}
    current = task
    while time.monotonic() < deadline:
        current = REGISTRY.get(task.id) or current
        if current.status in terminal:
            break
        time.sleep(0.25)
    else:
        REGISTRY.cancel(task.id)
        current = REGISTRY.get(task.id) or current

    ok = current.status == TaskStatus.DONE
    print(json.dumps({
        "ok": ok,
        "provider": provider_name,
        "task_id": current.id,
        "status": current.status.value,
        "elapsed_s": round(current.elapsed, 1),
        "result_present": bool(current.result),
        "error_present": bool(current.error),
    }, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
