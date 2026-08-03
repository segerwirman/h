"""Phase WA9 RED — controlled WhatsApp rollout.

Deny-by-default: toggle config + allowlist policy + opt-out/revoke +
rate limiting + daily caps. Tanpa live integration di fase ini.
"""
from __future__ import annotations


def _policy(monkeypatch, *, enabled=True, allowlist=("Toko Bunga",),
            rate_per_minute=5, daily_cap=50, now=1_800_000_000):
    import jarvis.integrations.whatsapp_rollout as wr

    def cfg(key, default=None):
        table = {
            "integrations.whatsapp.rollout_enabled": enabled,
            "integrations.whatsapp.allowlist": list(allowlist),
            "integrations.whatsapp.rate_per_minute": rate_per_minute,
            "integrations.whatsapp.daily_cap": daily_cap,
        }
        return table.get(key, default)

    state = {"now": now}
    monkeypatch.setattr(wr, "_config_get", cfg)
    monkeypatch.setattr(wr, "_now", lambda: state["now"])
    return wr, state


def test_deny_by_default_without_config(monkeypatch):
    import jarvis.integrations.whatsapp_rollout as wr

    monkeypatch.setattr(wr, "_config_get", lambda key, d=None: d)
    monkeypatch.setattr(wr, "_now", lambda: 1_800_000_000)
    policy = wr.WhatsAppRolloutPolicy()
    result = policy.allow_outbound("Toko Bunga")
    assert result["ok"] is False
    assert result["reason"] == "wa_rollout_disabled"


def test_contact_not_in_allowlist_is_denied(monkeypatch):
    wr, _state = _policy(monkeypatch)
    policy = wr.WhatsAppRolloutPolicy()
    result = policy.allow_outbound("Orang Tak Dikenal")
    assert result["ok"] is False
    assert result["reason"] == "wa_contact_not_allowlisted"


def test_opt_out_revokes_and_revoke_restores(monkeypatch):
    wr, _state = _policy(monkeypatch)
    policy = wr.WhatsAppRolloutPolicy()

    assert policy.opt_out("Toko Bunga") is True
    result = policy.allow_outbound("Toko Bunga")
    assert result["ok"] is False
    assert result["reason"] == "wa_contact_opted_out"

    assert policy.revoke_opt_out("Toko Bunga") is True
    result = policy.allow_outbound("Toko Bunga")
    assert result["ok"] is True
    assert result["reason"] is None


def test_rate_limit_blocks_bursts_then_recovers(monkeypatch):
    wr, state = _policy(monkeypatch, rate_per_minute=2)
    policy = wr.WhatsAppRolloutPolicy()

    assert policy.allow_outbound("Toko Bunga")["ok"] is True
    assert policy.allow_outbound("Toko Bunga")["ok"] is True
    # Burst ketiga → rate limited
    result = policy.allow_outbound("Toko Bunga")
    assert result["ok"] is False
    assert result["reason"] == "wa_rate_limited"
    # Window 60s berlalu → pulih
    state["now"] += 61
    assert policy.allow_outbound("Toko Bunga")["ok"] is True


def test_daily_cap_resets_on_new_day(monkeypatch):
    wr, state = _policy(monkeypatch, daily_cap=3)
    policy = wr.WhatsAppRolloutPolicy()

    for _ in range(3):
        assert policy.allow_outbound("Toko Bunga")["ok"] is True
    result = policy.allow_outbound("Toko Bunga")
    assert result["ok"] is False
    assert result["reason"] == "wa_daily_cap_reached"
    # Hari berikutnya → reset
    state["now"] += 86_400
    assert policy.allow_outbound("Toko Bunga")["ok"] is True


def test_all_gates_pass_for_allowlisted_contact(monkeypatch):
    wr, _state = _policy(monkeypatch)
    policy = wr.WhatsAppRolloutPolicy()
    result = policy.allow_outbound("Toko Bunga")
    assert result["ok"] is True
    assert result["reason"] is None


def test_no_live_integration_authority(monkeypatch):
    # Kontrak statis: tanpa import SDK/network — policy murni lokal
    from pathlib import Path

    source = Path(
        "jarvis/integrations/whatsapp_rollout.py").read_text(encoding="utf-8")
    for forbidden in ("import whatsapp", "requests", "socket", "http",
                      "open(", "subprocess"):
        assert forbidden not in source, forbidden
