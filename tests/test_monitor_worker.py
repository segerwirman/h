"""17H monitor-only lifecycle: load persisted jobs, tick, deliver, stop."""
from __future__ import annotations


def test_worker_installs_jobs_ticks_and_routes_existing_delivery():
    from jarvis.monitoring.worker import MonitorWorker
    events=[]
    class Jobs:
        def list(self):
            return [type('J',(),{'enabled':True,'source_id':'s','schedule':'* * * * *','delivery_mode':'desktop_only','id':'p'})()]
        class sources:
            @staticmethod
            def get(_):
                return type('S',(),{'monitor_source':lambda self:'SOURCE'})()
    class Scheduler:
        def __init__(self): self.created=[]
        def create_monitor_job(self,source,schedule): self.created.append((source,schedule)); return {'id':'r'}
        def tick_detailed(self): return [{'job':{'id':'r'},'result':{'status':'new_items','source':'News','items':[]}}]
    class Delivery:
        def bind_job(self,job,mode): events.append(('bind',job['id'],mode))
        def run_due(self): events.append(('run',)); return []
    worker=MonitorWorker(jobs=Jobs(), scheduler=Scheduler(), delivery=Delivery())
    assert worker.start() is True
    assert worker.tick_once() == []
    assert events == [('bind','r','desktop_only'),('run',)]
    worker.stop()


def test_worker_duplicate_start_is_rejected_and_stop_is_idempotent():
    from jarvis.monitoring.worker import MonitorWorker
    worker=MonitorWorker(jobs=type('J',(),{'list':lambda self:[]})(), scheduler=object(), delivery=object())
    assert worker.start() is True
    assert worker.start() is False
    worker.stop(); worker.stop()


def test_worker_skips_missing_source_and_catches_tick_failure():
    from jarvis.monitoring.worker import MonitorWorker
    class Jobs:
        def list(self): return [type('J',(),{'enabled':True,'source_id':'missing','schedule':'* * * * *','delivery_mode':'desktop_only','id':'p'})()]
        class sources:
            @staticmethod
            def get(_): return None
    worker=MonitorWorker(jobs=Jobs(), scheduler=object(), delivery=object())
    assert worker.start() is True
    assert worker.tick_once() == []
    worker.stop()


def test_worker_has_no_generic_cron_or_browser_shell_authority():
    from jarvis.monitoring import worker
    source=open(worker.__file__,encoding='utf-8').read()
    for forbidden in ('agent.cron','dispatch.run_sync','subprocess','webbrowser','send_from_anywhere','fetch_source','desktop_safe'):
        assert forbidden not in source
