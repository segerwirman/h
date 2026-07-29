"""Bounded outbound delivery retry without leaking transport errors."""
from __future__ import annotations


def deliver(send, retries: int = 1):
    """Call send at most retries + 1 times; return None on final failure."""
    for _ in range(max(0, int(retries)) + 1):
        try:
            return send()
        except Exception:  # noqa: BLE001
            pass
    return None
