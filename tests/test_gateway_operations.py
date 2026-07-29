"""Local-only Gateway Operations control plane."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

_APP_REF: QApplication | None = None


def _app() -> QApplication:
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


def test_ops_api_resolves_approval_and_revokes_pseudonymous_pair(tmp_path):
    from jarvis.agent.approval import ApprovalStore
    from jarvis.gateway.authz import GatewayAuthz
    from jarvis.ops.api import OpsAPI

    approvals_path = tmp_path / "approvals.sqlite"
    request = ApprovalStore(approvals_path).request(
        "trace-private", "files.write", "approval_required")
    authz = GatewayAuthz(tmp_path / "gateway.sqlite")
    assert authz.pair("telegram", "raw-actor-private")
    service = OpsAPI(audit_path=tmp_path / "audit.sqlite",
                     approvals_path=approvals_path, authz=authz)

    pending = service.pending_approvals("observer")
    assert pending == [request.safe_dict()]
    assert "trace-private" not in repr(pending)
    pairs = service.gateway_pairs("observer")
    assert len(pairs) == 1 and "raw-actor-private" not in repr(pairs)

    assert service.resolve_approval("observer", request.id, approved=True,
                                    actor_id="desktop") is None
    resolved = service.resolve_approval("local-admin", request.id, approved=True,
                                        actor_id="desktop")
    assert resolved["state"] == "approved"

    revoked = service.revoke_gateway_pair("local-admin", "telegram",
                                           pairs[0]["actor_hash"], actor_id="desktop")
    assert revoked is True
    assert service.gateway_pairs("observer")[0]["state"] == "revoked"
    assert "raw-actor-private" not in repr(
        service.recent_audit("observer"))


class _FakeOps:
    def __init__(self):
        self.calls: list[tuple] = []

    def gateway_overview(self, _role):
        return {"health": {"telegram": {"state": "connected"}},
                "telegram": {"state": "running", "configured": True}}

    def pending_approvals(self, _role):
        return [{"id": "req-1", "trace_hash": "abc123", "capability": "files.write",
                 "reason": "approval_required", "state": "pending", "created_at": 0,
                 "resolved_at": None}]

    def gateway_pairs(self, _role):
        return [{"platform": "telegram", "actor_hash": "1234abcd", "state": "paired",
                 "paired_at": 0, "revoked_at": None}]

    def resolve_approval(self, role, request_id, *, approved, actor_id):
        self.calls.append(("resolve", role, request_id, approved, actor_id))
        return {"id": request_id, "state": "approved" if approved else "denied"}

    def revoke_gateway_pair(self, role, platform, actor_hash, *, actor_id):
        self.calls.append(("revoke", role, platform, actor_hash, actor_id))
        return True

    def restart_gateway(self, role, platform, *, actor_id):
        self.calls.append(("restart", role, platform, actor_id))
        return True


def test_gateway_operations_sheet_only_exposes_safe_metadata_and_local_actions():
    _app()
    from jarvis.ui.gateway_operations import GatewayOperationsSheet

    host = QWidget()
    ops = _FakeOps()
    sheet = GatewayOperationsSheet(host, ops=ops)

    assert "telegram: connected" in sheet._health.text().lower()
    assert sheet._approvals.count() == 1
    assert sheet._pairs.count() == 1
    assert "raw-actor" not in sheet._pairs.item(0).text()

    sheet._approvals.setCurrentRow(0)
    sheet._resolve_selected(True)
    sheet._pairs.setCurrentRow(0)
    sheet._revoke_selected()

    assert ops.calls == [
        ("resolve", "local-admin", "req-1", True, "desktop-ui"),
        ("revoke", "local-admin", "telegram", "1234abcd", "desktop-ui"),
    ]


def test_gateway_operations_restart_memanggil_manager_owned_ops(monkeypatch):
    _app()
    from jarvis.ui import gateway_operations

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(gateway_operations.threading, "Thread", ImmediateThread)
    ops = _FakeOps()
    host = QWidget()
    sheet = gateway_operations.GatewayOperationsSheet(host, ops=ops)

    sheet._restart_telegram()

    assert ("restart", "local-admin", "telegram", "desktop-ui") in ops.calls
