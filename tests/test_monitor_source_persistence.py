"""17E persistent validated source registry and selected-source briefing seam."""
from __future__ import annotations
import pytest

def test_valid_source_and_selection_survive_reopen(tmp_path):
 from jarvis.monitoring.source_registry_store import PersistentSourceRegistry
 path=tmp_path/'sources.sqlite'
 reg=PersistentSourceRegistry(path)
 src=reg.add('News','https://example.org/feed','rss',rate_limit_s=60)
 reg.select(src.id)
 reopened=PersistentSourceRegistry(path)
 assert reopened.selected().id == src.id
 assert reopened.list()[0].url == 'https://example.org/feed'

def test_selection_requires_existing_source_and_invalid_url_never_persists(tmp_path):
 from jarvis.monitoring.source_registry_store import PersistentSourceRegistry
 reg=PersistentSourceRegistry(tmp_path/'sources.sqlite')
 with pytest.raises(ValueError): reg.select('missing')
 with pytest.raises(ValueError): reg.add('Bad','https://example.org/login','rss',rate_limit_s=60)
 assert reg.list()==[] and reg.selected() is None

def test_persisted_view_has_metadata_only_no_credentials_or_store_content(tmp_path):
 from jarvis.monitoring.source_registry_store import PersistentSourceRegistry
 reg=PersistentSourceRegistry(tmp_path/'sources.sqlite')
 src=reg.add('Feed','https://example.org/feed','rss',rate_limit_s=60)
 row=reg.public_view()[0]
 assert set(row)=={'id','name','url','mode','rate_limit_s'}
 assert 'token' not in str(row) and src.id


def test_manual_db_tamper_cannot_bypass_source_policy(tmp_path):
 import sqlite3
 from jarvis.monitoring.source_registry_store import PersistentSourceRegistry
 path=tmp_path/'sources.sqlite'
 reg=PersistentSourceRegistry(path)
 src=reg.add('Feed','https://example.org/feed','rss',rate_limit_s=60)
 conn=sqlite3.connect(path)
 conn.execute("UPDATE sources SET url=? WHERE id=?", ('https://example.org/login',src.id))
 conn.commit(); conn.close()
 with pytest.raises(ValueError): PersistentSourceRegistry(path).list()

def test_clear_selection_preserves_sources(tmp_path):
 from jarvis.monitoring.source_registry_store import PersistentSourceRegistry
 reg=PersistentSourceRegistry(tmp_path/'sources.sqlite')
 src=reg.add('Feed','https://example.org/feed','rss',rate_limit_s=60)
 reg.select(src.id)
 reg.clear_selection()
 assert reg.selected() is None and [item.id for item in reg.list()] == [src.id]


def test_briefing_reads_selected_latest_without_fetch_or_scheduler(monkeypatch):
 from jarvis.agent.tools import briefing_tool
 class Source: name='News'
 class Registry:
  def selected(self): return Source()
 class Store:
  def latest(self,name): assert name=='News'; return [{'title':'Safe Item','url':'https://e/a','published':'','hash':'h'}]
 monkeypatch.setattr(briefing_tool,'_persistent_sources',lambda:Registry())
 monkeypatch.setattr(briefing_tool,'_monitor_store',lambda:Store())
 assert briefing_tool._monitor_latest()=={'source':'News','items':[{'title':'Safe Item','url':'https://e/a','published':'','hash':'h'}]}
 source=open(briefing_tool.__file__,encoding='utf-8').read()
 assert 'fetch_source' not in source and 'MonitorScheduler' not in source

def test_briefing_no_selected_source_is_safe_empty(monkeypatch):
 from jarvis.agent.tools import briefing_tool
 monkeypatch.setattr(briefing_tool,'_persistent_sources',lambda:type('R',(),{'selected':lambda self:None})())
 assert briefing_tool._monitor_latest()=={'source':'','items':[]}
