"""Fase 17A: fetch monitor read-only dengan health reason aman."""
from __future__ import annotations


def _source(mode="rss"):
    from jarvis.monitoring.sources import MonitorSource
    return MonitorSource.create("Test", "https://example.org/feed", mode, rate_limit_s=60)


def test_rss_fetch_returns_bounded_public_items():
    from jarvis.monitoring.fetch import fetch_source
    xml = b"<rss><channel><item><title>One</title><link>https://example.org/a</link><pubDate>today</pubDate></item><item><title>Two</title><link>https://example.org/b</link></item></channel></rss>"
    out = fetch_source(_source(), get=lambda url, timeout: xml, max_items=1)
    assert out == {"ok": True, "source": "Test", "mode": "rss", "items": [{"title": "One", "url": "https://example.org/a", "published": "today"}]}


def test_fetch_failure_returns_reason_without_raw_error_or_html():
    from jarvis.monitoring.fetch import fetch_source
    def boom(url, timeout): raise RuntimeError("cookie=secret raw html")
    out = fetch_source(_source(), get=boom)
    assert out == {"ok": False, "source": "Test", "reason": "source_unavailable"}
    assert "secret" not in str(out)


def test_html_mode_extracts_bounded_links_not_raw_page():
    from jarvis.monitoring.fetch import fetch_source
    html = b'<html><a href="https://example.org/a"> Article A </a><a href="/b">B</a></html>'
    out = fetch_source(_source("html"), get=lambda url, timeout: html, max_items=2)
    assert out["ok"] is True
    assert len(out["items"]) == 2
    assert "<html" not in str(out).lower()


def test_api_mode_requires_json_list_and_rejects_malformed():
    from jarvis.monitoring.fetch import fetch_source
    out = fetch_source(_source("api"), get=lambda url, timeout: b'{"token":"no"}')
    assert out == {"ok": False, "source": "Test", "reason": "source_malformed"}


def test_fetch_never_uses_browser_or_login_parameters():
    from jarvis.monitoring.fetch import fetch_source
    import inspect
    sig = str(inspect.signature(fetch_source))
    assert "browser" not in sig and "login" not in sig and "cookie" not in sig


def test_fetch_caps_items_and_text_lengths():
    from jarvis.monitoring.fetch import fetch_source
    xml = ("<rss><channel>" + "".join(f"<item><title>{'x'*500}{i}</title><link>https://example.org/{i}</link></item>" for i in range(20)) + "</channel></rss>").encode()
    out = fetch_source(_source(), get=lambda u,t: xml, max_items=3)
    assert len(out["items"]) == 3
    assert all(len(item["title"]) <= 200 for item in out["items"])
