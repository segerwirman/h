"""17B.1 monitor-only scheduler contract."""
from __future__ import annotations
import pytest

def src():
 from jarvis.monitoring.sources import MonitorSource
 return MonitorSource.create('Feed','https://example.org/feed','rss',rate_limit_s=60)

def test_create_monitor_job_accepts_only_validated_source():
 from jarvis.monitoring.scheduler import MonitorScheduler
 s=MonitorScheduler()
 job=s.create_monitor_job(src(),'*/5 * * * *')
 assert job['source']=='Feed' and set(job)=={'id','source','schedule','enabled','next_run'}
 with pytest.raises(TypeError): s.create_monitor_job('free text task','*/5 * * * *')

def test_bad_schedule_rejected_and_no_task_field():
 from jarvis.monitoring.scheduler import MonitorScheduler
 s=MonitorScheduler()
 with pytest.raises(ValueError): s.create_monitor_job(src(),'not cron')
 job=s.create_monitor_job(src(),'*/5 * * * *')
 assert 'task' not in job and not hasattr(s,'create') and not hasattr(s,'dispatch')

def test_tick_invokes_only_scan_source_for_due_job(monkeypatch):
 from jarvis.monitoring import scheduler
 calls=[]
 monkeypatch.setattr(scheduler,'scan_source',lambda source,store: calls.append(source.name) or {'status':'no_change','source':source.name,'items':[]})
 s=scheduler.MonitorScheduler(store=object(),now=lambda:100.0,next_run=lambda sched,base: 100.0)
 s.create_monitor_job(src(),'* * * * *')
 assert s.tick(now=100.0)
 assert calls==['Feed']

def test_scheduler_source_failure_safe_and_no_shell_browser_params():
 from jarvis.monitoring.scheduler import MonitorScheduler
 import inspect
 assert all(x not in str(inspect.signature(MonitorScheduler.create_monitor_job)) for x in ('task','shell','browser','login','typing'))
 s=MonitorScheduler(store=object(),scan=lambda source,store:{'status':'source_failed','source':source.name,'reason':'source_unavailable'},now=lambda:100.0,next_run=lambda sched,base:100.0)
 s.create_monitor_job(src(),'* * * * *')
 assert s.tick(now=100.0)[0]['reason']=='source_unavailable'


def test_tick_detailed_pairs_safe_public_job_metadata_with_scan_result():
 from jarvis.monitoring.scheduler import MonitorScheduler
 s=MonitorScheduler(
  store=object(),
  scan=lambda source,store:{'status':'new_items','source':source.name,'items':[]},
  now=lambda:100.0,
  next_run=lambda sched,base:100.0,
 )
 s.create_monitor_job(src(),'* * * * *')
 detail=s.tick_detailed(now=100.0)
 assert detail[0]['result']['status']=='new_items'
 assert set(detail[0]['job'])=={'id','source','schedule','enabled','next_run'}
 assert 'source_obj' not in detail[0]['job']
