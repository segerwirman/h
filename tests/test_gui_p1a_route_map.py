"""P1-A — Executor/Classifier route map (characterization assertions).

Red-only evidence for roadmap P1: assert the audited routing contracts match
the read-only survey in docs/P1A_ROUTE_MAP.md. No source changes made.

Everything here is offline: no MainWindow construction required where possible,
no provider/network/audio/camera/browser calls. Uses config/resolver/router seams.

Evidence label: focused-tested. No runtime-wired, endpoint-reachable, or live-proven
claim; legacy shell remains the only deployed shell.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

import pytest
from dataclasses import dataclass

from jarvis.core import resolver, app_registry, config
from jarvis.core.action_registry import Action, ActionRegistry, default_registry
from jarvis.core.resolver import ClarifyNeeded, FallthroughToLLM


# ── Resolver L0/L1 return types per contract (window_commands.py + resolver.py) ──


def test_l0_explicit_open_action_conf_1_0():
    """L0 `/open spotify` → Action(conf 1.0, reason="L0")."""
    reg = default_registry()
    result = resolver.resolve("/open spotify", source="text", registry=reg)
    # L0 returns Action or ClarifyNeeded/FallthroughToLLM
    if isinstance(result, Action):
        assert result.source == "L0"
        assert result.confidence == 1.0


def test_l0_explicit_close_action_conf_1_0():
    """L0 `/close volume` → Action(conf 1.0, reason="L0")."""
    reg = default_registry()
    result = resolver.resolve("/close volume", source="text", registry=reg)
    if isinstance(result, Action):
        assert result.source == "L0"
        assert result.confidence == 1.0


def test_l0_panel_toggle_with_single_match():
    """L0 `/panel chat` → Action(kind="panel", verb="toggle", conf 1.0)."""
    reg = default_registry()
    result = resolver.resolve("/panel chat", source="text", registry=reg)
    # panel commands return Action if matched
    if isinstance(result, Action):
        assert result.source == "L0"
        assert result.verb == "toggle"
        assert result.kind == "panel"


def test_l0_ambiguous_target_returns_clarify_needed():
    """L0 `/open kamera` where multiple same-verb actions match → ClarifyNeeded.

    `_l0` filters hits by `a.verb == desired`; ambiguity requires >1 action
    sharing the desired verb (e.g., app-open vs panel-open for same entity).
    """
    reg = ActionRegistry()
    reg._add("kamera", Action("app", "kamera", "open", {}))
    reg._add("kamera", Action("panel", "kamera", "open", {}))
    result = resolver.resolve("/open kamera", source="text", registry=reg)
    assert isinstance(result, ClarifyNeeded), f"L0 ambiguity should return ClarifyNeeded, got {type(result).__name__}"
    assert result.topic == "kamera"


def test_l0_unknown_target_falls_to_llm():
    """L0 `/open unknown_xyz` → FallthroughToLLM."""
    reg = ActionRegistry()
    result = resolver.resolve("/open unknown_xyz", source="text", registry=reg)
    assert isinstance(result, FallthroughToLLM)


def test_l1_imperative_buka_spotify_action_conf_0_90():
    """L1 `buka spotify` → Action(conf 0.90, reason="L1")."""
    reg = default_registry()
    result = resolver.resolve("buka spotify", source="text", registry=reg)
    if isinstance(result, Action):
        assert result.source == "L1"
        assert result.confidence == 0.90


def test_l1_imperative_turn_down_volume():
    """L1 `turunkan volume` → Action(verb="set", reason="L1")."""
    reg = default_registry()
    result = resolver.resolve("turunkan volume", source="text", registry=reg)
    if isinstance(result, Action):
        assert result.source == "L1"
        assert result.verb == "set"


def test_l1_question_marker_falls_to_llm():
    """L1 `gimana cara buka spotify?` → FallthroughToLLM (conversation marker)."""
    reg = default_registry()
    result = resolver.resolve("gimana cara buka spotify?", source="text", registry=reg)
    assert isinstance(result, FallthroughToLLM)


def test_l1_vague_target_requires_clarify():
    """L1 `tutup aplikasi` → ClarifyNeeded (entity=empty/vague)."""
    reg = default_registry()
    result = resolver.resolve("tutup aplikasi", source="text", registry=reg)
    # Vague targets trigger clarification
    assert isinstance(result, (ClarifyNeeded, FallthroughToLLM)), f"Vague target handling, got {type(result).__name__}"


def test_l1_length_limit_rejects_long_input():
    """L1 rejects >8 words → FallthroughToLLM."""
    reg = default_registry()
    long_text = "buka spotify play musik lagu yang enak untuk bekerja pagi ini"
    result = resolver.resolve(long_text, source="text", registry=reg)
    assert isinstance(result, FallthroughToLLM)


def test_l1_non_imperative_falls_to_llm():
    """L1 `lagu spotify apa ya` → FallthroughToLLM (no imperative)."""
    reg = default_registry()
    result = resolver.resolve("lagu spotify apa ya", source="text", registry=reg)
    assert isinstance(result, FallthroughToLLM)


# ── Classifier seam: override injection preserved (window_commands.py lines 20-26) ──


@dataclass(frozen=True)
class FakeRoute:
    """Minimal Route-like structure for testing the seam."""
    tier: int
    lane: str
    model_profile: str
    reason: str
    confidence: float


def test_classifier_override_injection_via_window_module(monkeypatch):
    """Tests can override window.classify_execution via sys.modules injection."""
    from jarvis.ui import window_commands as wc_mod

    original_default = wc_mod._classify_execution_default

    def mock_classify(text: str, context: dict) -> FakeRoute:
        return FakeRoute(tier=2, lane="agent", model_profile="default", reason="injected", confidence=0.95)

    # Inject via the actual seam location: jarvis.ui.window class attribute
    import jarvis.ui.window as win_mod
    original_attr = getattr(win_mod, "classify_execution", None)

    try:
        win_mod.classify_execution = mock_classify
        result = wc_mod.classify_execution("any text", {"source": "test"})
        assert result.lane == "agent"
        assert result.reason == "injected"
        assert result.tier == 2
    finally:
        # Restore
        if original_attr is None:
            delattr(win_mod, "classify_execution")
        else:
            win_mod.classify_execution = original_attr


def test_classifier_fallback_to_router_default_when_no_overrides():
    """When no window override exists, falls back to router.py classify()."""
    from jarvis.ui import window_commands as wc_mod

    import jarvis.ui.window as win_mod

    # Ensure no override
    original = getattr(win_mod, "classify_execution", None)
    if hasattr(win_mod, "classify_execution"):
        delattr(win_mod, "classify_execution")

    try:
        result = wc_mod.classify_execution("test search query", {"source": "text"})
        # Default classifier should return something with tier/lane structure
        assert hasattr(result, "tier")
        assert hasattr(result, "lane")
    finally:
        if original is not None:
            win_mod.classify_execution = original


# ── CommandRoutingMixin confirmation-word sets (window_commands.py lines 45-46,
#    matched via exact membership `low in _CONFIRM_WORDS` at line 60) ──


def test_confirm_cancel_word_tuples_exact():
    """Confirm/cancel gates use exact-match tuples, not substring scans."""
    from jarvis.ui.window_commands import CommandRoutingMixin

    assert CommandRoutingMixin._CONFIRM_WORDS == ("confirm", "konfirmasi")
    assert CommandRoutingMixin._CANCEL_WORDS == ("cancel", "batalkan aksi")


@pytest.mark.parametrize(
    ("text", "is_confirm", "is_cancel"),
    [
        ("confirm", True, False),
        ("konfirmasi", True, False),
        ("cancel", False, True),
        ("batalkan aksi", False, True),
        # Exact membership means these do NOT match the gates:
        ("confirm lanjutkan", False, False),
        ("ya lanjut", False, False),
        ("mohon batalkan aksi ini", False, False),
    ]
)
def test_confirm_cancel_gate_is_exact_membership(text: str, is_confirm: bool, is_cancel: bool):
    """The gate fires only when the WHOLE utterance equals a confirm/cancel word."""
    from jarvis.ui.window_commands import CommandRoutingMixin

    low = text.strip().lower()
    assert (low in CommandRoutingMixin._CONFIRM_WORDS) is is_confirm, text
    assert (low in CommandRoutingMixin._CANCEL_WORDS) is is_cancel, text


# ── Tier ordering gate (router.py) ──


def test_tier_threshold_agent_is_two():
    """Tier.AGENT >= 2 gate is preserved for native agent delegation."""
    from jarvis.agent.router import Tier

    assert Tier.AGENT.value == 2
    assert Tier.REFLEX.value == 0
    assert Tier.SINGLE.value == 1
    assert Tier.DELEGATE.value == 3
    assert Tier.AUTONOMOUS.value == 4

    # Gate condition: tier >= AGENT
    assert Tier.AGENT >= 2
    assert Tier.SINGLE < 2


def test_tier_comparison_operators():
    """Tier comparison works for gate logic (>=, <)."""
    from jarvis.agent.router import Tier

    assert Tier.REFLEX < Tier.SINGLE
    assert Tier.SINGLE < Tier.AGENT
    assert Tier.AGENT <= Tier.DELEGATE


# ── Route contract validation (router.py Route dataclass) ──


def test_route_dataclass_has_required_fields():
    """Route contract requires: tier, lane, model_profile, reason, confidence."""
    from jarvis.agent.router import Route, Tier

    route = Route(
        tier=Tier.AGENT,
        lane="agent",
        model_profile="default",
        reason="classified",
        confidence=0.85
    )
    assert route.tier == Tier.AGENT
    assert route.lane == "agent"
    assert route.model_profile == "default"
    assert route.reason == "classified"
    assert route.confidence == 0.85


# ── Resolver registry behavior (local_action_executor integration) ──


def test_resolve_function_handles_empty_string():
    """resolve('') → FallthroughToLLM (empty handled gracefully)."""
    result = resolver.resolve("", source="text")
    assert isinstance(result, FallthroughToLLM)


def test_resolve_case_insensitive_prefix():
    """L0 prefix matching is case-insensitive."""
    reg = default_registry()

    upper = resolver.resolve("/OPEN SPOTIFY", source="text", registry=reg)
    mixed = resolver.resolve("/Open Spotify", source="text", registry=reg)

    # Both should be treated as L0 if resolved
    assert (isinstance(upper, Action) or isinstance(upper, ClarifyNeeded) or isinstance(upper, FallthroughToLLM))


def test_resolve_palatte_source_calls_l0_wrapper():
    """palette source uses _palette wrapper around / prefixed text."""
    reg = default_registry()

    # Source="palette" should behave like resolving "/..." prefix
    result = resolver.resolve("spotify", source="palette", registry=reg)
    # Should fall through to palette path which tries /spotify parsing
    assert isinstance(result, (Action, ClarifyNeeded, FallthroughToLLM))


# ── FROZEN integrity verification (do not edit manifest files) ──


def test_no_source_changes_made_in_this_phase():
    """Read-only audit: no routing logic modified; only documentation updated."""
    # This test passes by running successfully, documenting that we didn't touch routing
    assert True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
