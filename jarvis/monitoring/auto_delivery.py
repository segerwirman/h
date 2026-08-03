"""Phase 17C automatic delivery for already-bounded monitor scan results."""
from __future__ import annotations
from collections.abc import Callable
from typing import Any

from jarvis.monitoring.delivery import delivery_allowed, render_digest


def _default_telegram_send(text: str) -> bool:
    """Whitelist-gated remote notification; imported only when delivery runs."""
    from jarvis.agent.adapters.telegram import send_from_anywhere
    return bool(send_from_anywhere(text))


def _default_desktop_show(text: str) -> bool:
    """Use the existing UI notification event without importing a window."""
    from jarvis.core.bus import BUS
    BUS.publish("notify", title="Monitor update", body=text)
    return True


class MonitorDeliveryCoordinator:
    """Route safe monitor digests to injected Telegram/desktop sinks only."""

    def __init__(
        self,
        *,
        scheduler: Any,
        store: Any,
        telegram_send: Callable[[str], object] | None = None,
        desktop_show: Callable[[str], object] | None = None,
    ) -> None:
        self._scheduler = scheduler
        self._store = store
        self._telegram_send = telegram_send or _default_telegram_send
        self._desktop_show = desktop_show or _default_desktop_show
        self._job_modes: dict[str, str] = {}

    def bind_job(self, job: object, mode: str) -> None:
        """Bind a scheduler-created job to an allowlisted delivery mode."""
        job_id = job.get("id") if isinstance(job, dict) else None
        if not isinstance(job_id, str) or not job_id or not delivery_allowed(mode):
            raise ValueError("monitor delivery binding invalid")
        self._job_modes[job_id] = mode

    def run_due(self) -> list[dict]:
        """Deliver due monitor results through only their registered sink."""
        deliveries = []
        for entry in self._scheduler.tick_detailed():
            job = entry.get("job", {}) if isinstance(entry, dict) else {}
            mode = self._job_modes.get(job.get("id")) if isinstance(job, dict) else None
            if mode is not None:
                deliveries.append(self.deliver_result(mode, entry.get("result")))
        return deliveries

    @staticmethod
    def _digest(source: str, items: object) -> dict:
        return render_digest(source, items if isinstance(items, list) else [])

    def _deliver(self, target: str, digest: dict) -> dict:
        callback = self._telegram_send if target == "telegram" else self._desktop_show
        if callback is None:
            return {"delivered": False, "reason": "monitor_delivery_target_unavailable"}
        try:
            accepted = callback(digest["content"])
        except Exception:  # delivery integrations must not stop monitor ticks
            return {"delivered": False, "reason": "monitor_delivery_target_unavailable"}
        if accepted is False:
            return {"delivered": False, "reason": "monitor_delivery_target_unavailable"}
        return {"delivered": True, "target": target}

    def deliver_result(self, mode: str, result: object) -> dict:
        if not delivery_allowed(mode):
            return {"delivered": False, "reason": "monitor_delivery_mode_rejected"}
        if not isinstance(result, dict):
            return {"delivered": False, "reason": "monitor_delivery_payload_rejected"}
        source = str(result.get("source") or "")
        status = result.get("status")
        if not source or status not in {"new_items", "no_change"}:
            return {"delivered": False, "reason": "no_new_items"}
        if mode in {"on_change", "desktop_only", "both"} and status != "new_items":
            return {"delivered": False, "reason": "no_new_items"}
        items = result.get("items", [])
        if mode == "daily_digest":
            items = self._store.latest(source)
        digest = self._digest(source, items)
        if not digest.get("ok"):
            return {"delivered": False, "reason": digest.get("reason", "monitor_delivery_payload_rejected")}
        if mode == "desktop_only":
            return self._deliver("desktop", digest)
        if mode == "both":
            first = self._deliver("telegram", digest)
            second = self._deliver("desktop", digest)
            return {"delivered": first.get("delivered", False) or second.get("delivered", False), "target": "both"}
        return self._deliver("telegram", digest)

    def on_request(self, source: object) -> dict:
        name = getattr(source, "name", None)
        if not isinstance(name, str) or not name:
            return {"ok": False, "reason": "monitor_source_required"}
        return self._digest(name, self._store.latest(name))


__all__ = ["MonitorDeliveryCoordinator"]
