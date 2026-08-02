"""Studio A local-only, confirmation-gated creative brief intake."""
from __future__ import annotations

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.core.content_project import read_local_prompt


class _PromptParams(BaseModel):
    path: str = Field(min_length=1, max_length=1024)


class ContentStudioPrompt(Tool):
    name = "content_studio_prompt"
    description = "Baca brief kreatif lokal terbatas untuk Content Studio; tidak mengunggah atau mengirim file."
    params_schema = _PromptParams
    requires_confirmation = True
    read_only = True
    timeout_s = 15

    async def run(self, *, path: str, **_) -> ToolResult:
        payload = read_local_prompt(path)
        if not payload.get("ok"):
            return ToolResult.fail(str(payload.get("reason", "content_prompt_unavailable")))
        content = {"kind": payload["kind"], "text": payload["text"]}
        return ToolResult.success(content, display="Brief lokal siap dipakai di Content Studio.")


__all__ = ["ContentStudioPrompt"]
