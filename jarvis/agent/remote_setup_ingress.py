"""Fase 15S ingress: normalize a remote setup upload into a safe status payload.

Telegram (or any remote adapter) calls receive_setup_upload with the raw bytes.
This module only ever returns metadata/reason codes; secret bytes are staged
encrypted in the SetupQueue and never echoed back to the caller.
"""
from __future__ import annotations

from jarvis.agent.remote_setup import SetupQueue, attachment_allowed, validate_setup_payload


def receive_setup_upload(queue: SetupQueue, *, provider: str, requester: str,
                         paired: bool, filename: str, payload: bytes) -> dict:
    """Stage a paired remote setup upload; return a safe status dict only."""
    requester_id = str(requester or "").strip()
    if (not requester_id or not isinstance(paired, bool)
            or not isinstance(payload, bytes)):
        return {"accepted": False, "status": "rejected", "reason": "setup_context_rejected"}
    if not paired:
        return {"accepted": False, "status": "rejected", "reason": "setup_actor_not_paired"}
    allowed, reason = attachment_allowed(filename, len(payload))
    if not allowed:
        return {"accepted": False, "status": "rejected", "reason": reason}
    ok, _kind, reason = validate_setup_payload(provider, payload)
    if not ok:
        return {"accepted": False, "status": "rejected", "reason": reason}
    try:
        request = queue.stage(
            provider=provider, requester=requester_id, filename=filename, payload=payload)
    except ValueError as exc:
        return {"accepted": False, "status": "rejected", "reason": str(exc)}
    return {
        "accepted": True,
        "status": "awaiting_desktop_approval",
        "request_id": request.id,
        "provider": request.provider,
        "hash_suffix": request.hash_suffix,
    }


__all__ = ["receive_setup_upload"]
