"""BrowserAgentModule — NLP module for Modul 4 & 5.

Connects the user's browser-related voice/text commands to the Rust CLI
agent-browser, enabling accessibility-tree based web agent interactions.
"""
from __future__ import annotations

import asyncio
from jarvis.core import llm, log
from jarvis.nlp.base import Context, NLPModule, Response
from jarvis.browser.agent import BrowserAgent

_logger = log.get("nlp.browser")

class BrowserAgentModule(NLPModule):
    name = "BrowserAgent"

    def __init__(self):
        self.agent = BrowserAgent()

    def can_handle(self, text: str, ctx: Context) -> float:
        t = text.lower()
        if any(w in t for w in ["klik", "ketik", "scroll", "navigasi web", "buka situs", "cari di web"]):
            # Use high confidence to preempt standard routing if explicit browser commands
            return 0.85
        if "browser" in t:
            return 0.7
        return 0.0

    async def handle(self, text: str, ctx: Context) -> Response:
        try:
            tree = await asyncio.to_thread(self.agent.get_accessibility_tree)
            if not tree:
                return Response(
                    "CLI agent-browser tidak merespons atau tidak ditemukan. "
                    "Pastikan `vercel-labs/agent-browser` terinstal dan ada di PATH.",
                    source=self.name
                )
                
            prompt = (
                "Anda adalah JARVIS Web Agent. Berikut adalah accessibility tree JSON "
                "dari halaman web yang sedang aktif (sebagian):\n"
                f"{str(tree)[:15000]}\n\n"
                f"Instruksi pengguna: {text}\n\n"
                "Pilih satu tindakan untuk dieksekusi oleh agent-browser. Balas HANYA dengan format ini:\n"
                "- GOTO <url>\n"
                "- CLICK <target_id>\n"
                "- TYPE <target_id> | <teks yang diketik>\n\n"
                "Jika tidak ada elemen yang relevan, jelaskan dengan singkat."
            )
            
            resp = await asyncio.to_thread(llm.generate, prompt)
            resp = (resp or "").strip()
            
            if resp.startswith("GOTO"):
                url = resp.split("GOTO", 1)[1].strip()
                success = await asyncio.to_thread(self.agent.navigate, url)
                return Response(f"Menavigasi ke {url}." if success else "Gagal menavigasi.", source=self.name)
                
            elif resp.startswith("CLICK"):
                tid = resp.split("CLICK", 1)[1].strip()
                success = await asyncio.to_thread(self.agent.execute_action, "click", target_id=tid)
                return Response(f"Mengklik elemen." if success else "Gagal mengklik.", source=self.name)
                
            elif resp.startswith("TYPE"):
                content = resp.split("TYPE", 1)[1].strip()
                if "|" in content:
                    tid, val = content.split("|", 1)
                    tid, val = tid.strip(), val.strip()
                    success = await asyncio.to_thread(self.agent.execute_action, "type", target_id=tid, value=val)
                    return Response(f"Mengetik teks." if success else "Gagal mengetik.", source=self.name)
                    
            return Response(resp, source=self.name)
            
        except Exception as e:
            _logger.error("browser_agent.handle_error", error=str(e)[:100])
            return Response("Sistem agen browser sedang mengalami kendala teknis.", source=self.name)
