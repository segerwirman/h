"""delegate_task (§3.1.J) — sub-agent dengan context bersih + subset tool.

Sub-agent tidak bisa delegate lagi (loop.py meng-exclude tool ini saat
``is_subagent``). Hanya ringkasan hasil yang kembali — context utama lega.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.session import Session


class _Params(BaseModel):
    task: str = Field(description="Tugas lengkap dan mandiri untuk sub-agent "
                                  "(sertakan semua konteks yang dia butuhkan)")
    tools_allowed: list[str] = Field(
        default_factory=list,
        description="Batasi tool sub-agent (kosong = semua kecuali delegate)")
    max_iterations: int = Field(20, description="Batas iterasi sub-agent")


class DelegateTask(Tool):
    name = "delegate_task"
    description = ("Delegasikan sub-tugas besar/terpisah ke sub-agent dengan "
                   "context bersih. Kembalikan ringkasan hasilnya saja.")
    params_schema = _Params
    wants_context = True
    timeout_s = 900

    async def run(self, task: str, tools_allowed: list[str] | None = None,
                  max_iterations: int = 20, _session=None, _adapter=None,
                  _context=None, **_) -> ToolResult:
        if _session is not None and _session.is_subagent:
            return ToolResult.fail("sub-agent tidak boleh delegate lagi")

        from jarvis.agent import loop as agent_loop
        from jarvis.agent.adapters.base import NullAdapter

        parent_context = str(getattr(_session, "conversation_context", "") or "")
        if not parent_context and _session is not None:
            parent_context = (
                f"Tugas induk aktif: {str(getattr(_session, 'task', '') or '')[:1200]}"
            )
        if parent_context:
            task = (f"{task}\n\n[KONTEKS PARENT TERBATAS]\n"
                    f"{parent_context[:1200]}")
        sub_session = Session(task=task, adapter_name="subagent",
                              is_subagent=True)
        sub_context = _context.for_child() if _context is not None else None
        sub_session.execution_context = sub_context
        # Browser memakai satu page. Sub-agent mewarisi lease owner parent
        # supaya tidak deadlock terhadap parent dan lease tetap dilepas oleh
        # wrapper dispatch parent pada seluruh terminal path.
        parent_browser_owner = getattr(
            _session, "_browser_lease_owner", getattr(_session, "id", ""))
        if parent_browser_owner:
            setattr(sub_session, "_browser_lease_owner",
                    str(parent_browser_owner))
        sub_adapter = NullAdapter()
        sub_adapter.name = "subagent"
        result = await agent_loop.run(
            task, adapter=sub_adapter, session=sub_session,
            allowed_tools=tools_allowed or None,
            max_iterations=min(int(max_iterations or 20), 30),
            context=sub_context)

        summary = result.text or "\n".join(sub_adapter.outputs[-3:])
        if len(summary) > 6000:
            summary = summary[:6000] + " …[dipangkas]"
        if not result.ok:
            return ToolResult.fail(f"sub-agent gagal: {summary[:800]}")
        return ToolResult.success(f"Hasil sub-agent:\n{summary}",
                                  display=f"delegasi selesai "
                                          f"({result.iterations} iterasi)")
