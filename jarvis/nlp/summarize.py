"""AutomaticSummarization — reusable summarizer (Part 5).

Consumed by OnlineSearch, DocumentAnalysis and the activity log
("what happened in the last hour?"). Also usable directly as a module.
"""
from __future__ import annotations

import asyncio
import time

from jarvis.core import config, llm
from jarvis.nlp.base import Context, Response

_SUMMARY_SYSTEM = (
    "Anda adalah modul ringkasan JARVIS. Ringkas teks yang diberikan "
    "secara akurat tanpa menambahkan informasi luar. Format: poin-poin "
    "singkat diikuti satu kalimat kesimpulan. Gunakan bahasa yang sama "
    "dengan permintaan pengguna (default: Bahasa Indonesia)."
)

_TRIGGERS = ("ringkas", "rangkum", "summarize", "summarise", "tl;dr", "tldr",
             "apa yang terjadi", "what happened")


def summarize_text(text: str, instruction: str = "",
                   language: str = "id") -> str:
    """Synchronous reusable entry point for other modules."""
    if not text.strip():
        return ""
    prompt = (f"Instruksi: {instruction or 'ringkas teks berikut'}\n"
              f"Bahasa keluaran: {language}\n\nTeks:\n{text[:24000]}")
    return llm.generate(prompt, system=_SUMMARY_SYSTEM)


class ActivityLogSource:
    """Ring buffer of activity lines the summarizer can answer about."""

    def __init__(self, max_lines: int = 2000):
        self._lines: list[tuple[float, str]] = []
        self._max = max_lines

    def add(self, line: str) -> None:
        self._lines.append((time.time(), line))
        del self._lines[:-self._max]

    def window(self, seconds: float) -> str:
        cutoff = time.time() - seconds
        return "\n".join(line for ts, line in self._lines if ts >= cutoff)


ACTIVITY_LOG = ActivityLogSource()


class AutomaticSummarization:
    name = "AutomaticSummarization"

    def can_handle(self, text: str, ctx: Context) -> float:
        t = text.lower()
        if not any(k in t for k in _TRIGGERS):
            return 0.0
        # something to summarize? doc, last page, or the activity log
        if ctx.uploaded_file or ctx.extras.get("page_text") or "terjadi" in t \
                or "happened" in t or "log" in t:
            return 0.9
        return 0.65

    async def handle(self, text: str, ctx: Context) -> Response:
        t = text.lower()
        if "terjadi" in t or "happened" in t or "log" in t:
            hours = 1.0
            source = ACTIVITY_LOG.window(hours * 3600)
            if not source.strip():
                return Response("Tidak ada aktivitas tercatat dalam satu jam "
                                "terakhir.", source=self.name)
            body = await asyncio.to_thread(
                summarize_text, source,
                "ringkas aktivitas sistem berikut untuk pengguna", ctx.language)
            return Response(body or "Ringkasan tidak tersedia.",
                            show_on_stage=True, source=self.name)

        target = ctx.extras.get("page_text") or ""
        if not target and ctx.uploaded_file:
            from jarvis.nlp.document import read_document
            target = await asyncio.to_thread(read_document, ctx.uploaded_file)
        if not target:
            return Response("Tidak ada konten untuk diringkas — unggah "
                            "dokumen atau buka halaman terlebih dahulu.",
                            source=self.name)
        body = await asyncio.to_thread(summarize_text, target, text, ctx.language)
        return Response(body or "Ringkasan tidak tersedia.",
                        show_on_stage=True, source=self.name)
