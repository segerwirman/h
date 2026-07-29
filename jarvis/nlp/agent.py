"""Hermes-Style Agentic Orchestrator (Modul 9).

Performs multi-step reasoning (Thought -> Action -> Observation -> Response).
Integrates Persistent Memory (Modul 6) for context and self-improvement.
"""
from __future__ import annotations

import asyncio
import re
from jarvis.core import llm, log
from jarvis.core.memory import MemoryManager
from jarvis.nlp.base import Context, NLPModule, Response

_logger = log.get("nlp.agent")

class HermesAgent(NLPModule):
    name = "HermesAgent"

    def __init__(self):
        self.memory = MemoryManager.get()
        self.max_steps = 5

    def can_handle(self, text: str, ctx: Context) -> float:
        # Agent handles complex requests, multi-step tasks, or explicit agent triggers.
        t = text.lower()
        complex_triggers = ["tolong lakukan", "cari dan", "analisis", "buatkan", "rencana", "otomatisasi", "investigasi"]
        if any(w in t for w in complex_triggers):
            return 0.75
        # Fallback score if Chatbot is disabled or we want agent by default
        return 0.65

    async def handle(self, text: str, ctx: Context) -> Response:
        try:
            # 1. Fetch semantic memory context
            past_memories = await asyncio.to_thread(self.memory.search_semantic, text, top_k=3)
            memory_context = ""
            if past_memories:
                memory_context = "\nMemori relevan dari masa lalu:\n" + "\n".join(f"- {m}" for m in past_memories)

            # 2. Agentic Loop Setup
            system_prompt = (
                "Anda adalah JARVIS, asisten AI super cerdas (seperti J.A.R.V.I.S dari Iron Man). "
                "Gunakan format pemikiran bertahap (Thought, Action, Observation, Response).\n"
                "Anda dapat menggunakan alat (tools) jika diperlukan. Saat ini alat yang tersedia terbatas pada:\n"
                "1. SAVE_MEMORY <informasi> (Menyimpan fakta/skrip ke memori jangka panjang)\n"
                "2. BROWSER_ACTION <perintah> (Mendelegasikan ke modul browser agent)\n"
                "3. RELAY_CONNECTION_STATUS (Status koneksi integrasi Relay.app — read-only)\n"
                "4. RELAY_LIST_AVAILABLE_SOURCES (Daftar workflow/sumber Relay yang tersedia)\n"
                "5. RELAY_READ_EVENTS [jumlah] (Baca event Relay terbaru, maks 25)\n"
                "6. RELAY_GET_WORKFLOW_RESULT <nama_workflow> (Hasil terakhir sebuah workflow Relay)\n"
                "Semua alat RELAY_* bersifat read-only dan tidak pernah mengubah data.\n"
                "Jika tidak butuh alat, langsung berikan Response akhir.\n"
                f"{memory_context}"
            )
            
            history = f"User: {text}\n"
            step = 0
            
            while step < self.max_steps:
                step += 1
                prompt = system_prompt + "\n" + history + "\nAssistant: "
                
                resp_text = await asyncio.to_thread(llm.generate, prompt)
                resp_text = (resp_text or "").strip()
                
                # Parse action if any
                if "SAVE_MEMORY" in resp_text:
                    action_match = re.search(r"SAVE_MEMORY\s+(.+)", resp_text)
                    if action_match:
                        info = action_match.group(1).strip()
                        await asyncio.to_thread(self.memory.add_semantic, info)
                        history += f"{resp_text}\nObservation: Memori berhasil disimpan.\n"
                        continue
                        
                elif "BROWSER_ACTION" in resp_text:
                    action_match = re.search(r"BROWSER_ACTION\s+(.+)", resp_text)
                    if action_match:
                        cmd = action_match.group(1).strip()
                        from jarvis.nlp.browser_agent import BrowserAgentModule
                        browser = BrowserAgentModule()
                        b_resp = await browser.handle(cmd, ctx)
                        history += f"{resp_text}\nObservation: {b_resp.text}\n"
                        continue

                elif "RELAY_" in resp_text:
                    obs = await asyncio.to_thread(self._relay_tool, resp_text)
                    if obs is not None:
                        history += f"{resp_text}\nObservation: {obs}\n"
                        continue

                # If no tool called, assume final response
                final_answer = resp_text
                # extract from 'Response:' if format used
                if "Response:" in resp_text:
                    final_answer = resp_text.split("Response:")[-1].strip()
                    
                # Save this interaction to episodic log
                await asyncio.to_thread(self.memory.add_episodic, "user", text)
                await asyncio.to_thread(self.memory.add_episodic, "assistant", final_answer)
                
                return Response(final_answer, source=self.name)
                
            return Response("Tugas terlalu kompleks dan mencapai batas iterasi agen.", source=self.name)
            
        except Exception as e:
            _logger.error("agent.handle_error", error=str(e))
            return Response("Sistem agentik mengalami gangguan.", source=self.name)

    # ── Relay.app read-only tools (Fase 5) ───────────────────────────────────
    def _relay_tool(self, resp_text: str) -> str | None:
        """Execute one RELAY_* tool mentioned in the model output.
        Returns an observation string, or None when no tool actually matched.
        Structured errors; never raises; never exposes credentials."""
        import json as _json
        try:
            from jarvis.integrations.relay.service import RelayService
            svc = RelayService.get()
            if "RELAY_CONNECTION_STATUS" in resp_text:
                return _json.dumps(svc.status(), ensure_ascii=False)
            if "RELAY_LIST_AVAILABLE_SOURCES" in resp_text:
                if not svc.enabled:
                    return "Integrasi Relay dinonaktifkan (RELAY_ENABLED=0)."
                return _json.dumps(svc.sources()[:25], ensure_ascii=False)
            if "RELAY_READ_EVENTS" in resp_text:
                if not svc.enabled:
                    return "Integrasi Relay dinonaktifkan (RELAY_ENABLED=0)."
                m = re.search(r"RELAY_READ_EVENTS\s+(\d+)", resp_text)
                limit = int(m.group(1)) if m else 5
                events = svc.recent_events(limit)
                return (_json.dumps(events, ensure_ascii=False)
                        if events else "Belum ada event Relay yang diterima.")
            if "RELAY_GET_WORKFLOW_RESULT" in resp_text:
                if not svc.enabled:
                    return "Integrasi Relay dinonaktifkan (RELAY_ENABLED=0)."
                m = re.search(r"RELAY_GET_WORKFLOW_RESULT\s+(\S+)", resp_text)
                if not m:
                    return "Sebutkan nama workflow-nya."
                result = svc.workflow_result(m.group(1).strip())
                return (_json.dumps(result, ensure_ascii=False)
                        if result else "Tidak ada hasil untuk workflow itu.")
            return None
        except Exception as e:
            _logger.error("agent.relay_tool_error", error=str(e)[:120])
            return f"Tool Relay gagal: {type(e).__name__}"
