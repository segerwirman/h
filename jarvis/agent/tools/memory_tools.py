"""Tool memori (§3.1.I) — antarmuka agent ke memory_store."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from jarvis.agent import memory_store
from jarvis.agent.base import Tool, ToolResult

_SENSITIVE = ("api_key", "access_token", "refresh_token", "password", "secret", "sk-")


def _safe_for_memory(content: object) -> bool:
    text = str(content or "").casefold()
    return bool(text) and len(text) <= 2_000 and not any(token in text for token in _SENSITIVE)


class _WriteParams(BaseModel):
    content: str = Field(description="Fakta/prosedur/pelajaran yang diingat")
    type: str = Field("semantic",
                      description="episodic|semantic|procedural|reflective")
    tags: list[str] = Field(default_factory=list)
    importance: float = Field(0.5, description="0..1")


class MemoryWrite(Tool):
    name = "memory_write"
    description = ("Simpan informasi bernilai jangka panjang ke memori "
                   "persisten. semantic=fakta, procedural=cara melakukan, "
                   "reflective=pelajaran dari kegagalan.")
    params_schema = _WriteParams
    wants_context = True
    timeout_s = 30

    async def run(self, content: str, type: str = "semantic",
                  tags: list[str] | None = None, importance: float = 0.5,
                  _session=None, _context=None, **_) -> ToolResult:
        from jarvis.agent.memory_access import resolve
        try:
            memory_scope = resolve(_context)
        except PermissionError:
            return ToolResult.fail("policy menolak scope memori")
        if not _safe_for_memory(content):
            return ToolResult.fail("konten sensitif atau terlalu panjang tidak disimpan")
        mid = await asyncio.to_thread(
            memory_store.write, type, content, importance, tags or [],
            getattr(_session, "id", ""), memory_scope.scope, memory_scope.owner)
        return ToolResult.success(f"tersimpan (id={mid})",
                                  display=f"memori {type} tersimpan")


class _SearchParams(BaseModel):
    query: str = Field(description="Apa yang dicari")
    type: str = Field("", description="Filter jenis (kosong = semua)")
    limit: int = Field(8)


class MemorySearch(Tool):
    name = "memory_search"
    description = "Cari memori persisten (hybrid semantic+keyword+recency)."
    params_schema = _SearchParams
    read_only = True
    timeout_s = 30

    async def run(self, query: str, type: str = "", limit: int = 8,
                  _context=None, **_) -> ToolResult:
        from jarvis.agent.memory_access import resolve
        try:
            memory_scope = resolve(_context)
        except PermissionError:
            return ToolResult.fail("policy menolak scope memori")
        rows = await asyncio.to_thread(
            memory_store.search, query, type or None, min(int(limit), 20),
            scope=memory_scope.scope, owner=memory_scope.owner)
        if not rows:
            return ToolResult.success("tidak ada memori relevan",
                                      display="0 memori")
        text = "\n".join(f"[{r['id']}] ({r['type']}, imp={r['importance']}) "
                         f"{r['content']}" for r in rows)
        return ToolResult.success(text, display=f"{len(rows)} memori")


class _UpdateParams(BaseModel):
    id: str = Field(description="ID memori")
    content: str = Field(description="Isi baru")


class MemoryUpdate(Tool):
    name = "memory_update"
    description = "Perbarui isi sebuah memori (id dari memory_search)."
    params_schema = _UpdateParams
    timeout_s = 30

    async def run(self, id: str, content: str, _context=None, **_) -> ToolResult:
        from jarvis.agent.memory_access import resolve
        try:
            memory_scope = resolve(_context)
        except PermissionError:
            return ToolResult.fail("policy menolak scope memori")
        ok = await asyncio.to_thread(memory_store.update, id, content,
                                     memory_scope.scope, memory_scope.owner)
        return (ToolResult.success(f"memori {id} diperbarui") if ok
                else ToolResult.fail(f"memori {id} tidak ditemukan"))


class _ForgetParams(BaseModel):
    id: str = Field(description="ID memori yang dihapus")


class MemoryForget(Tool):
    name = "memory_forget"
    description = "Hapus sebuah memori secara permanen."
    params_schema = _ForgetParams
    timeout_s = 30

    async def run(self, id: str, _context=None, **_) -> ToolResult:
        from jarvis.agent.memory_access import resolve
        try:
            memory_scope = resolve(_context)
        except PermissionError:
            return ToolResult.fail("policy menolak scope memori")
        ok = await asyncio.to_thread(memory_store.forget, id,
                                     memory_scope.scope, memory_scope.owner)
        return (ToolResult.success(f"memori {id} dihapus") if ok
                else ToolResult.fail(f"memori {id} tidak ditemukan"))
