"""WA5-lanjutan — durable semantic memory & recall.

Facts yang disetujui (non-secret) → memori durable opt-in: propose →
approval/reject LOKAL one-shot → tersimpan; filter secret di propose
(secret TIDAK PERNAH masuk memory); recall by query; retention bounded
(MAX_FACTS ring buffer — tertua tergeser); clear(). In-memory, tanpa
file write/provider/network — tanpa transcript/audio.
"""
from __future__ import annotations

import uuid

MAX_FACTS = 50

_SECRET_MARKERS = (
    "password", "token", "api_key", "apikey", "otp", "pin", "cvv",
    "transfer", "rekening", "kartu kredit", "passphrase",
)


def _contains_secret(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


class DurableMemory:
    """Memori fakta durable; opt-in; approval lokal; bounded."""

    def __init__(self) -> None:
        self._enabled = False
        self._facts: list[dict] = []          # ring buffer, tertua di depan
        self._pending: dict[str, dict] = {}

    # ── opt-in ───────────────────────────────────────────────────────────────
    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)

    def enabled(self) -> bool:
        return self._enabled

    # ── tulis (lokal; approval wajib) ────────────────────────────────────────
    def propose(self, fact: str) -> str | None:
        """Usulkan fakta — ditolak kalau memory disabled / mengandung secret."""
        if not self._enabled:
            return None
        if _contains_secret(fact):
            return None                     # secret tidak pernah masuk
        pid = uuid.uuid4().hex
        self._pending[pid] = {"fact": fact}
        return pid

    def approve(self, proposal_id: str) -> bool:
        """Approval LOKAL — one-shot; faktanya tersimpan di ring buffer."""
        if proposal_id not in self._pending:
            return False
        fact = self._pending.pop(proposal_id)["fact"]
        self._facts.append({"fact": fact})
        if len(self._facts) > MAX_FACTS:
            self._facts.pop(0)              # tertua tergeser
        return True

    def reject(self, proposal_id: str) -> bool:
        """Reject LOKAL — one-shot; tidak tersimpan."""
        if proposal_id not in self._pending:
            return False
        del self._pending[proposal_id]
        return True

    def pending_ids(self) -> list[str]:
        return list(self._pending)

    # ── baca ─────────────────────────────────────────────────────────────────
    def recall(self, query: str | None = None) -> list[str]:
        """Recall by query (token substring); tanpa query → semua."""
        if not query:
            return [entry["fact"] for entry in self._facts]
        lowered = query.lower()
        return [entry["fact"] for entry in self._facts
                if lowered in entry["fact"].lower()]

    def clear(self) -> bool:
        self._facts.clear()
        self._pending.clear()
        return True


__all__ = ["DurableMemory", "MAX_FACTS", "_contains_secret"]
