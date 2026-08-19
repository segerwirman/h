"""Lifecycle facade for Jarvis-owned Chrome CDP.

This module never attaches to the user's everyday Chrome. It delegates every
lifecycle operation to the single browser host and exposes aggregate state only;
page URLs, titles, DOM, and profile contents do not cross this boundary.
"""
from __future__ import annotations

import threading

from jarvis.agent.tools import browser

_lock = threading.Lock()


def status() -> dict:
    """Return aggregate owned-CDP status without exposing page metadata."""
    return browser.browser_cdp_status()


def ensure() -> dict:
    """Start the one owned host, waiting for its bounded readiness result."""
    with _lock:
        try:
            return browser.ensure_browser_cdp()
        except Exception as exc:  # noqa: BLE001
            result = status()
            result.update({
                "owned": False,
                "ready": False,
                "reason": str(exc)[:200],
            })
            return result


def close() -> dict:
    """Request bounded graceful close; never force-kill an unknown process."""
    with _lock:
        try:
            browser.shutdown_browser_cdp()
        except Exception as exc:  # noqa: BLE001
            result = status()
            result.update({"closed": False, "reason": str(exc)[:200]})
            return result
        result = status()
        result["closed"] = result["state"] == "stopped"
        if not result["closed"] and not result["reason"]:
            result["reason"] = "dedicated CDP masih memiliki survivor"
        return result


__all__ = ["close", "ensure", "status"]
