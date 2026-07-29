"""Aggregate live-comment sentiment (redesign §15).

Reuses the existing lexicon scorer (``jarvis.nlp.sentiment.score``) instead
of duplicating sentiment logic — the same ID/EN lexicon already used for
conversational tone adaptation. Aggregation runs over a sliding window of
the most recent comments, with a per-author share cap so one highly-active
commenter (or a spam burst) cannot dominate the aggregate reading. Only the
aggregate is ever labeled — no per-person sentiment label is produced.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from jarvis.core import config
from jarvis.nlp.sentiment import score as lexicon_score


@dataclass
class SentimentSnapshot:
    label: str            # positive | neutral | negative | mixed
    average: float         # -1..1
    sample_count: int
    confidence: float      # 0..1, grows with sample_count


class CommentSentimentMeter:
    def __init__(self, window_size: int | None = None,
                max_share_per_author: float | None = None):
        c = config.section("live_comments.sentiment")
        self.enabled = bool(c.get("enabled", True))
        self._window: deque = deque(maxlen=window_size or int(c.get("window_size", 100)))
        self._max_share = (max_share_per_author if max_share_per_author is not None
                           else float(c.get("max_share_per_author", 0.2)))

    def observe(self, author_id: str, text: str) -> float:
        s = lexicon_score(text)
        self._window.append((author_id, s))
        return s

    def snapshot(self) -> SentimentSnapshot:
        if not self._window:
            return SentimentSnapshot("neutral", 0.0, 0, 0.0)
        capped = self._cap_author_dominance(list(self._window))
        avg = sum(s for _, s in capped) / len(capped)
        pos = sum(1 for _, s in capped if s > 0.15)
        neg = sum(1 for _, s in capped if s < -0.15)
        if pos and neg and min(pos, neg) / len(capped) > 0.25:
            label = "mixed"
        elif avg > 0.15:
            label = "positive"
        elif avg < -0.15:
            label = "negative"
        else:
            label = "neutral"
        confidence = min(1.0, len(capped) / max(1, self._window.maxlen or 100))
        return SentimentSnapshot(label, round(avg, 3), len(capped), round(confidence, 3))

    def _cap_author_dominance(self, items: list[tuple[str, float]]) -> list[tuple[str, float]]:
        if not items:
            return items
        max_count = max(1, int(len(items) * self._max_share))
        counts: dict[str, int] = {}
        capped = []
        for author, s in items:
            counts[author] = counts.get(author, 0) + 1
            if counts[author] <= max_count:
                capped.append((author, s))
        return capped or items
