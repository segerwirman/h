"""Clarifying question (§3.1.G) — routing per adapter; sesi cron tidak
bertanya: asumsi dicatat dan agent lanjut."""
from __future__ import annotations

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult


class _ClarifyParams(BaseModel):
    question: str = Field(description="Pertanyaan untuk user")
    options: list[str] = Field(default_factory=list,
                               description="Pilihan jawaban (opsional)")
    context: str = Field("", description="Konteks singkat kenapa bertanya")


class Clarify(Tool):
    name = "clarify"
    description = ("Tanyakan hal ambigu yang PENTING ke user dan tunggu "
                   "jawaban. Jangan dipakai untuk hal remeh — asumsikan "
                   "saja dan sebutkan asumsinya.")
    params_schema = _ClarifyParams
    wants_context = True
    read_only = True
    timeout_s = 330

    async def run(self, question: str, options: list[str] | None = None,
                  context: str = "", _adapter=None, _session=None,
                  **_) -> ToolResult:
        if _adapter is None or not getattr(_adapter, "interactive", False):
            return ToolResult.success(
                "Sesi non-interaktif — user tidak bisa ditanya. Ambil "
                "asumsi paling masuk akal, catat asumsinya di jawaban akhir, "
                "lalu lanjutkan.",
                display="clarify dilewati (non-interaktif)")
        text = question if not context else f"{question}\n({context})"
        answer = await _adapter.ask(text, options or None)
        if answer is None or not str(answer).strip():
            return ToolResult.success(
                "User tidak menjawab. Lanjutkan dengan asumsi paling aman "
                "dan sebutkan asumsi itu.",
                display="tanpa jawaban")
        return ToolResult.success(f"Jawaban user: {answer}",
                                  display=str(answer)[:80])
