"""Local-first operations facade over safe management DTOs."""
from __future__ import annotations

from pathlib import Path

from jarvis.agent import management_surface
from jarvis.agent.approval import ApprovalStore
from jarvis.agent.paths import data_dir
from jarvis.gateway.authz import GatewayAuthz
from jarvis.gateway.manager import GatewayManager
from jarvis.ops import audit_log, rbac


class OpsAPI:
    """Local-only operations facade; all returns remain secret and payload free."""

    def __init__(self, audit_path: Path | None = None, *,
                 approvals_path: Path | None = None,
                 authz: GatewayAuthz | None = None,
                 manager: GatewayManager | None = None):
        self._audit = audit_log.AuditLog(audit_path or data_dir() / "ops_audit.sqlite")
        self._approvals = ApprovalStore(approvals_path or data_dir() / "approvals.sqlite")
        self._authz = authz or GatewayAuthz()
        self._manager = manager

    def _gateway_manager(self) -> GatewayManager:
        if self._manager is None:
            from jarvis.gateway.runtime import telegram_runtime
            self._manager = telegram_runtime().manager
        return self._manager

    def snapshot(self, role: str) -> dict | None:
        if not rbac.authorize(role, "snapshot.read"):
            return None
        return management_surface.snapshot()

    def audit(self, role: str, action: str, *, actor_id: str) -> dict | None:
        if not rbac.authorize(role, action):
            return None
        event = audit_log.create(role, action, actor_id)
        self._audit.append(event)
        return event.safe_dict()

    def recent_audit(self, role: str, limit: int = 50) -> list[dict] | None:
        if not rbac.authorize(role, "audit.read"):
            return None
        return [item.safe_dict() for item in self._audit.recent(limit)]

    def gateway_overview(self, role: str) -> dict | None:
        if not rbac.authorize(role, "gateway.read"):
            return None
        try:
            health = self._gateway_manager().health()
        except Exception:  # noqa: BLE001
            health = {}
        try:
            from jarvis.integrations import telegram_control
            state = telegram_control.status()
            telegram = {key: state.get(key) for key in ("state", "configured", "running")}
        except Exception:  # noqa: BLE001
            telegram = {"state": "unknown", "configured": False, "running": False}
        return {"health": health, "telegram": telegram}

    def gateway_pairs(self, role: str) -> list[dict] | None:
        if not rbac.authorize(role, "gateway.read"):
            return None
        return self._authz.list_pairs()

    def revoke_gateway_pair(self, role: str, platform: str, actor_hash: str, *,
                            actor_id: str) -> bool:
        if not rbac.authorize(role, "gateway.revoke"):
            return False
        if not self._authz.revoke_hash(platform, actor_hash, revoked_by=actor_id):
            return False
        self.audit(role, "gateway.revoke", actor_id=actor_id)
        return True

    def pending_approvals(self, role: str, limit: int = 100) -> list[dict] | None:
        if not rbac.authorize(role, "approval.read"):
            return None
        return [item.safe_dict() for item in self._approvals.pending(limit)]

    def resolve_approval(self, role: str, request_id: str, *, approved: bool,
                         actor_id: str) -> dict | None:
        action = "approval.approve" if approved else "approval.deny"
        if not rbac.authorize(role, action):
            return None
        try:
            item = self._approvals.resolve(request_id, approved=approved)
        except KeyError:
            return None
        self.audit(role, action, actor_id=actor_id)
        return item.safe_dict()

    def restart_gateway(self, role: str, platform: str, *, actor_id: str) -> bool:
        if not rbac.authorize(role, "gateway.restart"):
            return False
        name = str(platform or "").strip().lower()
        if not name:
            return False
        try:
            manager = self._gateway_manager()
            manager.stop(name)
            started = manager.start(name)
        except Exception:  # noqa: BLE001
            return False
        if not started:
            return False
        return bool(self.audit(role, "gateway.restart", actor_id=actor_id))


API = OpsAPI()
