"""session_search (§3.1.H) — cari percakapan/sesi agent lampau."""
from __future__ import annotations

import asyncio
import datetime

from pydantic import BaseModel, Field

from jarvis.agent import session as session_mod
from jarvis.agent.base import Tool, ToolResult


class _Params(BaseModel):
    query: str = Field(description="Kata kunci")
    limit: int = Field(8)


class SessionSearch(Tool):
    name = "session_search"
    description = "Cari isi percakapan/sesi agent sebelumnya (full-text)."
    params_schema = _Params
    read_only = True
    timeout_s = 30

    async def run(self, query: str, limit: int = 8, **_) -> ToolResult:
        # Argumen datang dari MODEL dan tidak divalidasi registry, jadi
        # bentuknya diperiksa di sini — bukan diserahkan ke SQL.
        text = query if isinstance(query, str) else ""
        if not text.strip():
            return ToolResult.fail("query kosong")
        try:
            rows = await asyncio.to_thread(
                session_mod.search, text, min(int(limit or 8), 20))
        except Exception as exc:                             # noqa: BLE001
            # S-41 — pencarian yang gagal dilaporkan GAGAL. Mengembalikan
            # "0 hasil" di sini berarti berbohong tentang sesuatu yang tidak
            # pernah dikerjakan.
            return ToolResult.fail(f"pencarian sesi gagal: {str(exc)[:160]}")
        if not rows:
            return ToolResult.success("tidak ada sesi yang cocok",
                                      display="0 hasil")
        lines = []
        for r in rows:
            ts = datetime.datetime.fromtimestamp(
                r.get("ts", 0)).strftime("%Y-%m-%d %H:%M")
            lines.append(f"[{r.get('session_id')}] {ts} "
                         f"{r.get('role')}: {r.get('snip')}")
        return ToolResult.success("\n".join(lines),
                                  display=f"{len(rows)} hasil")
