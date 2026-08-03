"""Phase 27 RED — named local facade.

Komposisi lokal yang dipanggil agent dengan nama eksplisit; setiap facade
= daftar FIXED langkah lokal (immutable), deny-unknown; tanpa authority
baru (hanya komposisi modul inti yang sudah ada).
"""
from __future__ import annotations


def _registry():
    import jarvis.core.local_facades as lf

    return lf.default_facades()


def test_unknown_facade_is_denied():
    reg = _registry()
    result = reg.invoke("free_form_mission")
    assert result["ok"] is False
    assert result["reason"] == "facade_unknown"


def test_check_order_status_composes_service_case():
    reg = _registry()
    result = reg.invoke("check_order_status", reference="ORD-123456")
    assert result["ok"] is True
    steps = result["steps"]
    assert steps["open_case"]["ok"] is True
    assert steps["disclose_status"]["disclosed"] is True


def test_book_reservation_composes_proposal_and_gate():
    reg = _registry()
    result = reg.invoke("book_reservation", title="Hotel Kamar 101",
                        start_ts=1_800_100_000, duration_min=30,
                        cancel_within_days=7)
    assert result["ok"] is True
    steps = result["steps"]
    assert steps["create_proposal"]["status"] == "approved"
    assert steps["commitment_gate"]["ok"] is True


def test_facade_steps_are_fixed_and_immutable():
    import jarvis.core.local_facades as lf

    reg = _registry()
    steps = reg.steps("check_order_status")
    assert isinstance(steps, tuple)          # fixed, tidak bisa diubah
    names = [name for name, _fn in steps]
    assert names == ["open_case", "disclose_status"]
    # Langkah tidak bisa diubah runtime
    try:
        steps[0] = ("hacked", lambda ctx, **kw: {"ok": True})
        changed = False
    except TypeError:
        changed = True
    assert changed


def test_failing_step_stops_facade_with_report():
    import jarvis.core.local_facades as lf

    reg = lf.LocalFacadeRegistry()
    reg.register("broken", (
        ("first", lambda ctx, **kw: {"ok": True}),
        ("second", lambda ctx, **kw: {"ok": False,
                                      "reason": "facade_step_failed"}),
    ))
    result = reg.invoke("broken")
    assert result["ok"] is False
    assert "first" in result["steps"]
    assert result["steps"]["second"]["ok"] is False


def test_facade_rejects_secret_inputs():
    reg = _registry()
    result = reg.invoke("check_order_status", reference="password123")
    assert result["ok"] is False
    assert result["steps"]["open_case"]["ok"] is False


def test_facade_result_is_metadata_only():
    reg = _registry()
    result = reg.invoke("check_order_status", reference="ORD-123456")
    text = str(result)
    for forbidden in ("password", "token=", "api_key", "411111"):
        assert forbidden not in text, forbidden


def test_start_countdown_facade_composes_timer(monkeypatch):
    import jarvis.core.countdown_timer as ct
    import jarvis.core.local_facades as lf

    state = {"now": 1_000.0}
    monkeypatch.setattr(ct, "_now", lambda: state["now"])
    reg = lf.default_facades()
    result = reg.invoke("start_countdown", duration_s=10)
    assert result["ok"] is True
    steps = result["steps"]
    assert steps["start_timer"]["ok"] is True
    assert steps["start_timer"]["status"] == "running"
    # Artifact lokal (timer) tersedia untuk UI — bukan untuk remote
    assert "artifacts" in result
    assert result["artifacts"]["timer"].remaining_s() == 10


def test_start_countdown_facade_rejects_invalid_duration():
    import jarvis.core.local_facades as lf

    reg = lf.default_facades()
    assert reg.invoke("start_countdown", duration_s=0)["ok"] is False
    assert reg.invoke("start_countdown", duration_s=99999)["ok"] is False


def test_no_new_authority_via_static_contract():
    from pathlib import Path

    source = Path(
        "jarvis/core/local_facades.py").read_text(encoding="utf-8")
    for forbidden in ("import whatsapp", "requests", "socket", "http",
                      "subprocess", "selenium", "playwright", "write_bytes"):
        assert forbidden not in source, forbidden
