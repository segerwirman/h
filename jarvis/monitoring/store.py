"""Phase 17B: bounded SQLite monitor metadata store."""
from __future__ import annotations
import hashlib
import sqlite3
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
_TRACK={"utm_source","utm_medium","utm_campaign","utm_term","utm_content","fbclid","gclid"}
def canonical_url(value):
 p=urlparse(str(value)); q=[(k,v) for k,v in parse_qsl(p.query,keep_blank_values=True) if k.casefold() not in _TRACK]
 return urlunparse((p.scheme.casefold(),p.netloc.casefold(),p.path.rstrip('/') or '/', '',urlencode(sorted(q)),''))
def _hash(url,title,published): return hashlib.sha256((url+'\x1f'+title+'\x1f'+published).encode()).hexdigest()
class MonitorStore:
 def __init__(self,path,max_items_per_source=100):
  self.path=Path(path); self.max=max(1,min(int(max_items_per_source),500)); self.path.parent.mkdir(parents=True,exist_ok=True); self._init()
 def _conn(self): return sqlite3.connect(self.path)
 def _init(self):
  c=self._conn()
  try: c.execute('CREATE TABLE IF NOT EXISTS monitor_items (source TEXT, url TEXT, title TEXT, published TEXT, hash TEXT PRIMARY KEY, seen REAL)'); c.commit()
  finally: c.close()
 def record_scan(self,source,items):
  c=self._conn(); new=[]
  try:
   for item in items or []:
    url=canonical_url(item.get('url','')); title=str(item.get('title',''))[:200]; published=str(item.get('published',''))[:80]
    if not url or not title: continue
    h=_hash(url,title,published)
    if c.execute('SELECT 1 FROM monitor_items WHERE hash=?',(h,)).fetchone(): continue
    c.execute('INSERT INTO monitor_items VALUES (?,?,?,?,?,?)',(str(source),url,title,published,h,time.time())); new.append({'title':title,'url':url,'published':published,'hash':h})
   c.execute('DELETE FROM monitor_items WHERE source=? AND hash NOT IN (SELECT hash FROM monitor_items WHERE source=? ORDER BY seen DESC LIMIT ?)',(str(source),str(source),self.max)); c.commit()
  finally: c.close()
  return {'status':'new_items' if new else 'no_change','items':new}
 def latest(self,source):
  c=self._conn()
  try: return [{'title':r[0],'url':r[1],'published':r[2],'hash':r[3]} for r in c.execute('SELECT title,url,published,hash FROM monitor_items WHERE source=? ORDER BY seen DESC LIMIT ?',(str(source),self.max))]
  finally: c.close()
__all__=['MonitorStore','canonical_url']
