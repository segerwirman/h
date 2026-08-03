"""Phase 28 — mediated remote facade.

Facade lokal (Phase 27) diekspos ke remote HANYA sebagai proposal:
- remote hanya bisa `propose(facade_name, **args)` — deny-unknown;
- args disimpan LOKAL; view remote metadata-only (tanpa args);
- eksekusi hanya via `approve()`/`reject()` LOKAL, one-shot + TTL;
- bridge TIDAK mengekspos invoke/execute — remote tidak pernah memanggil
  facade langsung; tanpa provider/network/file.
"""
from __future__ import annotations

import time

from jarvis.core.local_facades import LocalFacadeRegistry, default_facades

DEFAULT_TTL_S = 300


def _now() -> float:
    return time.monotonic()


class RemoteFacadeBridge:
    """Mediasi remote → facade lokal; eksekusi lokal via approval."""

    def __init__(self, registry: LocalFacadeRegistry | None = None,
                 ttl_s: int = DEFAULT_TTL_S) -> None:
        self._registry = registry if registry is not None \
            else default_facades()
        self._ttl_s = int(ttl_s)
        self._proposals: dict[int, dict] = {}
        self._next_id: int = 1

    # ── remote side ──────────────────────────────────────────────────────────
    def propose(self, facade_name: str, **args: object) -> dict:
        """Remote mengusulkan facade; deny-unknown; args disimpan lokal."""
        if not self._registry.steps(facade_name):
            return {"ok": False, "reason": "facade_unknown"}
        proposal_id = self._next_id
        self._next_id += 1
        self._proposals[proposal_id] = {
            "facade_name": facade_name,
            "args": dict(args),
            "status": "awaiting_approval",
            "created": _now(),
            "outcome": None,
        }
        return {"ok": True, "proposal_id": proposal_id}

    def remote_view(self, proposal_id: int) -> dict:
        """View yang boleh dilihat remote — metadata-only, TANPA args."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return {"ok": False, "reason": "proposal_unknown"}
        return {
            "proposal_id": proposal_id,
            "facade_name": proposal["facade_name"],
            "status": proposal["status"],
        }

    def pending(self) -> list[dict]:
        """Daftar proposal — metadata-only (tanpa args)."""
        return [self.remote_view(pid) for pid in self._proposals]

    # ── local approval side ──────────────────────────────────────────────────
    def _expired(self, proposal: dict) -> bool:
        return _now() - proposal["created"] > self._ttl_s

    def approve(self, proposal_id: int) -> dict:
        """Approval LOKAL → eksekusi facade; one-shot; TTL check."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return {"ok": False, "reason": "proposal_unknown"}
        if proposal["status"] != "awaiting_approval":
            return {"ok": False, "reason": "proposal_not_awaiting"}
        if self._expired(proposal):
            proposal["status"] = "expired"
            return {"ok": False, "reason": "proposal_expired"}
        outcome = self._registry.invoke(proposal["facade_name"],
                                        **proposal["args"])
        proposal["outcome"] = outcome
        proposal["status"] = "done" if outcome.get("ok") else "failed"
        return {"ok": True, "proposal_id": proposal_id,
                "status": proposal["status"]}

    def reject(self, proposal_id: int) -> bool:
        """Reject LOKAL; one-shot."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None or proposal["status"] != "awaiting_approval":
            return False
        proposal["status"] = "rejected"
        return True

    def result(self, proposal_id: int) -> dict:
        """Hasil proposal — metadata-only; outcome penuh hanya via approve."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return {"ok": False, "reason": "proposal_unknown"}
        return {
            "proposal_id": proposal_id,
            "facade_name": proposal["facade_name"],
            "status": proposal["status"],
            "steps": (proposal["outcome"] or {}).get("steps"),
        }


__all__ = ["RemoteFacadeBridge", "DEFAULT_TTL_S"]
