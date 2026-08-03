"""Phase 17C: bounded monitor delivery modes."""
from __future__ import annotations

import pytest


def _items(n=3):
    return [{"title": f"Artikel {i}", "url": f"https://example.org/{i}", "published": "today", "hash": "x"} for i in range(n)]


def test_on_request_renders_bounded_digest():
    from jarvis.monitoring.delivery import render_digest
    out = render_digest("AI Blog", _items(10), max_items=3, max_chars=300)
    assert out["ok"] is True
    assert out["content"].count("Artikel") == 3
    assert len(out["content"]) <= 300


def test_render_digest_rejects_sensitive_or_raw_payload():
    from jarvis.monitoring.delivery import render_digest
    out = render_digest("X", [{"title":"A", "url":"https://x/a", "body":"secret"}])
    assert out == {"ok": False, "reason": "monitor_delivery_payload_rejected"}


def test_delivery_modes_are_allowlisted():
    from jarvis.monitoring.delivery import delivery_allowed
    assert delivery_allowed("on_request") is True
    assert delivery_allowed("desktop_only") is True
    assert delivery_allowed("on_change") is True
    assert delivery_allowed("daily_digest") is True
    assert delivery_allowed("shell") is False


def test_automatic_modes_defer_without_safe_scheduler():
    from jarvis.monitoring.delivery import plan_delivery
    assert plan_delivery("on_change", scheduler_ready=False) == {"dispatch": False, "reason": "monitor_scheduler_not_ready"}
    assert plan_delivery("daily_digest", scheduler_ready=False) == {"dispatch": False, "reason": "monitor_scheduler_not_ready"}


def test_on_request_is_immediate_and_desktop_only_never_remote():
    from jarvis.monitoring.delivery import plan_delivery
    assert plan_delivery("on_request", scheduler_ready=False) == {"dispatch": True, "target": "requester"}
    assert plan_delivery("desktop_only", scheduler_ready=True) == {"dispatch": True, "target": "desktop"}


def test_digest_never_contains_raw_url_query_secret():
    from jarvis.monitoring.delivery import render_digest
    out=render_digest("X", [{"title":"A", "url":"https://x/a?token=secret", "published":""}])
    assert out == {"ok": False, "reason": "monitor_delivery_payload_rejected"}


@pytest.mark.parametrize("query", [
    "api_key=zzz", "apikey=zzz", "access_token=zzz", "client_secret=zzz",
    "passwd=zzz", "x-password=zzz", "key=zzz", "secret=zzz",
])
def test_digest_rejects_substring_credential_query_keys(query):
    from jarvis.monitoring.delivery import render_digest
    out = render_digest("X", [{"title": "A", "url": f"https://x.org/a?{query}", "published": ""}])
    assert out == {"ok": False, "reason": "monitor_delivery_payload_rejected"}
