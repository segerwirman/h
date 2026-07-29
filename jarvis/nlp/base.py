"""NLP capability module protocol (Part 5)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class Context:
    """Rolling conversational context shared across modules."""
    history: list[dict] = field(default_factory=list)   # {role, text}
    uploaded_file: str | None = None
    last_url: str | None = None
    sentiment: float = 0.0            # −1..+1 rolling user sentiment
    language: str = "id"
    extras: dict[str, Any] = field(default_factory=dict)

    def add_turn(self, role: str, text: str, max_turns: int = 24) -> None:
        self.history.append({"role": role, "text": text})
        del self.history[:-max_turns]


@dataclass
class Response:
    text: str
    speak: bool = True                # route to TTS?
    show_on_stage: bool = False       # push to ContentStage card?
    source: str = ""                  # module name
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class NLPModule(Protocol):
    name: str

    def can_handle(self, text: str, ctx: Context) -> float: ...
    async def handle(self, text: str, ctx: Context) -> Response: ...
