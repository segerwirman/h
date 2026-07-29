"""Framework maturity Phase 13 — local ops roles are least privilege."""
from __future__ import annotations


def test_rbac_observer_tidak_boleh_mutasi_dan_admin_boleh():
    from jarvis.ops.rbac import authorize

    assert authorize("observer", "gateway.pair") is False
    assert authorize("local-admin", "gateway.pair") is True


def test_rbac_unknown_role_fail_closed():
    from jarvis.ops.rbac import authorize

    assert authorize("unknown", "snapshot.read") is False
    assert authorize("local-admin", "unknown.action") is False
