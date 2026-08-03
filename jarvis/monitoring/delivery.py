"""Phase 17C: bounded delivery formatter; never sends automatically itself."""
from __future__ import annotations
from urllib.parse import parse_qsl, urlparse
_MODES=frozenset({'on_request','on_change','daily_digest','desktop_only','both'})
def delivery_allowed(mode): return str(mode) in _MODES
def _safe_item(item):
 if not isinstance(item,dict) or set(item)-{'title','url','published','hash'}: return False
 u=str(item.get('url','')); p=urlparse(u)
 if p.scheme!='https': return False
 for k,_ in parse_qsl(p.query):
  kf=k.casefold()
  if any(t in kf for t in ('token','key','secret','password','passwd')):
   return False
 return True
def render_digest(source,items,*,max_items=5,max_chars=1000):
 if not all(_safe_item(x) for x in (items or [])): return {'ok':False,'reason':'monitor_delivery_payload_rejected'}
 cap=max(1,min(int(max_items),10)); chars=max(80,min(int(max_chars),1000))
 lines=[f'Update {str(source)[:80]}: {len(items or [])} item tersimpan']
 for x in (items or [])[:cap]: lines.append(f"• {str(x.get('title') or '')[:200]} — {x['url']}")
 return {'ok':True,'content':'\n'.join(lines)[:chars]}
def plan_delivery(mode,*,scheduler_ready):
 if not delivery_allowed(mode): return {'dispatch':False,'reason':'monitor_delivery_mode_rejected'}
 if mode in {'on_change','daily_digest'} and not scheduler_ready: return {'dispatch':False,'reason':'monitor_scheduler_not_ready'}
 if mode=='on_request': return {'dispatch':True,'target':'requester'}
 if mode=='desktop_only': return {'dispatch':True,'target':'desktop'}
 return {'dispatch':True,'target':'configured'}
__all__=['delivery_allowed','render_digest','plan_delivery']
