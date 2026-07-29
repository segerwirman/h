"""Task planning (§3.1.F) — todo per-sesi. Aturan agent: tugas >3 langkah
wajib bikin todo dulu; maksimal satu ``in_progress``."""
from __future__ import annotations

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult

_STATUSES = ("pending", "in_progress", "completed", "blocked")


class _TodoItem(BaseModel):
    id: str = Field(description="ID unik singkat, mis. '1'")
    content: str = Field(description="Deskripsi langkah")
    status: str = Field("pending",
                        description="pending|in_progress|completed|blocked")
    priority: int = Field(0, description="0 = normal, makin besar makin penting")


class _WriteParams(BaseModel):
    items: list[_TodoItem] = Field(description="Seluruh daftar todo terbaru "
                                               "(menggantikan yang lama)")


def _render(items: list[dict]) -> str:
    icons = {"pending": "○", "in_progress": "◐", "completed": "●",
             "blocked": "✕"}
    return "\n".join(
        f"{icons.get(i.get('status', 'pending'), '○')} [{i.get('id')}] "
        f"{i.get('content')}" for i in items) or "(todo kosong)"


class TodoWriteTool(Tool):
    name = "todo_write"
    description = ("Tulis/perbarui todo list sesi ini (menggantikan daftar "
                   "lama). Wajib untuk tugas >3 langkah; update status SAAT "
                   "mengerjakan; maksimal satu in_progress.")
    params_schema = _WriteParams
    wants_context = True
    timeout_s = 10

    async def run(self, items: list | None = None, _session=None,
                  **_) -> ToolResult:
        norm: list[dict] = []
        for it in items or []:
            if isinstance(it, _TodoItem):
                it = it.model_dump()
            status = str(it.get("status", "pending"))
            norm.append({
                "id": str(it.get("id", len(norm) + 1)),
                "content": str(it.get("content", ""))[:300],
                "status": status if status in _STATUSES else "pending",
                "priority": int(it.get("priority", 0) or 0),
            })
        in_progress = [i for i in norm if i["status"] == "in_progress"]
        if len(in_progress) > 1:
            return ToolResult.fail("maksimal satu item in_progress")
        if _session is not None:
            _session.todos = norm
        return ToolResult.success(_render(norm),
                                  display=f"{len(norm)} todo")


class TodoReadTool(Tool):
    name = "todo_read"
    description = "Baca todo list sesi ini."
    read_only = True
    wants_context = True
    timeout_s = 10

    async def run(self, _session=None, **_) -> ToolResult:
        items = list(_session.todos) if _session is not None else []
        return ToolResult.success(_render(items),
                                  display=f"{len(items)} todo")
