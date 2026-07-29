"""SentimentAnalysis — score every utterance, adapt tone, log the trend.

Fast lexicon scorer (ID + EN) so it can run on every turn without an LLM
round-trip. Scores are USED (tone adaptation via ctx.sentiment) but never
announced unprompted; asking explicitly ("bagaimana mood saya") is the only
path that verbalizes them.
"""
from __future__ import annotations

import json
import re
import time

from jarvis.core import config, log
from jarvis.core.bus import BUS
from jarvis.nlp.base import Context, Response

_logger = log.get("nlp.sentiment")

_POS = {
    "bagus", "hebat", "keren", "mantap", "terima kasih", "makasih", "senang",
    "suka", "cinta", "berhasil", "sukses", "sempurna", "luar biasa", "oke",
    "great", "good", "awesome", "thanks", "thank", "love", "nice", "perfect",
    "works", "happy", "excellent", "cool",
}
_NEG = {
    "buruk", "jelek", "bodoh", "gagal", "error", "rusak", "kesal", "marah",
    "benci", "lambat", "payah", "sampah", "salah", "tidak bisa", "gabisa",
    "bad", "terrible", "hate", "broken", "stupid", "fail", "failed", "wrong",
    "slow", "annoying", "useless", "crash", "angry",
}
_INTENSIFIERS = {"sangat", "banget", "sekali", "very", "really", "so"}

_WORD_RE = re.compile(r"[a-zA-Z']+")


def score(text: str) -> float:
    """−1..+1 lexicon sentiment."""
    t = text.lower()
    words = _WORD_RE.findall(t)
    pos = sum(1 for w in words if w in _POS) + sum(1 for p in _POS if " " in p and p in t)
    neg = sum(1 for w in words if w in _NEG) + sum(1 for p in _NEG if " " in p and p in t)
    boost = 1.5 if any(w in _INTENSIFIERS for w in words) else 1.0
    total = pos + neg
    if total == 0:
        return 0.0
    return max(-1.0, min(1.0, boost * (pos - neg) / max(2, total)))


class SentimentAnalysis:
    name = "SentimentAnalysis"

    def __init__(self) -> None:
        self._log_path = config.resolve_path(
            config.get("nlp.sentiment_log", "logs/sentiment.jsonl"))
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._trend: list[tuple[float, float]] = []

    # service API — SmartAssistant calls this on EVERY user turn
    def observe(self, text: str, ctx: Context) -> float:
        s = score(text)
        # exponential rolling blend into the shared context
        ctx.sentiment = 0.7 * ctx.sentiment + 0.3 * s
        # UI subtly reflects mood via orb glow (redesign §6) — audio stays
        # the dominant visual input, this is a small clamped nudge only.
        BUS.publish("sentiment.updated", value=ctx.sentiment)
        self._trend.append((time.time(), s))
        del self._trend[:-500]
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": time.time(), "score": s,
                                    "rolling": round(ctx.sentiment, 3)}) + "\n")
        except OSError:
            pass
        _logger.debug("sentiment.observed", score=s,
                      rolling=round(ctx.sentiment, 3))
        return s

    def can_handle(self, text: str, ctx: Context) -> float:
        t = text.lower()
        if any(k in t for k in ("mood saya", "perasaan saya", "sentimen",
                                "my mood", "how do i sound", "am i angry")):
            return 0.8
        return 0.0            # service module — runs via observe(), not routing

    async def handle(self, text: str, ctx: Context) -> Response:
        recent = [s for ts, s in self._trend[-20:]]
        if not recent:
            return Response("Belum ada data suasana percakapan, sir.",
                            source=self.name)
        avg = sum(recent) / len(recent)
        label = ("positif" if avg > 0.15 else
                 "negatif" if avg < -0.15 else "netral")
        return Response(
            f"Dari {len(recent)} ucapan terakhir, nada percakapan Anda "
            f"cenderung {label} (rata-rata {avg:+.2f}).", source=self.name)
