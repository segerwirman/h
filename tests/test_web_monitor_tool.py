"""Phase 17A monitor tool validates source before fetch."""
from __future__ import annotations
import asyncio

def test_monitor_is_read_only_and_rejects_login_before_fetch(monkeypatch):
    from jarvis.agent.tools import web_monitor
    called = []
    monkeypatch.setattr(web_monitor, "fetch_source", lambda *a, **k: called.append(1) or {"ok": True, "items": []})
    tool = web_monitor.WebMonitor()
    assert tool.read_only is True
    result = asyncio.run(tool.run("Bad", "https://example.org/login", "rss"))
    assert result.ok is False
    assert called == []

def test_monitor_returns_bounded_fetch_result(monkeypatch):
    from jarvis.agent.tools import web_monitor
    monkeypatch.setattr(web_monitor, "fetch_source", lambda source, max_items: {"ok": True, "source": source.name, "mode": source.mode, "items": [{"title":"A","url":"https://x/a","published":""}]})
    result = asyncio.run(web_monitor.WebMonitor().run("News", "https://example.org/feed", "rss", max_items=1))
    assert result.ok is True
    assert result.content["items"][0]["title"] == "A"
    assert "tanpa login/browser" in web_monitor.WebMonitor.description.lower()
    assert not {"browser", "login", "cookies"} & set(web_monitor.WebMonitor().json_schema()["properties"])
