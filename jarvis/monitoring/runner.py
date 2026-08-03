"""Phase 17B: safe monitor scan runner; accepts only a validated MonitorSource."""
from __future__ import annotations
from jarvis.monitoring.sources import MonitorSource
from jarvis.monitoring.fetch import fetch_source

def scan_source(source, store, *, fetch=fetch_source):
 if not isinstance(source,MonitorSource): raise TypeError('monitor source required')
 result=fetch(source)
 if not result.get('ok'):
  return {'status':'source_failed','source':source.name,'reason':str(result.get('reason','source_unavailable'))}
 recorded=store.record_scan(source.name,result.get('items') or [])
 return {'status':recorded['status'],'source':source.name,'items':recorded['items']}
__all__=['scan_source']
