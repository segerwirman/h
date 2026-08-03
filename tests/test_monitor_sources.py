"""Fase 17A source registry: public/read-only/allowlisted only."""
from __future__ import annotations

import pytest


def test_public_https_rss_source_validates():
    from jarvis.monitoring.sources import MonitorSource
    source = MonitorSource.create("AI Blog", "https://example.org/feed.xml", "rss", rate_limit_s=60)
    assert source.name == "AI Blog"
    assert source.mode == "rss"
    assert source.url == "https://example.org/feed.xml"


@pytest.mark.parametrize("url", [
    "http://example.org/feed", "ftp://example.org/feed", "file:///private/x",
    "https://user:pass@example.org/feed", "https://example.org/login",
    "https://bank.example.org/account", "https://example.org/payment", "https://example.org/captcha",
])
def test_source_rejects_nonpublic_or_sensitive_urls(url):
    from jarvis.monitoring.sources import MonitorSource
    with pytest.raises(ValueError):
        MonitorSource.create("Bad", url, "rss", rate_limit_s=60)


@pytest.mark.parametrize("mode", ["browser", "login", "shell", "crawl", "unknown"])
def test_source_rejects_modes_outside_api_rss_html(mode):
    from jarvis.monitoring.sources import MonitorSource
    with pytest.raises(ValueError):
        MonitorSource.create("Bad", "https://example.org/feed", mode, rate_limit_s=60)


def test_source_requires_bounded_positive_rate_limit():
    from jarvis.monitoring.sources import MonitorSource
    for value in (0, -1, 1, 4):
        with pytest.raises(ValueError):
            MonitorSource.create("Bad", "https://example.org/feed", "rss", rate_limit_s=value)


def test_source_metadata_has_no_credentials_or_headers():
    from jarvis.monitoring.sources import MonitorSource
    s = MonitorSource.create("Safe", "https://example.org/feed", "rss", rate_limit_s=60)
    assert not {"headers", "cookies", "password", "token", "selector"} & set(vars(s))


def test_source_registry_is_bounded_and_rejects_duplicate_url():
    from jarvis.monitoring.sources import SourceRegistry
    r = SourceRegistry(max_sources=2)
    r.add("A", "https://a.org/feed", "rss", rate_limit_s=60)
    with pytest.raises(ValueError):
        r.add("B", "https://a.org/feed", "rss", rate_limit_s=60)
    r.add("B", "https://b.org/feed", "api", rate_limit_s=60)
    with pytest.raises(ValueError):
        r.add("C", "https://c.org/feed", "html", rate_limit_s=60)


def test_registry_public_view_never_has_auth_or_raw_url_query_secret():
    from jarvis.monitoring.sources import SourceRegistry
    r = SourceRegistry()
    r.add("Safe", "https://example.org/feed", "rss", rate_limit_s=60)
    view = r.public_view()
    assert view == [{"name": "Safe", "url": "https://example.org/feed", "mode": "rss", "rate_limit_s": 60}]
