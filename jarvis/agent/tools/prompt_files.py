"""Native prompt library backed by a dedicated project folder."""
from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from pathlib import Path

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.core import config


def prompt_dir() -> Path:
    path = config.resolve_path(
        str(config.get("agent.prompt_dir", "prompts") or "prompts")
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def _slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore"
    ).decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", ascii_value).strip("-_").lower()
    return slug[:80] or f"prompt-{time.strftime('%Y%m%d-%H%M%S')}"


def _path(name: str) -> Path:
    return prompt_dir() / f"{_slug(name)}.md"


class _ListParams(BaseModel):
    query: str = Field("", description="Filter nama prompt (opsional)")


class PromptList(Tool):
    name = "prompt_list"
    description = "Daftar prompt Markdown yang tersimpan di folder prompt."
    params_schema = _ListParams
    read_only = True
    timeout_s = 15

    async def run(self, query: str = "", **_) -> ToolResult:
        needle = str(query or "").strip().casefold()

        def _list() -> list[dict]:
            items = []
            for path in sorted(prompt_dir().glob("*.md")):
                if needle and needle not in path.stem.casefold():
                    continue
                stat = path.stat()
                items.append({
                    "name": path.stem,
                    "path": str(path),
                    "bytes": stat.st_size,
                    "modified": stat.st_mtime,
                })
            return items[:200]

        items = await asyncio.to_thread(_list)
        return ToolResult.success(items, display=f"{len(items)} prompt")


class _ReadParams(BaseModel):
    name: str = Field(description="Nama prompt, tanpa path")


class PromptRead(Tool):
    name = "prompt_read"
    description = "Baca prompt berdasarkan nama dari folder prompt Jarvis."
    params_schema = _ReadParams
    read_only = True
    timeout_s = 15

    async def run(self, name: str, **_) -> ToolResult:
        path = _path(name)
        if not path.is_file():
            return ToolResult.fail(f"prompt tidak ditemukan: {path.stem}")
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        return ToolResult.success(
            text[:200_000], display=f"baca prompt {path.stem}", path=str(path)
        )


class _SaveParams(BaseModel):
    name: str = Field(description="Nama file prompt; akan dibuat aman sebagai .md")
    content: str = Field(
        min_length=1,
        max_length=200_000,
        description="Prompt lengkap yang sudah dibuat oleh model",
    )
    overwrite: bool = Field(
        False, description="Timpa prompt bernama sama setelah konfirmasi"
    )


class PromptSave(Tool):
    name = "prompt_save"
    description = (
        "Simpan prompt yang sudah kamu susun langsung sebagai Markdown di "
        "folder prompt Jarvis. Nama selalu disanitasi; path traversal tidak "
        "mungkin. Gunakan setelah membuat prompt sesuai permintaan user."
    )
    params_schema = _SaveParams
    timeout_s = 20

    def needs_confirmation(self, **kwargs) -> bool:
        return bool(kwargs.get("overwrite")) and _path(
            str(kwargs.get("name", ""))
        ).exists()

    def confirmation_text(self, **kwargs) -> str:
        return f"Timpa prompt '{_slug(str(kwargs.get('name', 'prompt')))}.md'?"

    async def run(self, name: str, content: str, overwrite: bool = False,
                  **_) -> ToolResult:
        path = _path(name)
        if path.exists() and not overwrite:
            return ToolResult.fail(
                "prompt sudah ada; pilih nama lain atau set overwrite=true"
            )

        def _save() -> None:
            tmp = path.with_suffix(".md.tmp")
            tmp.write_text(str(content).rstrip() + "\n", encoding="utf-8")
            tmp.replace(path)

        await asyncio.to_thread(_save)
        return ToolResult.success(
            {"name": path.stem, "path": str(path), "bytes": path.stat().st_size},
            display=f"prompt tersimpan: {path.name}",
            path=str(path),
        )


__all__ = ["PromptList", "PromptRead", "PromptSave", "prompt_dir"]
