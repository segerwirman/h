"""Command routing methods for the Mark XLIX main window."""
from __future__ import annotations

import sys
import threading

from jarvis.agent.router import Tier as ExecutionTier
from jarvis.agent.router import classify as _classify_execution_default
from jarvis.core import log
from jarvis.core.action_registry import Action
from jarvis.core.bus import BUS
from jarvis.core.resolver import ClarifyNeeded
from jarvis.core.router import Intent
from jarvis.ui.orb import OrbState
from jarvis.ui.window_widgets import execute_typed_action, resolve_typed_action

_logger = log.get("ui")


def classify_execution(text: str, context: dict):
    """Preserve the legacy ``window.classify_execution`` injection seam."""
    window = sys.modules.get("jarvis.ui.window")
    override = getattr(window, "classify_execution", None)
    if override is not None and override is not classify_execution:
        return override(text, context)
    return _classify_execution_default(text, context)


def _agent_ask_active() -> bool:
    """True while native agent waits for local confirmation/cancellation."""
    window = sys.modules.get("jarvis.ui.window")
    override = getattr(window, "_agent_ask_active", None)
    if override is not None and override is not _agent_ask_active:
        return bool(override())
    try:
        from jarvis.agent.adapters.ui import ask_active
        return ask_active()
    except Exception:
        return False


