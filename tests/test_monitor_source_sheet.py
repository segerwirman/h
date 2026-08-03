"""17F desktop-local source management sheet."""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
_APP=None
def _app():
 global _APP
 _APP=QApplication.instance() or QApplication([])
 return _APP

def test_sheet_adds_valid_source_and_shows_metadata_only(tmp_path):
 _app()
 from jarvis.monitoring.source_registry_store import PersistentSourceRegistry
 from jarvis.ui.monitor_source_sheet import MonitorSourceSheet
 sheet=MonitorSourceSheet(PersistentSourceRegistry(tmp_path/'sources.sqlite'))
 assert sheet.add_source('News','https://example.org/feed','rss',60) is True
 text=sheet.summary_text()
 assert 'News' in text and 'https://example.org/feed' in text
 assert 'token' not in text.lower() and 'body' not in text.lower()

def test_sheet_rejects_invalid_source_and_never_creates_browser_or_fetch(tmp_path):
 _app()
 from jarvis.monitoring.source_registry_store import PersistentSourceRegistry
 from jarvis.ui.monitor_source_sheet import MonitorSourceSheet
 sheet=MonitorSourceSheet(PersistentSourceRegistry(tmp_path/'sources.sqlite'))
 assert sheet.add_source('Bad','https://example.org/login','rss',60) is False
 assert sheet.summary_text()=='Source tidak valid.'
 assert sheet.registry.list()==[]
 source=open(sheet.__class__.__module__.replace('.','/')+'.py',encoding='utf-8').read()
 for forbidden in ('fetch_source','MonitorScheduler','webbrowser','send_from_anywhere','credential','password'):
  assert forbidden not in source

def test_sheet_select_and_clear_selection_are_local_metadata_operations(tmp_path):
 _app()
 from jarvis.monitoring.source_registry_store import PersistentSourceRegistry
 from jarvis.ui.monitor_source_sheet import MonitorSourceSheet
 registry=PersistentSourceRegistry(tmp_path/'sources.sqlite'); sheet=MonitorSourceSheet(registry)
 sheet.add_source('News','https://example.org/feed','rss',60)
 source_id=registry.list()[0].id
 assert sheet.select_source(source_id) is True
 assert registry.selected().id==source_id
 assert sheet.clear_selection() is True and registry.selected() is None

def test_sheet_starts_hidden_and_has_no_remote_approval_surface(tmp_path):
 _app()
 from PyQt6.QtWidgets import QWidget
 from jarvis.monitoring.source_registry_store import PersistentSourceRegistry
 from jarvis.ui.monitor_source_sheet import MonitorSourceSheet
 parent=QWidget(); sheet=MonitorSourceSheet(PersistentSourceRegistry(tmp_path/'sources.sqlite'), parent)
 parent.show(); _app().processEvents()
 assert sheet.isVisible() is False
 assert not hasattr(sheet,'approve_remote') and not hasattr(sheet,'receive_remote')
 parent.close()


def test_sheet_registers_selected_source_without_fetching_or_running_scheduler(tmp_path):
 _app()
 from jarvis.monitoring.source_registry_store import PersistentSourceRegistry
 from jarvis.ui.monitor_source_sheet import MonitorSourceSheet
 registry=PersistentSourceRegistry(tmp_path/'sources.sqlite'); sheet=MonitorSourceSheet(registry)
 sheet.add_source('News','https://example.org/feed','rss',60)
 sheet.select_source(registry.list()[0].id)
 job=sheet.register_selected_job('*/5 * * * *','desktop_only')
 assert job is not None and job.source=='News' and job.delivery_mode=='desktop_only'
 assert 'News' in sheet.summary_text()
