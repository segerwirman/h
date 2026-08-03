"""17B.1 monitor-only scheduler; never imports agent.cron or dispatch."""
from __future__ import annotations
import time, uuid
from jarvis.monitoring.sources import MonitorSource
from jarvis.monitoring.runner import scan_source

def _next(schedule, base):
 try:
  from croniter import croniter
  return float(croniter(schedule,base).get_next(float))
 except Exception as e: raise ValueError('monitor schedule invalid') from e
class MonitorScheduler:
 def __init__(self,*,store=None,scan=None,now=time.time,next_run=_next):
  self._store=store; self._scan=scan; self._now=now; self._next=next_run; self._jobs={}
 def _scan_source(self, source):
  return (self._scan or scan_source)(source, self._store)
 def _public_job(self, job):
  return {k:v for k,v in job.items() if k!='source_obj'}
 def create_monitor_job(self,source,schedule):
  if not isinstance(source,MonitorSource): raise TypeError('validated MonitorSource required')
  base=float(self._now()); nxt=self._next(str(schedule),base)
  jid=uuid.uuid4().hex[:12]; self._jobs[jid]={'source_obj':source,'id':jid,'source':source.name,'schedule':str(schedule),'enabled':True,'next_run':nxt}
  return self._public_job(self._jobs[jid])
 def tick_detailed(self,*,now=None):
  current=float(self._now() if now is None else now); out=[]
  for job in self._jobs.values():
   if not job['enabled'] or job['next_run']>current: continue
   result=self._scan_source(job['source_obj'])
   job['next_run']=self._next(job['schedule'],current)
   out.append({'job':self._public_job(job),'result':result})
  return out
 def tick(self,*,now=None):
  return [entry['result'] for entry in self.tick_detailed(now=now)]
__all__=['MonitorScheduler']
