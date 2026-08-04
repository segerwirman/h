"""Phase WA5 — call memory & privacy.

Simpan HANYA ringkasan metadata dari sesi call: field allowlist ketat
(session_id, status, duration_s, turn_count) — tidak pernah transcript,
audio, path, atau payload. Opt-in via config; retention bounded (ring
buffer) + clear; PII/secret ditolak. In-memory only — tanpa file write.
"""
from __future__ import annotations

import re

MAX_ENTRIES = 50
_ALLOWED_FIELDS = ("session_id", "status", "duration_s", "turn_count")

_SECRET_MARKERS = (
    "password", "token", "api key", "secret", "kartu", "norek",
    "otp", "pin ", "passphrase", "credential",
)


def _memory_enabled() -> bool:
    try:
        from jarvis.core import config
        return bool(config.get("integrations.call.memory_enabled", False))
    except Exception:  # noqa: BLE001
        return False


def admit_summary(value: object) -> dict:
    """Admit hanya dict dengan field allowlist; tolak transcript/audio/dll."""
    if not isinstance(value, dict):
        return {"ok": False, "reason": "call_memory_summary_type_rejected"}
    if set(value) - set(_ALLOWED_FIELDS):
        return {"ok": False, "reason": "call_memory_allowlist_rejected"}
    required = {"session_id", "status", "duration_s", "turn_count"}
    if not required <= set(value):
        return {"ok": False, "reason": "call_memory_fields_missing"}
    return {"ok": True, "summary": {
        "session_id": str(value["session_id"]),
        "status": str(value["status"]),
        "duration_s": int(value["duration_s"]),
        "turn_count": int(value["turn_count"]),
    }}


_OPAQUE_ID_RE = re.compile(r"\A[0-9a-f]{32}\Z")


def _is_opaque_id(text: str) -> bool:
    """Hex 32-karakter kanonik — bentuk ``uuid.uuid4().hex`` yang dipakai
    ``CallSession``. Identitas mesin, tidak pernah memuat masukan user."""
    return bool(_OPAQUE_ID_RE.match(text))


def _looks_like_secret(text: str) -> bool:
    lowered = text.lower()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        return True
    if _is_opaque_id(text):
        # Temuan S-11: ~3,45% dari uuid4().hex kebetulan memuat 12+ digit
        # berurutan, sehingga heuristik nomor kartu di bawah menolak record
        # yang sah — dan record itu hilang tanpa pesan apa pun. Id opaque
        # dikecualikan dari heuristik DIGIT saja; penanda kata rahasia di
        # atas tetap berlaku, dan bentuk lain (mis. "4111111111111111")
        # tetap ditolak seperti semula.
        return False
    return bool(re.search(r"\d{12,19}", text))


class CallMemoryStore:
    """Ring buffer metadata call; opt-in; bounded; clearable; tanpa disk."""

    def __init__(self) -> None:
        self._entries: list[dict] = []

    def record(self, summary: dict) -> bool:
        if not _memory_enabled():
            return False
        admitted = admit_summary(summary)
        if not admitted.get("ok"):
            return False
        candidate = admitted["summary"]
        for field in candidate.values():
            if isinstance(field, str) and _looks_like_secret(field):
                return False
        self._entries.append(candidate)
        if len(self._entries) > MAX_ENTRIES:
            self._entries = self._entries[-MAX_ENTRIES:]   # evict tertua
        return True

    def list_summaries(self) -> list[dict]:
        return [dict(entry) for entry in self._entries]

    def count(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()


__all__ = ["CallMemoryStore", "admit_summary", "MAX_ENTRIES",
           "_ALLOWED_FIELDS"]
