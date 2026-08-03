"""27-lanjutan — facade capability enum & permanent reject rules.

Enum facade untuk capability proven; deny-first pipeline:
1) capability dikenal? (selain itu → facade_capability_unknown)
2) args bersih dari PERMANENT rejects (coordinate/selector/key/path/
   url/screenshot/raw dispatch/login/payment → facade_permanent_reject)?
3) field sesuai allowlist policy capability (→ facade_policy_field_rejected)?
Per-capability confirmation flag tetap berlaku. Murni lokal; tanpa
provider/network/file.
"""
from __future__ import annotations

from enum import Enum

_FIXED_REASONS = {
    "facade_capability_unknown",
    "facade_permanent_reject",
    "facade_policy_field_rejected",
}

# Pola field yang TIDAK PERNAH diizinkan di arg facade apa pun
_PERMANENT_REJECT_FIELDS = (
    "coordinate", "x", "y", "selector", "key", "path", "url", "screenshot",
    "raw_dispatch", "login", "payment",
)

# Policy per capability: (allowlist fields, requires_confirmation)
_CAPABILITY_POLICY: dict[str, tuple] = {
    "CONTENT_TITLE": (("project_title",), True),
    "CONTENT_REORDER": (("source_element_id", "destination_element_id"), True),
    "FOCUS_MODE": (("enabled",), False),
    "BROWSER_MEDIA": (("action",), False),
    "TIMER": (("duration_s",), False),
    "CALL_START": (("contact", "objective"), True),
    "CALL_STATUS": ((), False),
    "CALL_HANGUP": ((), True),
}


class FacadeCapability(str, Enum):
    """Capability proven yang boleh di-facade-kan (fixed set)."""

    CONTENT_TITLE = "CONTENT_TITLE"
    CONTENT_REORDER = "CONTENT_REORDER"
    FOCUS_MODE = "FOCUS_MODE"
    BROWSER_MEDIA = "BROWSER_MEDIA"
    TIMER = "TIMER"
    CALL_START = "CALL_START"
    CALL_STATUS = "CALL_STATUS"
    CALL_HANGUP = "CALL_HANGUP"


class CapabilityPolicy:
    """Deny-first gate: capability + permanent rejects + field allowlist."""

    def admit_capability(self, name: str) -> dict:
        if name not in _CAPABILITY_POLICY:
            return {"ok": False, "reason": "facade_capability_unknown"}
        return {"ok": True, "capability": name}

    def check_rejects(self, args: dict) -> dict:
        """Permanent rejects — apa pun isi args, field terlarang → reject."""
        for field in args:
            if field in _PERMANENT_REJECT_FIELDS:
                return {"ok": False, "reason": "facade_permanent_reject"}
        return {"ok": True, "args": args}

    def verify_policy(self, capability: str, args: dict) -> dict:
        """Pipeline lengkap: capability → rejects → field allowlist."""
        admitted = self.admit_capability(capability)
        if not admitted.get("ok"):
            return admitted
        clean = self.check_rejects(args)
        if not clean.get("ok"):
            return clean
        allowlist, _confirmation = _CAPABILITY_POLICY[capability]
        for field in args:
            if field not in allowlist:
                return {"ok": False, "reason": "facade_policy_field_rejected"}
        return {"ok": True, "capability": capability}

    def requires_confirmation(self, capability: str) -> bool:
        if capability not in _CAPABILITY_POLICY:
            return False
        return _CAPABILITY_POLICY[capability][1]


__all__ = ["FacadeCapability", "CapabilityPolicy", "_FIXED_REASONS",
           "_CAPABILITY_POLICY", "_PERMANENT_REJECT_FIELDS"]
