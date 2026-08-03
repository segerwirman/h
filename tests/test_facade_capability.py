"""27-lanjutan RED — facade capability enum & permanent reject rules.

Enum facade untuk capability proven (Content Studio title/reorder, Focus
Mode, browser media, timer, call-session); permanent reject rules
(coordinate/selector/key/path/url/screenshot/raw dispatch/login/payment);
per-capability policy (allowlist fields + confirmation) tetap berlaku.
"""
from __future__ import annotations

_FIXED_REASONS = {
    "facade_capability_unknown",
    "facade_permanent_reject",
    "facade_policy_field_rejected",
}


def _policy():
    import jarvis.core.facade_capability as fc

    return fc.CapabilityPolicy()


def test_capability_enum_is_fixed_and_deny_unknown():
    import jarvis.core.facade_capability as fc

    assert set(fc.FacadeCapability) == {
        fc.FacadeCapability.CONTENT_TITLE,
        fc.FacadeCapability.CONTENT_REORDER,
        fc.FacadeCapability.FOCUS_MODE,
        fc.FacadeCapability.BROWSER_MEDIA,
        fc.FacadeCapability.TIMER,
        fc.FacadeCapability.CALL_START,
        fc.FacadeCapability.CALL_STATUS,
        fc.FacadeCapability.CALL_HANGUP,
    }
    policy = _policy()
    assert policy.admit_capability("CONTENT_TITLE")["ok"] is True
    assert policy.admit_capability("free_form_mission")["ok"] is False
    assert policy.admit_capability("arbitrary_tool")["ok"] is False


def test_permanent_reject_rules_block_dangerous_args():
    policy = _policy()
    blocked_args = [
        {"coordinate": [10, 20]},
        {"x": 100, "y": 200},
        {"selector": "#login"},
        {"key": "ctrl+alt+del"},
        {"path": "C:/Windows/system32"},
        {"url": "https://example.com/pay"},
        {"screenshot": True},
        {"raw_dispatch": "shell:calc"},
        {"login": "admin"},
        {"payment": 100000},
    ]
    for args in blocked_args:
        result = policy.check_rejects(args)
        assert result["ok"] is False, args
        assert result["reason"] == "facade_permanent_reject", args
    # Arg normal tidak ter-reject
    assert policy.check_rejects({"duration_s": 10})["ok"] is True
    assert policy.check_rejects({})["ok"] is True


def test_per_capability_field_allowlist_enforced():
    policy = _policy()
    # TIMER hanya menerima duration_s
    result = policy.verify_policy("TIMER", {"duration_s": 10})
    assert result["ok"] is True
    result = policy.verify_policy("TIMER", {"coordinate": [1, 2]})
    assert result["ok"] is False
    assert result["reason"] == "facade_permanent_reject"
    result = policy.verify_policy("TIMER", {"title": "X"})
    assert result["ok"] is False
    assert result["reason"] == "facade_policy_field_rejected"
    # CONTENT_REORDER hanya source/destination element id
    result = policy.verify_policy(
        "CONTENT_REORDER",
        {"source_element_id": "a", "destination_element_id": "b"})
    assert result["ok"] is True
    result = policy.verify_policy("CONTENT_REORDER", {"from": 0, "to": 1})
    assert result["ok"] is False


def test_confirmation_required_per_capability():
    policy = _policy()
    assert policy.requires_confirmation("CONTENT_TITLE") is True
    assert policy.requires_confirmation("CONTENT_REORDER") is True
    assert policy.requires_confirmation("CALL_START") is True
    assert policy.requires_confirmation("CALL_HANGUP") is True
    assert policy.requires_confirmation("TIMER") is False
    assert policy.requires_confirmation("FOCUS_MODE") is False
    assert policy.requires_confirmation("BROWSER_MEDIA") is False
    assert policy.requires_confirmation("CALL_STATUS") is False


def test_reason_codes_are_closed_set():
    import jarvis.core.facade_capability as fc

    policy = _policy()
    results = [
        policy.admit_capability("nope"),
        policy.check_rejects({"path": "/etc/passwd"}),
        policy.verify_policy("TIMER", {"notes": "x"}),
    ]
    for result in results:
        assert result["ok"] is False
        assert result["reason"] in _FIXED_REASONS, result["reason"]
        assert result["reason"] in fc._FIXED_REASONS


def test_no_live_authority_via_static_contract():
    from pathlib import Path

    source = Path(
        "jarvis/core/facade_capability.py").read_text(encoding="utf-8")
    for forbidden in ("import whatsapp", "requests", "socket", "http",
                      "subprocess", "selenium", "playwright", "write_bytes"):
        assert forbidden not in source, forbidden
