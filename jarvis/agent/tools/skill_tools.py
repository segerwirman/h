"""Tool skills (§3.1.M) — list/view/manage skill markdown."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from jarvis.agent import skill_usage, skills
from jarvis.agent.base import Tool, ToolResult


class _ListParams(BaseModel):
    filter: str = Field("", description="Substring nama/deskripsi")


class SkillList(Tool):
    name = "skill_list"
    description = "Daftar skill tersedia (nama + deskripsi)."
    params_schema = _ListParams
    read_only = True
    timeout_s = 15

    async def run(self, filter: str = "", **_) -> ToolResult:
        metas = await asyncio.to_thread(skills.list_metadata, filter)
        if not metas:
            return ToolResult.success("belum ada skill", display="0 skill")
        text = "\n".join(f"- {m['name']}: {m['description']}" for m in metas)
        return ToolResult.success(text, display=f"{len(metas)} skill")


class _ViewParams(BaseModel):
    name: str = Field(description="Nama skill")


class SkillView(Tool):
    name = "skill_view"
    description = "Baca isi lengkap sebuah skill (instruksinya)."
    params_schema = _ViewParams
    read_only = True
    timeout_s = 15

    async def run(self, name: str, **_) -> ToolResult:
        body = await asyncio.to_thread(skills.view, name)
        if body is None:
            return ToolResult.fail(f"skill '{name}' tidak ditemukan")
        # telemetry setelah sukses — best-effort, tidak pernah raise (§4.1)
        await asyncio.to_thread(skill_usage.bump, name, "view")
        return ToolResult.success(body[:24_000], display=f"skill {name}")


class _ManageParams(BaseModel):
    action: str = Field(description="create | update | delete")
    name: str = Field(description="Nama skill (kebab-case)")
    content: str = Field("", description="Isi SKILL.md (untuk create/update); "
                                         "frontmatter otomatis bila kosong")


class SkillManage(Tool):
    name = "skill_manage"
    description = "Buat/perbarui/hapus skill."
    params_schema = _ManageParams
    timeout_s = 15

    def needs_confirmation(self, **kw) -> bool:
        return kw.get("action") == "delete"

    async def run(self, action: str, name: str, content: str = "",
                  **_) -> ToolResult:
        ok, msg = await asyncio.to_thread(skills.manage, action, name, content)
        if ok:
            # sidecar di-key dengan nama tersanitasi yang sama dengan folder
            safe = skills._safe_name(name)
            # provenance EKSPLISIT saat create — sumber badge "learned";
            # jangan pernah diinferensi dari path/tanggal (§4.2, audit §B.5)
            if action == "create":
                await asyncio.to_thread(skill_usage.mark_agent_created, safe)
            elif action == "update":
                await asyncio.to_thread(skill_usage.bump, safe, "patch")
            elif action == "delete":
                await asyncio.to_thread(skill_usage.forget, safe)
        return ToolResult.success(msg) if ok else ToolResult.fail(msg)
