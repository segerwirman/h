"""Shared pure title/application privacy matcher for desktop observation lanes."""
from __future__ import annotations

from collections.abc import Iterable

from jarvis.core import config


def is_denylisted(title: str, app: str, *, terms: Iterable[object] | None = None) -> bool:
    """Return whether a configured privacy term occurs in title or application name."""
    if terms is None:
        terms = config.get("awareness.privacy.denylist", []) or []
    haystack = f"{title} {app}".casefold()
    return any(str(term).casefold() in haystack for term in terms if str(term).strip())


__all__ = ["is_denylisted"]