class CommandRoutingMixin:
    """Route typed and lightweight voice commands without owning window state."""

    _CONFIRM_WORDS = ("confirm", "konfirmasi")
    _CANCEL_WORDS = ("cancel", "batalkan aksi")

    def handle_command(self, text: str) -> None:
        # typed path routes here directly — the You: echo must not re-route
        # through the voice intercept in _append_log
        self._skip_next_intercept = True
        self.write_log(f"You: {text}")
        # Destructive-action confirmation gate (redesign §13) uses distinct
        # words from ReplyFlow's ya/batal so the two confirmation contexts
        # never collide.
        if (self._pending_close_decision is not None
                or self._pending_voice_proposal_id is not None
                or _agent_ask_active()):
            low = text.strip().lower()
            if low in self._CONFIRM_WORDS:
                BUS.publish("confirm")
                return
            if low in self._CANCEL_WORDS:
                BUS.publish("cancel")
                return
        if self.reply_flow.handle_utterance(text):     # CONFIRM: ya / batal
            return
        # Jawaban untuk pertanyaan klarifikasi yang tertunda ditangani SEBELUM
        # routing — kalau tidak, "aplikasi" akan diklasifikasi ulang sebagai
        # perintah baru. Kalimat panjang sengaja tidak ditelan (clarify_state
        # mengembalikan None), sehingga user tetap bisa ganti topik.
        # Konfirmasi "matikan dirimu" ditangani sebelum routing — jawaban
        # "ya" tidak boleh diklasifikasi ulang sebagai perintah baru.
        if self._confirm_self_shutdown(text):
            return
        if self._handle_clarify_answer(text):
            return
        local = resolve_typed_action(text)

        def _execute_local(action):
            confirmation = execute_typed_action(action)
            if confirmation is not None:
                self.write_log(f"Jarvis: {confirmation}")
            return confirmation

        # Do not send FallthroughToLLM to Gemini Live yet. Doing that here and
        # then classifying T2 below started both Live chat and the native agent
        # for the same text, which looked like fluent conversation but caused
        # duplicate/competing execution. Local actions and clarification still
        # return immediately; unresolved text is routed exactly once below.
        if isinstance(local, Action):
            if _execute_local(local) is not None:
                return
        elif isinstance(local, ClarifyNeeded):
            self.write_log(f"Jarvis: {local.question}")
            return
        route = classify_execution(text, {"source": "text"})
        _logger.info(
            "router.decision",
            source="text",
            tier=int(route.tier),
            lane=route.lane,
            reason=route.reason,
        )
        if route.tier >= ExecutionTier.AGENT:
            self._run_agent_native(text)
            return
        from jarvis.integrations import google_direct
        google_call = google_direct.match_command(text)
        if google_call is not None:
            self._run_google_light(*google_call)
            return
        c = self.router.classify(text)
        BUS.publish("intent", intent=c.intent.value, text=text, meta=c.slots)
        self._dispatch_command(c, text)

    def _dispatch_command(self, c, text: str) -> None:
        """Normal command routing (no in-frame agent). Shared by the typed path
        and the in-frame agent's fallback so behaviour is identical."""
        if c.intent is Intent.SEARCH_WEB:
            query = c.slots.get("query", text)
            mode = c.slots.get("mode")
            if mode == "news":
                self.run_news(query)
            elif mode == "search":
                self.run_information(query)
            else:
                self.run_search(query)
        elif c.intent is Intent.OPEN_URL:
            self.open_url(c.slots.get("url", ""))
        elif c.intent is Intent.OPEN_BROWSER_AGENT:
            self.open_browser_agent(c.slots)
        elif c.intent is Intent.CLARIFY:
            self._ask_clarify(c.slots)
        elif c.intent is Intent.OPEN_APP:
            self.open_app(c.slots.get("app", text))
        elif c.intent is Intent.SYSTEM:
            self.run_system(c.slots, text)
        elif c.intent is Intent.NATIVE_AGENT_TASK:
            self.run_native_task(c.slots, text)
        else:
            # §31 (S-31) — tepat SEBELUM menyerah ke model, tanyakan router
            # tier yang sering sudah tahu jawabannya secara deterministik.
            # Duduk di sini dengan sengaja: jembatan yang berada di depan
            # segalanya akan mendahului aturan yang sudah benar, untuk SETIAP
            # ucapan. Di sini ia hanya mengisi celah yang tadinya jatuh ke
            # model.
            from jarvis.agent import router as tier_router
            resolved = tier_router.deterministic_tool(text)
            if resolved is not None:
                from jarvis.agent import registry
                if registry.get(resolved[0]) is not None:
                    self._run_deterministic_tool(*resolved)
                    return
            self._chat(text)

    def _run_deterministic_tool(self, tool_name: str, args: dict) -> None:
        """Jalankan tool T1 langsung lewat registry; tidak masuk agent loop.

        Kegagalannya dilaporkan apa adanya — Fase 23 sudah memisahkan
        "browser tidak terjangkau" dari "tidak ada video", dan jembatan ini
        tidak boleh mengubur perbedaan itu lagi.
        """
        self.orb.set_state(OrbState.THINKING)

        def work():
            import asyncio
            from jarvis.agent import registry
            try:
                result = asyncio.run(registry.execute(tool_name, dict(args)))
                if result.ok:
                    text = str(result.display or result.for_llm())
                    self.write_log(f"Jarvis: {text}")
                    self._speak_line(text)
                else:
                    message = result.error or f"{tool_name} gagal tanpa detail."
                    self.write_log(f"ERR: {message}")
                    self._speak_line(message)
            except Exception as exc:                         # noqa: BLE001
                message = f"{tool_name} gagal: {str(exc)[:160]}"
                self.write_log(f"ERR: {message}")
                self._speak_line(message)
            finally:
                self._restore_orb()

        threading.Thread(target=work, daemon=True,
                         name="deterministic-tool").start()

    def _run_google_light(self, tool_name: str, args: dict) -> None:
        """T1 Google langsung via registry; tidak pernah masuk agent loop."""
        self.orb.set_state(OrbState.THINKING)

        def work():
            import asyncio
            from jarvis.agent import registry
            from jarvis.integrations import google_direct
            try:
                tool = registry.get(tool_name)
                if tool is None:
                    message = google_direct.unavailable_message(tool_name)
                    self.write_log(f"SYS: {message}")
                    self._speak_line(message)
                    return
                if not google_direct.enabled_by_tool_group(tool_name):
                    message = ("Tool Google Cloud sedang dimatikan di "
                               "Capabilities.")
                    self.write_log(f"SYS: {message}")
                    self._speak_line(message)
                    return
                result = asyncio.run(registry.execute(tool_name, args))
                text = str(result.display or result.for_llm())
                if result.ok:
                    self._speak_line(text)
                else:
                    message = result.error or "Google API gagal tanpa detail."
                    self.write_log(f"ERR: {message}")
                    self._speak_line(f"Maaf, {message}")
            except Exception as exc:
                message = f"Google tool gagal: {type(exc).__name__}"
                self.write_log(f"ERR: {message}")
                self._speak_line(f"Maaf, {message}")
            finally:
                self._restore_orb()

        threading.Thread(target=work, daemon=True,
                         name=f"google-light-{tool_name}").start()

    def run_search(self, query: str) -> None:
        """§23 — cari sungguhan, lalu tampilkan SUMBERNYA.

        Bentuk lama mengirim ``search_url(query)`` ke browser sistem, dan
        ``query`` kerap jatuh ke transkrip mentah. Yang muncul di layar Takeda
        adalah kalimatnya sendiri:

            'kan saya restoran yang - Search - Google Chrome'

        Itu memantulkan ucapan, bukan menjawabnya. Sekarang pencarian dijalankan
        lewat tool ``web_search`` yang menghasilkan sumber nyata (web, media
        sosial, peta), dan sumber itulah yang ditawarkan untuk dibuka.
        """
        self._run_web_lookup(query, mode="text", label="Informasi")

    def _run_web_lookup(self, query: str, *, mode: str, label: str) -> None:
        """Shared UI worker untuk berita/informasi; tool menentukan fallback."""
        self.orb.set_state(OrbState.THINKING)
        self.write_log(f"SYS: Mengambil {label.lower()} — {query} …")

        def _run() -> None:
            try:
                from actions.web_search import web_search
                result = web_search({"query": query, "mode": mode}, player=self)
                text = str(result or (
                    "Tidak menemukan berita untuk itu, sir."
                    if mode == "news" else "Tidak menemukan informasi untuk itu, sir."))
                self.write_log(f"Jarvis: {text[:700]}")
                self._content_sig.emit(label.upper(), text)
                self._speak_line(text[:900])
            except Exception as exc:                         # noqa: BLE001
                _logger.error("web_lookup.ui_route_failed", mode=mode,
                              exc_type=type(exc).__name__, error=str(exc)[:200])
                message = ("Sumber berita sedang bermasalah, sir. Coba lagi beberapa saat."
                           if mode == "news" else
                           "Tidak bisa menjangkau sumber informasi. Koneksi bermasalah.")
                self.write_log(f"ERR: {label.lower()} — {type(exc).__name__}")
                self._speak_line(message)
            finally:
                self._restore_orb()

        threading.Thread(target=_run, daemon=True,
                         name=f"{mode}-fetch").start()

    def run_news(self, query: str) -> None:
        """Berita nyata: Gemini Grounded + DDG fallback, bukan URL browser."""
        self._run_web_lookup(query, mode="news", label="BERITA")

    def run_information(self, query: str) -> None:
        """Pencarian informasi: Gemini Grounded + DDG fallback, bukan browser."""
        self._run_web_lookup(query, mode="search", label="INFORMASI")
