"""File operations (§3.1.A) — sandbox ke workspace root + allowed_paths;
path di luar itu meminta konfirmasi user, tidak pernah diam-diam."""
from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.paths import allowed_paths, workspace_root
from jarvis.core import quiet

_MAX_READ = 200_000
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
              ".pytest_cache", "dist", "build", ".mypy_cache"}


def _inside_sandbox(path: Path) -> bool:
    try:
        target = path.resolve()
        roots = [workspace_root().resolve()]
        roots.extend(
            p.resolve() for p in allowed_paths() if p.exists()
        )
    except (OSError, TypeError, ValueError):
        return False
    return any(target == root or root in target.parents for root in roots)


def _resolve(raw: str) -> Path:
    p = Path(raw).expanduser()
    return p if p.is_absolute() else workspace_root() / p


def _looks_binary(data: bytes) -> bool:
    return b"\x00" in data[:4096]


class _ReadParams(BaseModel):
    path: str = Field(description="Path file (absolut atau relatif workspace)")
    offset: int = Field(0, description="Mulai dari baris ke- (0-based)")
    limit: int = Field(0, description="Jumlah baris maksimal (0 = semua, dibatasi ukuran)")


class FileRead(Tool):
    name = "file_read"
    description = ("Baca isi file teks. File biner ditolak dengan info "
                   "ukuran. Output dibatasi agar tidak membanjiri konteks.")
    params_schema = _ReadParams
    read_only = True
    timeout_s = 30

    def needs_confirmation(self, **kw) -> bool:
        return not _inside_sandbox(_resolve(kw.get("path", "")))

    async def run(self, path: str, offset: int = 0, limit: int = 0,
                  **_) -> ToolResult:
        p = _resolve(path)
        if not p.is_file():
            return ToolResult.fail(f"file tidak ditemukan: {p}")
        data = await asyncio.to_thread(p.read_bytes)
        if _looks_binary(data):
            return ToolResult.fail(
                f"file biner ({len(data):,} byte) — tidak dibaca sebagai teks")
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        total = len(lines)
        if offset or limit:
            lines = lines[offset:offset + limit if limit else None]
        out = "\n".join(lines)
        if len(out) > _MAX_READ:
            out = out[:_MAX_READ] + "\n… [terpotong]"
        return ToolResult.success(out, display=f"baca {p.name} ({total} baris)",
                                  path=str(p), total_lines=total)


class _WriteParams(BaseModel):
    path: str = Field(description="Path file tujuan")
    content: str = Field(description="Isi lengkap file")


class FileWrite(Tool):
    name = "file_write"
    description = ("Tulis/timpa file teks. File lama otomatis di-backup "
                   "menjadi .bak sebelum ditimpa.")
    params_schema = _WriteParams
    timeout_s = 30

    def needs_confirmation(self, **kw) -> bool:
        return not _inside_sandbox(_resolve(kw.get("path", "")))

    async def run(self, path: str, content: str, **_) -> ToolResult:
        p = _resolve(path)

        def _write():
            p.parent.mkdir(parents=True, exist_ok=True)
            backed_up = False
            if p.exists():
                shutil.copy2(p, p.with_suffix(p.suffix + ".bak"))
                backed_up = True
            p.write_text(content, encoding="utf-8")
            return backed_up

        backed_up = await asyncio.to_thread(_write)
        note = " (backup .bak dibuat)" if backed_up else ""
        return ToolResult.success(f"tersimpan: {p}{note}",
                                  display=f"tulis {p.name}", path=str(p))


class _PatchParams(BaseModel):
    path: str = Field(description="Path file")
    old_str: str = Field(description="Teks lama — harus unik di file")
    new_str: str = Field(description="Teks pengganti")


