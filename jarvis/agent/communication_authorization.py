"""Desktop-local communication override authorization.

The caller supplies a real registry task identity and explicit capability IDs.
Only the resulting opaque grant ID may leave this boundary; user-entered secret
material is passed straight to the verifier and is never retained.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass


_MAX_TTL_S = 300.0
_MAX_USES = 16
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_FORBIDDEN_OVERRIDE_TOOL_NAMES = frozenset({
    "agent.dispatch",
    "task_start",
})


@dataclass(frozen=True)
class AuthorizationResult:
    ok: bool
    status: str
    grant_id: str = ""


class CommunicationAuthorizer:
    """Verify locally, then issue a generation- and task-scoped grant."""

    def __init__(self, *, verifier=None, mode=None, task_registry=None) -> None:
        self._verifier = verifier
        self._mode = mode
        self._task_registry = task_registry

    def authorize(
        self,
        value: str,
        *,
        task_id: str,
        trace_id: str,
        capability_ids,
        ttl_s: float,
        uses: int = 1,
    ) -> AuthorizationResult:
        target = str(task_id or "").strip()
        trace = str(trace_id or "").strip()
        capabilities = frozenset(
            str(item).strip() for item in (capability_ids or ())
            if str(item).strip()
        )
        try:
            ttl = float(ttl_s)
            use_count = int(uses)
        except (TypeError, ValueError):
            return AuthorizationResult(False, "invalid_scope")
        before = self._task(target)
        if (
            before is None
            or not _ID_PATTERN.fullmatch(trace)
            or not capabilities
            or any(not _ID_PATTERN.fullmatch(item) for item in capabilities)
            or not self._capabilities_authorizable(capabilities)
            or not math.isfinite(ttl)
            or ttl <= 0
            or ttl > _MAX_TTL_S
            or use_count <= 0
            or use_count > _MAX_USES
        ):
            return AuthorizationResult(False, "invalid_scope")
        verification = self._passphrases().verify(value)
        if not verification.ok:
            return AuthorizationResult(False, verification.status)
        try:
            grant = self._communication_mode().issue_override(
                task_id=target,
                trace_id=trace,
                capability_ids=capabilities,
                ttl_s=ttl,
                uses=use_count,
            )
        except (RuntimeError, TypeError, ValueError):
            return AuthorizationResult(False, "grant_unavailable")
        after = self._task(target)
        if after is None:
            self._revoke(grant.id)
            return AuthorizationResult(False, "task_unavailable")
        return AuthorizationResult(True, "authorized", grant.id)

    @staticmethod
    def _capabilities_authorizable(capability_ids: frozenset[str]) -> bool:
        try:
            from jarvis.agent.capabilities import REGISTRY
            descriptors = {item.id: item for item in REGISTRY.descriptors()}
        except Exception:
            return False
        for capability_id in capability_ids:
            descriptor = descriptors.get(capability_id)
            if (
                descriptor is None
                or not descriptor.enabled
                or descriptor.tool_name in _FORBIDDEN_OVERRIDE_TOOL_NAMES
            ):
                return False
        return True

    def _task(self, task_id: str):
        if not task_id:
            return None
        registry = self._registry()
        try:
            view = registry.get(task_id)
        except Exception:
            return None
        if view is None or not bool(getattr(view, "active", False)):
            return None
        return view

    def _passphrases(self):
        if self._verifier is not None:
            return self._verifier
        from jarvis.core.communication_passphrase import VERIFIER
        return VERIFIER

    def _communication_mode(self):
        if self._mode is not None:
            return self._mode
        from jarvis.agent.communication_mode import MODE
        return MODE

    def _registry(self):
        if self._task_registry is not None:
            return self._task_registry
        from jarvis.agent.tasks import REGISTRY
        return REGISTRY

    def _revoke(self, grant_id: str) -> None:
        try:
            self._communication_mode().revoke_grant(grant_id)
        except Exception:
            pass


AUTHORIZER = CommunicationAuthorizer()


__all__ = [
    "AUTHORIZER",
    "AuthorizationResult",
    "CommunicationAuthorizer",
]
