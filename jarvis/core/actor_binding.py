"""28-lanjutan — actor binding.

Paired remote actor identity binding: actor terdaftar (duplicate ditolak,
bounded, non-secret) → proposal di-bind ke actor (one-shot); approval
side memverifikasi kepemilikan. Larangan eksplisit payload remote:
UIA refs/transcript/audio/path/screenshot/coordinate/raw_html/cookie/
header/ocr — TIDAK PERNAH diterima dari/dikirim ke remote. Murni lokal;
tanpa provider/network/file.
"""
from __future__ import annotations

MAX_ACTOR_ID_LEN = 64
MAX_DISPLAY_LEN = 40

_SECRET_MARKERS = (
    "password", "token", "api_key", "otp", "pin", "cvv", "transfer",
    "rekening", "kartu kredit", "passphrase",
)

# Jenis payload yang TIDAK PERNAH boleh masuk/keluar remote
_FORBIDDEN_PAYLOAD_FIELDS = (
    "uia_ref", "uia_reference", "transcript", "audio", "path", "screenshot",
    "coordinate", "raw_html", "cookie", "header", "ocr",
)


def _clean_text(value: str, max_len: int) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= max_len:
        return False
    lowered = value.lower()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        return False
    return True


class ActorBinding:
    """Register actor + bind proposal + payload guard."""

    def __init__(self) -> None:
        self._actors: dict[str, str] = {}        # actor_id → display_name
        self._proposal_actor: dict[str, str] = {}  # proposal_id → actor_id

    # ── identitas ────────────────────────────────────────────────────────────
    def register(self, actor_id: str, display_name: str) -> bool:
        if actor_id in self._actors:
            return False                        # duplicate
        if not _clean_text(actor_id, MAX_ACTOR_ID_LEN):
            return False
        if not _clean_text(display_name, MAX_DISPLAY_LEN):
            return False
        self._actors[actor_id] = display_name
        return True

    def known_actors(self) -> list[dict]:
        """Metadata-only — tanpa nilai sensitif."""
        return [{"actor_id": actor_id, "display_name": name}
                for actor_id, name in sorted(self._actors.items())]

    # ── binding proposal → actor ─────────────────────────────────────────────
    def bind_proposal(self, proposal_id: str, actor_id: str) -> bool:
        if proposal_id in self._proposal_actor:
            return False                        # one-shot
        if actor_id not in self._actors:
            return False                        # actor tak dikenal
        self._proposal_actor[proposal_id] = actor_id
        return True

    def bound_actor(self, proposal_id: str) -> str | None:
        return self._proposal_actor.get(proposal_id)

    def actor_owns(self, proposal_id: str, actor_id: str) -> bool:
        return self._proposal_actor.get(proposal_id) == actor_id

    # ── payload guard ────────────────────────────────────────────────────────
    def check_payload(self, payload: dict) -> dict:
        """Payload remote tidak boleh memuat jenis terlarang."""
        for field in payload:
            if field in _FORBIDDEN_PAYLOAD_FIELDS:
                return {"ok": False, "reason": "actor_payload_forbidden"}
        return {"ok": True, "payload": payload}


__all__ = ["ActorBinding", "_FORBIDDEN_PAYLOAD_FIELDS"]
