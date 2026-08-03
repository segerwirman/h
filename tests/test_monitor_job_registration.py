"""17G: local registration of selected sources to monitor-only scheduler."""
from __future__ import annotations
import pytest

def _registry(tmp_path):
 from jarvis.monitoring.source_registry_store import PersistentSourceRegistry
 r=PersistentSourceRegistry(tmp_path/'sources.sqlite')
 s=r.add('News','https://example.org/feed','rss',rate_limit_s=60); r.select(s.id)
 return r,s

def test_local_registration_requires_selected_source_and_valid_schedule(tmp_path):
 from jarvis.monitoring.monitor_job_store import MonitorJobRegistry
 r,_=_registry(tmp_path); jobs=MonitorJobRegistry(tmp_path/'jobs.sqlite',r)
 job=jobs.register_selected('*/5 * * * *','desktop_only')
 assert set(job.public_dict())=={'id','source_id','source','schedule','delivery_mode','enabled','last_status','last_status_at'}
 with pytest.raises(ValueError): jobs.register_selected('not cron','desktop_only')
 r.clear_selection()
 with pytest.raises(ValueError): jobs.register_selected('*/5 * * * *','desktop_only')

def test_job_reopen_and_scheduler_handoff_uses_only_validated_source(tmp_path):
 from jarvis.monitoring.monitor_job_store import MonitorJobRegistry
 r,s=_registry(tmp_path); path=tmp_path/'jobs.sqlite'
 job=MonitorJobRegistry(path,r).register_selected('*/5 * * * *','on_change')
 calls=[]
 class Scheduler:
  def create_monitor_job(self, source, schedule):
   calls.append((source,schedule)); return {'id':'runtime-job'}
 reopened=MonitorJobRegistry(path,r)
 assert reopened.install_into(Scheduler())==[{'persisted_id':job.id,'runtime_job_id':'runtime-job','delivery_mode':'on_change'}]
 assert calls[0][0].url=='https://example.org/feed' and calls[0][1]=='*/5 * * * *'

def test_job_registry_rejects_generic_task_remote_and_unsafe_delivery(tmp_path):
 from jarvis.monitoring.monitor_job_store import MonitorJobRegistry
 r,_=_registry(tmp_path); jobs=MonitorJobRegistry(tmp_path/'jobs.sqlite',r)
 source=open(jobs.__class__.__module__.replace('.','/')+'.py',encoding='utf-8').read()
 for forbidden in ('dispatch.run_sync','agent.cron','subprocess','webbrowser','send_from_anywhere','task TEXT'):
  assert forbidden not in source
 with pytest.raises(ValueError): jobs.register_selected('*/5 * * * *','shell')
 assert not hasattr(jobs,'register_remote')
