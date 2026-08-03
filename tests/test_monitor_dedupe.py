"""Phase 17B: bounded monitor store + canonical dedupe."""
from __future__ import annotations


def test_canonical_url_removes_fragment_and_tracking():
    from jarvis.monitoring.store import canonical_url
    assert canonical_url("https://EXAMPLE.org/a/?utm_source=x&b=2#top") == "https://example.org/a?b=2"


def test_store_first_scan_new_then_same_scan_no_change(tmp_path):
    from jarvis.monitoring.store import MonitorStore
    store = MonitorStore(tmp_path / "monitor.sqlite", max_items_per_source=3)
    items = [{"title":"One", "url":"https://example.org/a?utm_source=x", "published":"today"}]
    assert store.record_scan("source-a", items)["status"] == "new_items"
    assert store.record_scan("source-a", items)["status"] == "no_change"


def test_store_detects_changed_title_same_canonical_url(tmp_path):
    from jarvis.monitoring.store import MonitorStore
    store = MonitorStore(tmp_path / "monitor.sqlite", max_items_per_source=3)
    store.record_scan("s", [{"title":"Old", "url":"https://x.org/a", "published":""}])
    out = store.record_scan("s", [{"title":"New", "url":"https://x.org/a", "published":""}])
    assert out["status"] == "new_items"
    assert len(out["items"]) == 1


def test_store_caps_retained_items_and_has_no_raw_content(tmp_path):
    from jarvis.monitoring.store import MonitorStore
    store = MonitorStore(tmp_path / "monitor.sqlite", max_items_per_source=2)
    store.record_scan("s", [{"title":str(i), "url":f"https://x.org/{i}", "published":""} for i in range(5)])
    rows = store.latest("s")
    assert len(rows) == 2
    assert all(set(row) == {"title", "url", "published", "hash"} for row in rows)


def test_runner_returns_source_failed_without_raw_fetch_error(tmp_path):
    from jarvis.monitoring.runner import scan_source
    from jarvis.monitoring.sources import MonitorSource
    from jarvis.monitoring.store import MonitorStore
    s = MonitorSource.create("A", "https://x.org/feed", "rss", rate_limit_s=60)
    out = scan_source(s, MonitorStore(tmp_path / "m.sqlite"), fetch=lambda _: {"ok":False,"reason":"source_unavailable","raw":"secret"})
    assert out == {"status":"source_failed", "source":"A", "reason":"source_unavailable"}


def test_store_releases_sqlite_handle_for_windows_cleanup(tmp_path):
    from jarvis.monitoring.store import MonitorStore
    db = tmp_path / "monitor.sqlite"
    store = MonitorStore(db)
    store.record_scan("s", [{"title":"A", "url":"https://x.org/a", "published":""}])
    store.latest("s")
    db.unlink()
    assert not db.exists()


def test_runner_only_accepts_monitor_source_not_cron_task(tmp_path):
    from jarvis.monitoring.runner import scan_source
    from jarvis.monitoring.store import MonitorStore
    import pytest
    with pytest.raises(TypeError):
        scan_source("arbitrary shell", MonitorStore(tmp_path / "m.sqlite"), fetch=lambda _: {})
