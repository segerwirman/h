"""PredictiveText — inline ghost-text autocomplete for the command bar.

Suggests from persisted command history + common intents; the UI shows the
completion as ghost text and Tab accepts it. Not a conversational module —
it never competes in routing.
"""
from __future__ import annotations

import json
from collections import Counter

from jarvis.core import config, log, quiet
from jarvis.nlp.base import Context, Response

_logger = log.get("nlp.predictive")

_COMMON = [
    "cari ", "buka spotify", "buka youtube", "volume 50", "matikan wifi",
    "screenshot", "ringkas halaman ini", "terjemahkan ", "aktifkan kontrol gestur",
    "apa itu ", "buka vscode", "berita hari ini",
]


class PredictiveText:
    name = "PredictiveText"

    def __init__(self) -> None:
        self._path = config.resolve_path(
            config.get("nlp.history_file", "config/command_history.json"))
        self._history: Counter[str] = Counter()
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._history = Counter({str(k): int(v) for k, v in data.items()})
        except Exception as exc:                             # noqa: BLE001
            quiet.swallowed("nlp.predictive.history_load_failed", exc)
            self._history = Counter()

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(dict(self._history.most_common(400)),
                           ensure_ascii=False, indent=1),
                encoding="utf-8")
        except OSError:
            pass

    # ── command-bar API ──────────────────────────────────────────────────────

    def record(self, command: str) -> None:
        command = command.strip()
        if len(command) >= 3:
            self._history[command] += 1
            self._save()

    def suggest(self, prefix: str) -> str:
        """Return the full suggested command ('' if none). Ghost text is
        suggestion[len(prefix):]."""
        prefix = prefix.lstrip()
        if len(prefix) < 2:
            return ""
        pl = prefix.lower()
        # history first (frequency-ranked), then the common-intent seed list
        for cmd, _n in self._history.most_common():
            if cmd.lower().startswith(pl) and len(cmd) > len(prefix):
                return cmd
        for cmd in _COMMON:
            if cmd.lower().startswith(pl) and len(cmd) > len(prefix):
                return cmd
        return ""

    # ── NLPModule protocol (non-routing) ─────────────────────────────────────

    def can_handle(self, text: str, ctx: Context) -> float:
        return 0.0

    async def handle(self, text: str, ctx: Context) -> Response:
        return Response("", speak=False, source=self.name)
