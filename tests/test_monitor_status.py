"""17I metadata-only monitor observability."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication

_APP = None
def _app():
 global _APP
 _APP = QApplication.instance() or QApplication([])
 return _APP


def test_worker_status_is_metadata_only_after_tick():
 from jarvis.monitoring.worker import MonitorWorker
 class Jobs:
  def list(self): return []
 worker=MonitorWorker(jobs=Jobs(),scheduler=object(),delivery=type('D',(),{'run_due':lambda self:[{'delivered':True,'target':'desktop'}]})())
 worker.start(); worker.tick_once()
 status=worker.status()
 assert set(status)=={'running','last_tick_at','last_delivery_count','last_status'}
 assert status['last_delivery_count']==1
 assert 'payload' not in str(status) and 'exception' not in str(status)
 worker.stop()


def test_sheet_status_summary_has_job_metadata_no_raw_content(tmp_path):
 _app()
 from jarvis.monitoring.source_registry_store import PersistentSourceRegistry
 from jarvis.monitoring.monitor_job_store import MonitorJobRegistry
 from jarvis.ui.monitor_source_sheet import MonitorSourceSheet
 registry=PersistentSourceRegistry(tmp_path/'sources.sqlite'); src=registry.add('News','https://example.org/feed','rss',rate_limit_s=60); registry.select(src.id)
 jobs=MonitorJobRegistry(tmp_path/'jobs.sqlite',registry); jobs.register_selected('*/5 * * * *','desktop_only')
 sheet=MonitorSourceSheet(registry); sheet.jobs=jobs; sheet.refresh()
 text=sheet.summary_text()
 assert 'Job:' in text and '*/5 * * * *' in text and 'desktop_only' in text
 for forbidden in ('Traceback','cookie','header','body','token','https response'):
  assert forbidden.lower() not in text.lower()
