"""Pure deterministic reply policy for low-ambiguity social messages."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class ReplyDisposition(str, Enum):
    AUTO = "auto"
    DRAFT = "draft"
    MANUAL = "manual"


@dataclass(frozen=True)
class ReplyDecision:
    disposition: ReplyDisposition
    reply: str = ""
    reason: str = ""


_DEFAULT_TEMPLATES = MappingProxyType(
    {
        "greeting": (
            "Halo! Terima kasih sudah menghubungi kami.",
            "Hai! Ada yang bisa kami bantu?",
        ),
        "thanks": (
            "Sama-sama! Senang bisa membantu.",
            "Terima kasih kembali!",
        ),
        "positive": (
            "Terima kasih atas dukungannya!",
            "Senang mendengarnya—terima kasih!",
        ),
    }
)
_SENSITIVE_TERMS = (
    "password",
    "passphrase",
    "kata sandi",
    "pin",
    "otp",
    "nomor kartu",
    "kartu kredit",
    "rekening",
    "transfer",
    "pembayaran",
    "alamat rumah",
    "credential",
    "login",
)
_NEGATIVE_TERMS = (
    "buruk",
    "jelek",
    "marah",
    "kecewa",
    "penipuan",
    "scam",
    "benci",
    "rusak",
    "gagal",
    "terrible",
    "awful",
)
_GREETING_TERMS = frozenset({"halo", "hai", "hi", "hello", "pagi", "siang", "sore", "malam"})
_THANKS_PHRASES = (
    ("terima", "kasih"),
    ("makasih",),
    ("thanks",),
    ("thank", "you"),
    ("thx",),
)
_POSITIVE_PHRASES = tuple(
    (term,)
    for term in (
        "bagus",
        "keren",
        "mantap",
        "suka",
        "menyukai",
        "love",
        "loved",
        "awesome",
        "hebat",
    )
)
_NEGATIONS = frozenset(
    {"tidak", "tak", "bukan", "gak", "nggak", "ga", "no", "not", "never"}
)
_NEGATED_CONTRACTIONS = frozenset(
    {
        "aren",
        "can",
        "couldn",
        "didn",
        "doesn",
        "don",
        "hadn",
        "hasn",
        "haven",
        "isn",
        "mustn",
        "needn",
        "shouldn",
        "wasn",
        "weren",
        "won",
        "wouldn",
    }
)
_REQUEST_TERMS = frozenset(
    {
        "apa",
        "apakah",
        "bagaimana",
        "bisa",
        "boleh",
        "but",
        "can",
        "could",
        "how",
        "missing",
        "mohon",
        "namun",
        "order",
        "pesanan",
        "please",
        "refund",
        "status",
        "tapi",
        "tolong",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "would",
    }
)
_REQUEST_PHRASES = (
    ("bantu", "kami"),
    ("bantu", "saya"),
    ("explain",),
    ("help", "me"),
    ("help", "us"),
    ("jelaskan",),
    ("return", "instructions"),
    ("send", "details"),
    ("share", "details"),
)
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_OPEN_ENDED_PREFIXES = (
    "mengapa ",
    "kenapa ",
    "bagaimana ",
    "menurut kamu ",
    "menurut anda ",
    "apa pendapat",
)


def _normalize(text: str) -> str:
    return " ".join(str(text or "").casefold().split())


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _phrase_starts(tokens: list[str], phrases: tuple[tuple[str, ...], ...]) -> list[int]:
    starts = []
    for index in range(len(tokens)):
        if any(tokens[index : index + len(phrase)] == list(phrase) for phrase in phrases):
            starts.append(index)
    return starts


def _is_negated(tokens: list[str], phrase_start: int, *, lookback: int = 5) -> bool:
    start = max(0, phrase_start - lookback)
    prefix = tokens[start:phrase_start]
    return any(token in _NEGATIONS for token in prefix) or any(
        token in _NEGATED_CONTRACTIONS
        and index + 1 < len(prefix)
        and prefix[index + 1] == "t"
        for index, token in enumerate(prefix)
    )


def _contains_request(tokens: list[str], normalized: str) -> bool:
    return (
        normalized.endswith("?")
        or any(token in _REQUEST_TERMS for token in tokens)
        or bool(_phrase_starts(tokens, _REQUEST_PHRASES))
    )


class DeterministicReplyPolicy:
    """Classify only explicit low-ambiguity messages for automatic replies."""

    def __init__(
        self,
        *,
        faq: Mapping[str, str] | None = None,
        templates: Mapping[str, tuple[str, ...]] | None = None,
        max_reply_chars: int = 280,
    ) -> None:
        self._max_reply_chars = max(1, min(500, int(max_reply_chars)))
        self._faq = {
            _normalize(question): self._bounded(reply)
            for question, reply in dict(faq or {}).items()
            if _normalize(question) and self._bounded(reply)
        }
        source = dict(_DEFAULT_TEMPLATES)
        source.update(dict(templates or {}))
        self._templates = {
            key: tuple(
                bounded
                for value in values
                if (bounded := self._bounded(value))
            )
            for key, values in source.items()
        }

    def classify(
        self,
        text: str,
        *,
        platform: str = "",
        author_id: str = "",
    ) -> ReplyDecision:
        normalized = _normalize(text)
        if not normalized:
            return ReplyDecision(ReplyDisposition.MANUAL, reason="empty")
        if any(term in normalized for term in _SENSITIVE_TERMS):
            return ReplyDecision(ReplyDisposition.MANUAL, reason="sensitive")
        if any(term in normalized for term in _NEGATIVE_TERMS):
            return ReplyDecision(ReplyDisposition.MANUAL, reason="negative")
        if normalized in self._faq:
            return ReplyDecision(
                ReplyDisposition.AUTO,
                self._faq[normalized],
                "faq_exact",
            )
        tokens = _tokens(normalized)
        words = frozenset(tokens)
        if words and words <= _GREETING_TERMS:
            return self._template("greeting", normalized, platform, author_id)
        thanks_starts = _phrase_starts(tokens, _THANKS_PHRASES)
        positive_starts = _phrase_starts(tokens, _POSITIVE_PHRASES)
        if any(_is_negated(tokens, start) for start in positive_starts):
            return ReplyDecision(ReplyDisposition.DRAFT, reason="negated_positive")
        if any(_is_negated(tokens, start) for start in thanks_starts):
            return ReplyDecision(ReplyDisposition.DRAFT, reason="negated_thanks")
        if (thanks_starts or positive_starts) and _contains_request(tokens, normalized):
            return ReplyDecision(ReplyDisposition.DRAFT, reason="mixed_request")
        if thanks_starts:
            return self._template("thanks", normalized, platform, author_id)
        if positive_starts:
            return self._template("positive", normalized, platform, author_id)
        if normalized.endswith("?") or any(
            normalized.startswith(prefix) for prefix in _OPEN_ENDED_PREFIXES
        ):
            return ReplyDecision(ReplyDisposition.DRAFT, reason="open_ended")
        return ReplyDecision(ReplyDisposition.DRAFT, reason="ambiguous")

    def _template(
        self,
        category: str,
        normalized: str,
        platform: str,
        author_id: str,
    ) -> ReplyDecision:
        values = self._templates.get(category, ())
        if not values:
            return ReplyDecision(ReplyDisposition.DRAFT, reason="template_missing")
        seed = "\x1f".join((category, platform, author_id, normalized)).encode("utf-8")
        index = int.from_bytes(hashlib.sha256(seed).digest()[:8], "big") % len(values)
        return ReplyDecision(ReplyDisposition.AUTO, values[index], category)

    def _bounded(self, value: str) -> str:
        return str(value or "").strip()[: self._max_reply_chars]


__all__ = [
    "DeterministicReplyPolicy",
    "ReplyDecision",
    "ReplyDisposition",
]
