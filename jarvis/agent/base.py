"""Kontrak tool agent (jarvis.md §3) — semua tool mengikuti bentuk yang sama.

Aturan:
- semua ``async`` dan ber-timeout;
- tidak pernah raise ke agent loop — kegagalan menjadi ``ok=False``;
- tool berbahaya menyatakan ``requires_confirmation`` (statis) atau
  meng-override ``needs_confirmation()`` untuk keputusan per-panggilan;
- eksekusi di-log ke ``data/logs/tools.jsonl`` oleh registry.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ToolResult(BaseModel):
    ok: bool
    content: Any = None            # hasil untuk LLM (str/dict/list)
    display: str | None = None     # versi ringkas untuk UI/Telegram
    error: str | None = None
    meta: dict = {}

    @classmethod
    def success(cls, content: Any, display: str | None = None, **meta) -> "ToolResult":
        return cls(ok=True, content=content, display=display, meta=meta)

    @classmethod
    def fail(cls, error: str, **meta) -> "ToolResult":
        return cls(ok=False, content=f"ERROR: {error}", error=error, meta=meta)

    def for_llm(self, max_chars: int = 24_000) -> str:
        """Serialisasi hasil untuk pesan tool — dibatasi agar tidak menelan
        context window."""
        import json
        c = self.content
        if not isinstance(c, str):
            try:
                c = json.dumps(c, ensure_ascii=False, default=str)
            except Exception:
                c = str(c)
        if len(c) > max_chars:
            c = c[:max_chars] + f"\n… [terpotong, total {len(c)} karakter]"
        return c


class Tool(ABC):
    """Satu kemampuan agent. Subclass di ``jarvis/agent/tools/`` ditemukan
    otomatis oleh registry."""

    name: str = ""
    description: str = ""
    params_schema: type[BaseModel] | None = None
    requires_confirmation: bool = False    # tool berbahaya → True
    read_only: bool = False                # True → boleh dieksekusi paralel
    timeout_s: int = 60

    @abstractmethod
    async def run(self, **kwargs) -> ToolResult: ...

    def is_available(self) -> bool:
        """Gate per-tool untuk capability/scope yang lebih sempit dari modul."""
        return True

    # per-panggilan; default mengikuti flag statis
    def needs_confirmation(self, **kwargs) -> bool:
        return self.requires_confirmation

    def confirmation_text(self, **kwargs) -> str:
        import json
        args = json.dumps(kwargs, ensure_ascii=False, default=str)
        if len(args) > 300:
            args = args[:300] + "…"
        return f"Izinkan menjalankan {self.name} dengan argumen {args}?"

    # ── schema ────────────────────────────────────────────────────────────

    def json_schema(self) -> dict:
        """JSON Schema parameter (format OpenAI); pydantic → schema bersih."""
        if self.params_schema is None:
            return {"type": "object", "properties": {}}
        schema = self.params_schema.model_json_schema()
        _strip_titles(schema)
        return schema


def _strip_titles(node: Any) -> None:
    """Buang ``title`` yang disisipkan pydantic — noise untuk LLM."""
    if isinstance(node, dict):
        node.pop("title", None)
        for v in node.values():
            _strip_titles(v)
    elif isinstance(node, list):
        for v in node:
            _strip_titles(v)
