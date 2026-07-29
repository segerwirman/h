"""Chatbot — freeform conversation fallback with rolling context (Part 5)."""
from __future__ import annotations

import asyncio

from jarvis.core import config, llm
from jarvis.nlp.base import Context, Response

PERSONA = (
    "Anda adalah J.A.R.V.I.S, asisten AI pribadi. Panggil pengguna 'sir'. "
    "Jawab ringkas, cerdas, sedikit kering humornya. Gunakan bahasa yang "
    "dipakai pengguna (Indonesia atau Inggris)."
)


class Chatbot:
    name = "Chatbot"

    def can_handle(self, text: str, ctx: Context) -> float:
        # Fallback module: modest score so specialists win the argmax,
        # SmartAssistant routes here explicitly when nothing clears threshold.
        return 0.3 if text.strip() else 0.0

    async def handle(self, text: str, ctx: Context) -> Response:
        turns = int(config.get("nlp.chat_context_turns", 12))
        history = ctx.history[-turns:]
        convo = "\n".join(f"{h['role']}: {h['text']}" for h in history)
        tone = ""
        if ctx.sentiment < -0.35:
            tone = ("\n[Catatan nada: pengguna tampak frustrasi — jawab dengan "
                    "tenang, empatik, langsung ke solusi. Jangan sebut analisis "
                    "sentimen.]")
        prompt = f"{convo}\nuser: {text}\nassistant:" if convo else text
        body = await asyncio.to_thread(
            llm.generate, prompt + tone, PERSONA)
        return Response(body or "Maaf sir, modul percakapan sedang tidak "
                        "tersedia.", source=self.name)
