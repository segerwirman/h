"""Resolver L0/L1 konservatif untuk teks dan suara.

Tidak mengklasifikasikan percakapan. Ia hanya menjawab apakah aksi lokal dapat
aman dieksekusi tanpa LLM; selain itu selalu fallthrough.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from jarvis.core import app_registry, config
from jarvis.core.action_registry import Action, ActionRegistry, default_registry


@dataclass(frozen=True)
class ClarifyNeeded:
    topic: str
    question: str
    options: tuple[str, ...] = ()
    kind: str = "action"


@dataclass(frozen=True)
class FallthroughToLLM:
    reason: str = "not_unambiguous"


Resolution = Action | ClarifyNeeded | FallthroughToLLM

_IMPERATIVES = frozenset({
    "buka", "bukakan", "jalankan", "putar", "tutup", "close", "open",
    "launch", "start", "play", "turn", "set", "naikkan", "turunkan",
    "matikan", "nyalakan", "mute", "lock", "screenshot", "capture",
})
_QUESTION_MARKERS = (
    "gimana", "bagaimana", "kenapa", "apakah", "bisa nggak", "bisa gak",
    "menurutmu", "kira kira", "kira-kira", "sih", " dong", "ya?",
)
_VAGUE = frozenset({"semua", "semuanya", "all", "aplikasi", "app", "program"})
_PREFIX = re.compile(r"^/(?P<verb>open|close|panel)\s+(?P<target>.+)$", re.I)


def _known_sites() -> set[str]:
    return {app_registry.normalize(k) for k in (config.section("router.known_sites") or {})}


def _clean(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def _l0(text: str, registry: ActionRegistry) -> Resolution | None:
    m = _PREFIX.match(text)
    if not m:
        return None
    verb, entity = m.group("verb").lower(), app_registry.normalize(m.group("target"))
    if not entity:
        return FallthroughToLLM("empty_explicit_target")
    actions = registry.lookup(entity)
    desired = {"open": "open", "close": "close", "panel": "toggle"}[verb]
    hits = [a for a in actions if a.verb == desired or (verb == "panel" and a.kind == "panel")]
    if len(hits) == 1:
        hit = hits[0]
        return Action(hit.kind, hit.target, hit.verb, hit.args, 1.0, "L0")
    return ClarifyNeeded(entity, f"Target '{entity}' tidak ditemukan secara tunggal.", (), "explicit_target") \
        if len(hits) > 1 else FallthroughToLLM("unknown_explicit_target")


def _palette(text: str, registry: ActionRegistry) -> Resolution:
    # Palette is deterministic selection, yet preserve an explicit action shape.
    parsed = _l0("/" + _clean(text), registry)
    if isinstance(parsed, Action):
        return parsed
    return FallthroughToLLM("palette_missing_action")


def _l1(text: str, registry: ActionRegistry) -> Resolution:
    normalized = _clean(text).lower()
    words = normalized.split()
    if not words or len(words) > 8:
        return FallthroughToLLM("length_or_empty")
    if words[0] not in _IMPERATIVES:
        return FallthroughToLLM("not_imperative")
    if "?" in normalized or any(marker in normalized for marker in _QUESTION_MARKERS):
        return FallthroughToLLM("conversation_marker")

    # Multiword verbs: turn up / turn down; otherwise drop imperative first word.
    entity_words = words[2:] if len(words) >= 3 and words[:2] in (["turn", "up"], ["turn", "down"]) else words[1:]
    entity = app_registry.normalize(" ".join(entity_words))
    if not entity or entity in _VAGUE:
        return ClarifyNeeded(entity, "Target aksi mana yang Anda maksud?", (), "close_target") \
            if words[0] in {"tutup", "close"} else FallthroughToLLM("vague_target")
    # System alias may include verb ("naikkan volume"), unlike entities.
    actions = registry.lookup(entity) or registry.lookup(normalized)
    if not actions:
        return FallthroughToLLM("lookup_miss")

    verb = words[0]
    wanted = "close" if verb in {"tutup", "close"} else "open"
    if verb in {"naikkan", "turunkan", "matikan", "nyalakan", "mute", "lock", "screenshot", "capture", "set", "turn"}:
        wanted = "set"
    candidates = [a for a in actions if a.verb == wanted]
    # "buka kamera" is panel open, while direct panel icon uses toggle itself.
    if wanted == "open":
        candidates = [a for a in actions if a.verb in {"open", "toggle"}]
    # Panel Spotify is an external-app launcher. App target wins over a panel
    # with the same semantic target; it is not ambiguity requiring a question.
    if wanted == "open" and any(a.kind == "app" for a in candidates):
        candidates = [a for a in candidates if a.kind == "app"]
    targets = {(a.kind, a.target) for a in candidates}
    if len(targets) != 1:
        return FallthroughToLLM("verb_or_lookup_ambiguous")
    choice = candidates[0]

    # Preserve PROMPT B invariant: unknown preference app+known-site asks once.
    app_entity = app_registry.normalize(choice.target)
    if choice.kind == "app" and app_entity in _known_sites() and app_registry.preference_for(app_entity) is None:
        return ClarifyNeeded(app_entity, f"Aplikasi {choice.args.get('app', app_entity)} atau buka di browser?",
                             ("aplikasi", "browser"), "app_or_site")
    if choice.kind == "app" and app_entity in _known_sites() and app_registry.preference_for(app_entity) == "web":
        return FallthroughToLLM("learned_web_preference")
    return Action(choice.kind, choice.target, choice.verb, choice.args, 0.90, "L1")


def resolve(text: str, *, source: str, registry: ActionRegistry | None = None) -> Resolution:
    """Resolve one utterance. Default is L2 fallthrough, never a guess."""
    registry = registry or default_registry()
    cleaned = _clean(text)
    if source == "palette":
        return _palette(cleaned, registry)
    explicit = _l0(cleaned, registry)
    if explicit is not None:
        return explicit
    return _l1(cleaned, registry)


__all__ = ["Action", "ClarifyNeeded", "FallthroughToLLM", "Resolution", "resolve"]
