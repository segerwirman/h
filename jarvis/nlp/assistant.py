"""SmartAssistant — the orchestrator (Part 5).

Routes each turn: sentiment observation first (always), then polls every
module's can_handle() and takes the argmax above the configured threshold,
falling back to Chatbot. Holds the persona and the shared Context.
"""
from __future__ import annotations

import asyncio

from jarvis.core import config, log
from jarvis.core.bus import BUS
from jarvis.nlp.base import Context, NLPModule, Response

_logger = log.get("nlp.assistant")


class SmartAssistant:
    name = "SmartAssistant"

    def __init__(self) -> None:
        self.ctx = Context()
        self._threshold = float(config.get("nlp.route_threshold", 0.6))
        self._modules: list[NLPModule] = []
        self._chatbot: NLPModule | None = None
        self._sentiment = None

    # ── registry ─────────────────────────────────────────────────────────────

    def register_defaults(self) -> None:
        """Instantiate the full capability set; each import is independent so
        a broken optional dependency only removes its own module."""
        from jarvis.nlp.chatbot import Chatbot
        from jarvis.nlp.sentiment import SentimentAnalysis
        self._chatbot = Chatbot()
        self._sentiment = SentimentAnalysis()
        self._modules = [self._chatbot, self._sentiment]

        for path, cls_name in [
            ("jarvis.nlp.agent", "HermesAgent"),
            ("jarvis.nlp.summarize", "AutomaticSummarization"),
            ("jarvis.nlp.translation", "LanguageTranslation"),
            ("jarvis.nlp.document", "DocumentAnalysis"),
            ("jarvis.nlp.search", "OnlineSearch"),
            ("jarvis.nlp.predictive", "PredictiveText"),
            ("jarvis.nlp.social", "SocialMediaMonitoring"),
            ("jarvis.nlp.email_filter", "EmailFiltering"),
            ("jarvis.nlp.browser_agent", "BrowserAgentModule"),
        ]:
            try:
                mod = __import__(path, fromlist=[cls_name])
                self._modules.append(getattr(mod, cls_name)())
            except Exception as e:
                _logger.warning("nlp.module_unavailable", module=cls_name,
                                error=str(e)[:120])

    def register(self, module: NLPModule) -> None:
        self._modules.append(module)

    def module(self, name: str):
        for m in self._modules:
            if m.name == name:
                return m
        return None

    # ── routing ──────────────────────────────────────────────────────────────

    def route_sync(self, text: str) -> tuple[NLPModule, float]:
        """Poll all modules, argmax above threshold, else Chatbot."""
        if self._sentiment is not None:
            self._sentiment.observe(text, self.ctx)

        best: NLPModule | None = None
        best_score = 0.0
        for m in self._modules:
            try:
                s = float(m.can_handle(text, self.ctx))
            except Exception as e:
                _logger.warning("nlp.can_handle_failed", module=m.name,
                                error=str(e)[:120])
                continue
            if s > best_score:
                best, best_score = m, s

        if best is None or best_score < self._threshold:
            best, best_score = self._chatbot, max(best_score, 0.0)
        _logger.info("nlp.routed", module=best.name,
                     confidence=round(best_score, 2), text=text[:100])
        return best, best_score

    async def handle(self, text: str) -> Response:
        module, conf = self.route_sync(text)
        self.ctx.add_turn("user", text)
        try:
            resp = await module.handle(text, self.ctx)
        except Exception as e:
            _logger.error("nlp.handle_failed", module=module.name,
                          error=str(e)[:200])
            resp = Response(f"Modul {module.name} mengalami kendala, sir.",
                            source=module.name)
        resp.source = resp.source or module.name
        resp.meta.setdefault("confidence", conf)
        self.ctx.add_turn("assistant", resp.text)
        BUS.publish("nlp.response", module=resp.source, text=resp.text)
        return resp

    def handle_blocking(self, text: str) -> Response:
        """Convenience for callers without an event loop (worker threads)."""
        return asyncio.run(self.handle(text))
