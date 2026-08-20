"""P6-A — Presentation adapter seam (pure Python, Qt-free).

First slice of roadmap P6 / GUI_EVOLUTION_PLAN GUI-1: the smallest
presentation boundary between the semantic owners and the shell. This module
adds NO behavior change: ``FacadeShim`` is a pass-through recorder around the
legacy facade. The legacy shell remains the only deployed shell and its
appearance is unchanged.

Design rules:
- no PyQt import anywhere in this module (both legacy and future modern
  shells must be able to consume it headless);
- no business logic, no providers, no BUS subscription, no second registry;
- delegation is exactly one call per facade method, arguments unmuted;
- the viewport applies the SAME bounds the legacy facade already applies
  (title[:64], text[:6000]) so the semantic model can never carry more than
  the shell already shows.
"""
from __future__ import annotations

_TITLE_BOUND = 64
_TEXT_BOUND = 6000
_DEFAULT_LOG_BOUND = 200


class SemanticViewPort:
    """Bounded, non-secret, presentation-relevant state mirror.

    Values mirror what the legacy shell already renders; this is a consumer
    model for future shells, never a second owner.
    """

    def __init__(self, max_log: int = _DEFAULT_LOG_BOUND):
        self._max_log = max(1, int(max_log))
        self._state: str = ""
        self._title: str = ""
        self._text: str = ""
        self._log: list[str] = []

    @property
    def state(self) -> str:
        return self._state

    @property
    def title(self) -> str:
        return self._title

    @property
    def text(self) -> str:
        return self._text

    @property
    def log(self) -> tuple[str, ...]:
        return tuple(self._log)

    def apply_state(self, state: str) -> None:
        self._state = state

    def apply_content(self, title: str, text: str) -> None:
        self._title = title[:_TITLE_BOUND]
        self._text = text[:_TEXT_BOUND]

    def append_log(self, line: str) -> None:
        self._log.append(line)
        if len(self._log) > self._max_log:
            del self._log[: len(self._log) - self._max_log]


class IntentRecorder:
    """One record per delegated user action; read-side only."""

    def __init__(self):
        self._intents: list[dict] = []

    def record(self, intent: str, **meta) -> None:
        self._intents.append({"intent": intent, "meta": dict(meta)})

    @property
    def intents(self) -> tuple[dict, ...]:
        return tuple(self._intents)

    def clear(self) -> None:
        self._intents.clear()


class FacadeShim:
    """Pass-through around the legacy facade: exactly one delegation per call,
    arguments unmuted, semantic values mirrored into the viewport."""

    def __init__(self, facade, viewport: SemanticViewPort | None = None):
        self._facade = facade
        self.viewport = viewport if viewport is not None else SemanticViewPort()
        self.recorder = IntentRecorder()

    # ── delegated surfaces (mirror legacy facade exactly) ────────────────────

    def set_state(self, state: str) -> None:
        self._facade.set_state(state)
        self.viewport.apply_state(state)

    def write_log(self, text: str) -> None:
        self._facade.write_log(text)
        self.viewport.append_log(text)

    def show_content(self, title: str, text: str) -> None:
        self._facade.show_content(title, text)
        self.viewport.apply_content(title, text)

    # ── user-action surface ──────────────────────────────────────────────────

    def submit_text(self, text: str) -> None:
        """Forward one user submission to the facade's text-command callback
        and record exactly one intent."""
        cb = getattr(self._facade, "on_text_command", None)
        if cb is not None:
            cb(text)
        self.recorder.record("submit_text", text=text)
