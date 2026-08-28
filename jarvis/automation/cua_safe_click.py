"""One deliberately narrow CUA vertical slice: semantic left-click only.

The caller injects capture and click primitives. This module never captures a
screen, invokes a vision provider, or accepts coordinates from an agent. It
consumes a semantic tree, issues a short-lived ref through ``CuaSafetyGate``,
and requires a same-surface recapture after exactly one click attempt.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from jarvis.automation.cua_safety import (
    CuaObservation,
    CuaSafetyGate,
    SemanticTargetRef,
)
from jarvis.core.element_model import ScreenElementTree, elements_from_harvest


@dataclass(frozen=True)
class CaptureFrame:
    surface_id: str
    tree: ScreenElementTree
    privacy: str = "normal"


@dataclass(frozen=True)
class SafeClickOutcome:
    ok: bool
    executed: bool
    verified: bool
    requires_confirmation: bool
    reason: str
    before: CuaObservation | None = None
    after: CuaObservation | None = None


class CaptureAdapter:
    """Converts an injected UIA/DOM semantic source into a gate observation."""

    def __init__(self, gate: CuaSafetyGate, capture: Callable[[], object]):
        self._gate = gate
        self._capture = capture

    @classmethod
    def from_dom_harvest(cls, gate: CuaSafetyGate,
                         harvest: Callable[[], tuple[str, list[dict]]]):
        def capture() -> CaptureFrame:
            surface_id, items = harvest()
            return CaptureFrame(
                surface_id=str(surface_id),
                tree=_tree_from_dom(items),
            )
        return cls(gate, capture)

    def capture(self) -> CuaObservation:
        raw = self._capture()
        surface_id = str(getattr(raw, "surface_id", "") or "").strip()
        tree = getattr(raw, "tree", None)
        privacy = str(getattr(raw, "privacy", "normal") or "normal")
        if not isinstance(tree, ScreenElementTree):
            raise TypeError("capture adapter membutuhkan ScreenElementTree")
        return self._gate.observe(surface_id=surface_id, tree=tree, privacy=privacy)


def _tree_from_dom(items: list[dict]) -> ScreenElementTree:
    tree = ScreenElementTree()
    for element in elements_from_harvest(list(items or [])):
        tree.add(element)
    return tree


class SafeClickPlan:
    """Executes one non-sensitive semantic left click and verifies recapture."""

    def __init__(self, gate: CuaSafetyGate, capture: CaptureAdapter,
                 click_rect: Callable[[tuple[int, int, int, int]], None]):
        self._gate = gate
        self._capture = capture
        self._click_rect = click_rect

    def execute(self, ref: SemanticTargetRef, *, button: str = "left") -> SafeClickOutcome:
        if str(button).casefold() != "left":
            return SafeClickOutcome(False, False, False, False,
                                    "safe click hanya mengizinkan button left")
        try:
            decision = self._gate.evaluate(ref, action="click")
        except Exception as exc:  # gate is the fail-closed authority
            return SafeClickOutcome(False, False, False, False, str(exc))
        if not decision.allowed:
            return SafeClickOutcome(False, False, False, False, decision.reason)
        if decision.requires_confirmation:
            return SafeClickOutcome(False, False, False, True, decision.reason)

        before = self._observation(ref.observation_id)
        try:
            self._click_rect(ref.rect)
        except Exception as exc:  # no retry: action might have landed
            self._gate.invalidate(ref.observation_id)
            return SafeClickOutcome(False, True, False, False,
                                    f"click dieksekusi tetapi executor gagal: {type(exc).__name__}",
                                    before=before)
        self._gate.invalidate(ref.observation_id)
        try:
            after = self._capture.capture()
        except Exception as exc:
            return SafeClickOutcome(False, True, False, False,
                                    f"click terkirim; recapture gagal: {type(exc).__name__}",
                                    before=before)
        verified = self._gate.verify_recapture(before, after)
        return SafeClickOutcome(
            verified, True, verified, False,
            "click semantik terverifikasi" if verified else
            "click terkirim tetapi recapture tidak membuktikan surface yang sama",
            before=before, after=after,
        )

    def _observation(self, observation_id: str) -> CuaObservation:
        observation = self._gate._observations.get(observation_id)
        if observation is None:
            raise ValueError("observasi ref tidak ditemukan")
        return observation


__all__ = ["CaptureAdapter", "CaptureFrame", "SafeClickOutcome", "SafeClickPlan"]