class FilePatch(Tool):
    name = "file_patch"
    description = ("Ganti tepat satu kemunculan old_str dengan new_str. "
                   "Error bila old_str tidak ada atau tidak unik.")
    params_schema = _PatchParams
    timeout_s = 30

    def needs_confirmation(self, **kw) -> bool:
        return not _inside_sandbox(_resolve(kw.get("path", "")))

    async def run(self, path: str, old_str: str, new_str: str,
                  **_) -> ToolResult:
        p = _resolve(path)
        if not p.is_file():
            return ToolResult.fail(f"file tidak ditemukan: {p}")
        text = await asyncio.to_thread(p.read_text, encoding="utf-8")
        n = text.count(old_str)
        if n == 0:
            return ToolResult.fail("old_str tidak ditemukan di file")
        if n > 1:
            return ToolResult.fail(f"old_str tidak unik ({n} kemunculan) — "
                                   "perluas konteksnya")
        shutil.copy2(p, p.with_suffix(p.suffix + ".bak"))
        await asyncio.to_thread(
            p.write_text, text.replace(old_str, new_str, 1), encoding="utf-8")
        return ToolResult.success(f"patch diterapkan pada {p}",
                                  display=f"patch {p.name}")


class _SearchParams(BaseModel):
    pattern: str = Field(description="Regex yang dicari di isi file")
    path: str = Field("", description="Folder awal (default: workspace)")
    glob: str = Field("", description="Filter nama file, mis. *.py")
    max_results: int = Field(60, description="Batas jumlah baris hasil")


class FileSearch(Tool):
    name = "file_search"
    description = "Cari regex di isi file (rekursif), hasil path:line:match."
    params_schema = _SearchParams
    read_only = True
    timeout_s = 60

    async def run(self, pattern: str, path: str = "", glob: str = "",
                  max_results: int = 60, **_) -> ToolResult:
        root = _resolve(path) if path else workspace_root()
        if not root.is_dir():
            return ToolResult.fail(f"folder tidak ditemukan: {root}")
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return ToolResult.fail(f"regex tidak valid: {e}")

        def _scan() -> list[str]:
            hits: list[str] = []
            for f in root.rglob(glob or "*"):
                if len(hits) >= max_results:
                    break
                if not f.is_file() or any(part in _SKIP_DIRS
                                          for part in f.parts):
                    continue
                if f.stat().st_size > 2_000_000:
                    continue
                try:
                    data = f.read_bytes()
                    if _looks_binary(data):
                        continue
                    for i, line in enumerate(
                            data.decode("utf-8", "replace").splitlines(), 1):
                        if rx.search(line):
                            hits.append(f"{f}:{i}: {line.strip()[:200]}")
                            if len(hits) >= max_results:
                                break
                except OSError as exc:
                    quiet.swallowed("agent.tools.file_ops.scan_skip_failed", exc)
                    continue
            return hits

        hits = await asyncio.to_thread(_scan)
        if not hits:
            return ToolResult.success("tidak ada yang cocok",
                                      display="0 hasil")
        return ToolResult.success("\n".join(hits),
                                  display=f"{len(hits)} hasil")


class _ListParams(BaseModel):
    path: str = Field("", description="Folder (default: workspace root)")
    depth: int = Field(2, description="Kedalaman maksimal")


class FileList(Tool):
    name = "file_list"
    description = "Daftar isi folder (tree ringkas, folder berat dilewati)."
    params_schema = _ListParams
    read_only = True
    timeout_s = 30

    async def run(self, path: str = "", depth: int = 2, **_) -> ToolResult:
        root = _resolve(path) if path else workspace_root()
        if not root.is_dir():
            return ToolResult.fail(f"folder tidak ditemukan: {root}")

        def _walk() -> list[str]:
            lines: list[str] = []

            def rec(d: Path, level: int):
                if level > depth or len(lines) > 400:
                    return
                try:
                    entries = sorted(
                        d.iterdir(),
                        key=lambda e: (e.is_file(), e.name.lower()))
                except OSError:
                    return
                for e in entries:
                    if e.name in _SKIP_DIRS or e.name.startswith("."):
                        continue
                    indent = "  " * level
                    if e.is_dir():
                        lines.append(f"{indent}{e.name}/")
                        rec(e, level + 1)
                    else:
                        try:
                            size = e.stat().st_size
                        except OSError:
                            size = 0
                        lines.append(f"{indent}{e.name}  [{size:,}]")
            rec(root, 0)
            return lines

        lines = await asyncio.to_thread(_walk)
        return ToolResult.success(f"{root}\n" + "\n".join(lines),
                                  display=f"{len(lines)} entri")
