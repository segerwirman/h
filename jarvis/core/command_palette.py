"""Command Palette matching core — fuzzy search over the command registry,
recent actions, procedural macros, and known apps/sites (redesign §12).

Pure Python (no Qt) so ranking/confidence logic is unit-testable headless.
A destructive candidate is always tagged ``is_destructive=True`` so the UI
can label it; nothing here executes anything — it only ranks candidates.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field

LOW_CONFIDENCE_THRESHOLD = 0.55


@dataclass
class PaletteCandidate:
    label: str
    kind: str                  # command | app | recent | macro | site
    action_id: str
    confidence: float
    source: str                 # registry | memory | macro | fuzzy
    is_destructive: bool = False
    meta: dict = field(default_factory=dict)


class CommandPaletteModel:
    def __init__(self):
        self._commands: list[dict] = []
        self._apps: list[str] = []
        self._sites: dict[str, str] = {}
        self._recent: list[dict] = []
        self._macros: list[dict] = []

    def set_commands(self, commands: list[dict]) -> None:
        self._commands = commands

    def set_apps(self, apps: list[str]) -> None:
        self._apps = apps

    def set_sites(self, sites: dict[str, str]) -> None:
        self._sites = sites

    def set_recent(self, recent: list[dict]) -> None:
        self._recent = recent

    def set_macros(self, macros: list[dict]) -> None:
        self._macros = macros

    def query(self, text: str, limit: int = 8) -> list[PaletteCandidate]:
        text = text.strip()
        if not text:
            return self._default_candidates(limit)

        pool: list[PaletteCandidate] = []
        for cmd in self._commands:
            pool.append(self._score(text, cmd["label"], "command", cmd["action_id"],
                                    "registry", cmd.get("destructive", False), cmd))
        for app in self._apps:
            pool.append(self._score(text, app, "app", app, "registry"))
        for name, url in self._sites.items():
            pool.append(self._score(text, name, "site", url, "registry"))
        for macro in self._macros:
            pool.append(self._score(text, macro["name"], "macro", macro["name"], "macro",
                                    False, macro))
        for item in self._recent:
            label = item.get("target") or (item.get("content", "") or "")[:60]
            if not label:
                continue
            pool.append(self._score(text, label, "recent", label, "memory", False, item))

        pool = [c for c in pool if c.confidence > 0.2]
        pool.sort(key=lambda c: c.confidence, reverse=True)
        return pool[:limit]

    def _default_candidates(self, limit: int) -> list[PaletteCandidate]:
        return [PaletteCandidate(c["label"], "command", c["action_id"], 1.0, "registry",
                                 c.get("destructive", False), c)
                for c in self._commands[:limit]]

    @staticmethod
    def _score(text: str, label: str, kind: str, action_id: str, source: str,
              destructive: bool = False, meta: dict | None = None) -> PaletteCandidate:
        t, low_label = text.lower(), label.lower()
        if t == low_label:
            conf = 1.0
        elif t in low_label:
            conf = 0.85
        else:
            conf = difflib.SequenceMatcher(None, t, low_label).ratio()
        return PaletteCandidate(label, kind, action_id, conf, source, destructive, meta or {})
