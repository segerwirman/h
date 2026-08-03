"""Explicit phrase gate for the read-only voice briefing command."""
from __future__ import annotations

_ALLOWED = frozenset({"bacakan briefing", "briefing pagi", "bacakan ringkasan pagi"})


def match(text: str) -> bool:
    return " ".join(str(text or "").casefold().split()) in _ALLOWED


__all__ = ["match"]
