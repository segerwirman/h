"""A51e: Telegram producer must use the runtime-owned setup queue singleton.

Regression: producer created its own SetupQueue() instance while the window
reads the get_setup_queue() singleton — a staged request would never be found
by the desktop approval sheet. Both sides must share one runtime-owned queue.
"""
import os

import pytest

_TG = os.path.join(os.path.dirname(__file__), "..", "jarvis", "agent", "adapters", "telegram.py")


def test_telegram_producer_uses_runtime_owned_singleton_queue():
    source = open(_TG, encoding="utf-8").read()
    assert "get_setup_queue()" in source, \
        "producer harus memakai get_setup_queue() singleton"
    assert "SetupQueue()" not in source, \
        "producer tidak boleh membuat instance SetupQueue sendiri"
    assert "BUS.publish(\"remote_setup.pending\", request_id=str(request_id))" in source, \
        "BUS hanya membawa request_id opaque, tanpa queue caller-supplied"
