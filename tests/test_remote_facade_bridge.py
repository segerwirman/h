"""Phase 28 RED — mediated remote facade.

Facade lokal (Phase 27) diekspos ke remote HANYA sebagai proposal;
eksekusi tetap lokal via approval eksplisit (one-shot + TTL); remote tidak
pernah memanggil facade langsung; view remote metadata-only tanpa args.
"""
from __future__ import annotations


def _bridge(monkeypatch, *, now=1_800_000_000.0, ttl_s=300):
    import jarvis.core.remote_facade_bridge as rfb

    state = {"now": now}
    monkeypatch.setattr(rfb, "_now", lambda: state["now"])
    return rfb, state


def test_remote_can_only_propose_known_facades(monkeypatch):
    rfb, _state = _bridge(monkeypatch)
    bridge = rfb.RemoteFacadeBridge()

    result = bridge.propose("check_order_status", reference="ORD-123456")
    assert result["ok"] is True
    assert "proposal_id" in result

    # Deny-unknown: remote tidak bisa memanggil facade tak dikenal
    denied = bridge.propose("free_form_mission")
    assert denied["ok"] is False
    assert denied["reason"] == "facade_unknown"


def test_remote_view_is_metadata_only_without_args(monkeypatch):
    rfb, _state = _bridge(monkeypatch)
    bridge = rfb.RemoteFacadeBridge()
    proposed = bridge.propose("check_order_status",
                              reference="ORD-123456")
    view = bridge.remote_view(proposed["proposal_id"])
    assert view["facade_name"] == "check_order_status"
    assert view["status"] == "awaiting_approval"
    # Remote view TIDAK pernah berisi args (bisa berisi reference sensitif)
    for forbidden in ("reference", "ORD-", "args", "title", "start_ts"):
        assert forbidden not in view, forbidden


def test_remote_has_no_direct_invoke_authority(monkeypatch):
    rfb, _state = _bridge(monkeypatch)
    bridge = rfb.RemoteFacadeBridge()
    # Bridge tidak mengekspos invoke/execute — eksekusi hanya via approve
    assert not hasattr(bridge, "invoke")
    assert not hasattr(bridge, "execute")
    # Satu-satunya jalan eksekusi = approve (local) / reject
    public = {name for name in dir(bridge) if not name.startswith("_")}
    assert "approve" in public
    assert "reject" in public
    assert len(public & {"invoke", "execute", "run"}) == 0


def test_approval_is_local_and_executes_facade(monkeypatch):
    rfb, _state = _bridge(monkeypatch)
    bridge = rfb.RemoteFacadeBridge()
    proposed = bridge.propose("check_order_status",
                              reference="ORD-123456")
    pid = proposed["proposal_id"]

    # Sebelum approval → belum dieksekusi
    assert bridge.result(pid)["status"] == "awaiting_approval"
    # Approval lokal → eksekusi facade lokal
    approved = bridge.approve(pid)
    assert approved["ok"] is True
    outcome = bridge.result(pid)
    assert outcome["status"] == "done"
    assert outcome["steps"]["disclose_status"]["disclosed"] is True


def test_approval_is_one_shot_and_reject_blocks(monkeypatch):
    rfb, _state = _bridge(monkeypatch)
    bridge = rfb.RemoteFacadeBridge()
    pid = bridge.propose("check_order_status",
                         reference="ORD-123456")["proposal_id"]

    assert bridge.reject(pid) is True
    assert bridge.result(pid)["status"] == "rejected"
    assert bridge.approve(pid)["ok"] is False      # one-shot
    assert bridge.reject(pid) is False


def test_proposal_expires_after_ttl(monkeypatch):
    rfb, state = _bridge(monkeypatch, ttl_s=300)
    bridge = rfb.RemoteFacadeBridge()
    pid = bridge.propose("check_order_status",
                         reference="ORD-123456")["proposal_id"]
    state["now"] += 301
    result = bridge.approve(pid)
    assert result["ok"] is False
    assert result["reason"] == "proposal_expired"
    assert bridge.result(pid)["status"] == "expired"


def test_pending_list_is_metadata_only(monkeypatch):
    rfb, _state = _bridge(monkeypatch)
    bridge = rfb.RemoteFacadeBridge()
    bridge.propose("book_reservation", title="Hotel", start_ts=1_800_100_000,
                   duration_min=30, cancel_within_days=7)
    pending = bridge.pending()
    assert len(pending) == 1
    text = str(pending)
    for forbidden in ("Hotel", "1800100000", "cancel_within_days"):
        assert forbidden not in text, forbidden


def test_no_live_authority_via_static_contract(monkeypatch):
    from pathlib import Path

    source = Path(
        "jarvis/core/remote_facade_bridge.py").read_text(encoding="utf-8")
    for forbidden in ("import whatsapp", "requests", "socket", "http",
                      "subprocess", "selenium", "playwright", "write_bytes"):
        assert forbidden not in source, forbidden
