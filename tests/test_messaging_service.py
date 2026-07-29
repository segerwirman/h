"""Fase 3 — MessagingService: status dari file Hermes, tulis via bridge,
allowlist enforcement (§6.4)."""
from __future__ import annotations

import json

import pytest

from jarvis.integrations.hermes import messaging_service as svc
from jarvis.integrations.hermes import platform_catalog as catalog


class _StubBridge:
    """Bridge palsu — merekam panggilan; config_set platforms.* menulis
    config.yaml Hermes tiruan supaya verifikasi set_enabled jalan."""

    def __init__(self, home, effective=True):
        self.home = home
        self.effective = effective
        self.calls: list[tuple] = []

    def config_set(self, key, value):
        self.calls.append(("config_set", key, value))
        if self.effective and key.startswith("platforms."):
            _, pid, field = key.split(".")
            import yaml
            path = self.home / "config.yaml"
            data = {}
            if path.exists():
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            data.setdefault("platforms", {}).setdefault(pid, {})[field] = \
                value == "true"
            path.write_text(yaml.safe_dump(data), encoding="utf-8")
        return {"ok": True, "stdout": "", "stderr": ""}

    def gateway_command(self, action, timeout_s=90):
        self.calls.append(("gateway", action))
        return {"ok": True, "stdout": "", "stderr": ""}


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    # These are compatibility-path tests; MK50 production config stays off.
    monkeypatch.setattr(svc, "is_enabled", lambda: True)
    stub = _StubBridge(tmp_path)
    monkeypatch.setattr(svc.HermesBridge, "get", classmethod(lambda cls: stub))
    return tmp_path, stub


def _env(home, **kv):
    (home / ".env").write_text(
        "\n".join(f"{k}={v}" for k, v in kv.items()) + "\n", encoding="utf-8")


def _cfg(home, **platforms):
    import yaml
    (home / "config.yaml").write_text(
        yaml.safe_dump({"platforms": {k: {"enabled": v}
                                      for k, v in platforms.items()}}),
        encoding="utf-8")


def _runtime(home, gateway_state="running", **plat_states):
    (home / "gateway_state.json").write_text(json.dumps({
        "gateway_state": gateway_state,
        "platforms": {k: {"state": v} for k, v in plat_states.items()},
    }), encoding="utf-8")


def _plat(pid):
    return {p["id"]: p for p in svc.list_platforms()}[pid]


# ── status ────────────────────────────────────────────────────────────────────

def test_derivasi_state(home):
    h, _ = home
    _env(h, TELEGRAM_BOT_TOKEN="abc", TELEGRAM_ALLOWED_USERS="123")
    _cfg(h, telegram=True, discord=False)
    _runtime(h, gateway_state="running", telegram="connected")

    tg = _plat("telegram")
    assert tg["state"] == "connected" and tg["live"] is True
    assert tg["configured"] is True and tg["allowlist_ok"] is True
    assert _plat("discord")["state"] == "disabled"
    # slack enabled tanpa token → not_configured
    _cfg(h, slack=True)
    assert _plat("slack")["state"] == "not_configured"
    # telegram enabled+configured, gateway hidup, belum lapor → pending_restart
    _cfg(h, telegram=True)
    _runtime(h, gateway_state="running")
    assert _plat("telegram")["state"] == "pending_restart"
    _runtime(h, gateway_state="stopped")
    assert _plat("telegram")["state"] == "gateway_stopped"


def test_field_redaksi_dan_flag(home):
    h, _ = home
    _env(h, TELEGRAM_BOT_TOKEN="1234567890:secret")
    fields = {f["key"]: f for f in _plat("telegram")["fields"]}
    tok = fields["TELEGRAM_BOT_TOKEN"]
    assert tok["is_set"] and tok["secret"] and tok["required"]
    assert tok["redacted"].endswith("cret") and "secret" not in \
        tok["redacted"][:-4]
    assert fields["TELEGRAM_ALLOWED_USERS"]["is_allowlist"] is True


def test_instalasi_kosong_tidak_crash(home):
    plats = svc.list_platforms()
    assert len(plats) == len(catalog.CATALOG)
    assert all(p["state"] in ("disabled",) for p in plats)


# ── tulis ─────────────────────────────────────────────────────────────────────

def test_set_env_validasi(home):
    _, stub = home
    ok, _ = svc.set_env("KEY_ASING", "x")
    assert ok is False and stub.calls == []
    ok, _ = svc.set_env("TELEGRAM_BOT_TOKEN", "  ")
    assert ok is False
    ok, _ = svc.set_env("TELEGRAM_BOT_TOKEN", "tok")
    assert ok is True
    assert stub.calls == [("config_set", "TELEGRAM_BOT_TOKEN", "tok")]


def test_clear_env_surgical(home):
    h, _ = home
    (h / ".env").write_text(
        "# komentar\nTELEGRAM_BOT_TOKEN=abc\nDISCORD_BOT_TOKEN=def\n",
        encoding="utf-8")
    ok, _ = svc.clear_env("TELEGRAM_BOT_TOKEN")
    assert ok is True
    text = (h / ".env").read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN" not in text
    assert "# komentar" in text and "DISCORD_BOT_TOKEN=def" in text


# ── allowlist enforcement (§6.4) ──────────────────────────────────────────────

def test_enable_ditolak_tanpa_allowlist(home):
    h, stub = home
    _env(h, TELEGRAM_BOT_TOKEN="abc")            # token ada, allowlist kosong
    ok, msg = svc.set_enabled("telegram", True)
    assert ok is False and "allowlist" in msg
    assert stub.calls == []                       # bridge tidak disentuh


def test_enable_dengan_allowlist(home):
    h, stub = home
    _env(h, TELEGRAM_BOT_TOKEN="abc", TELEGRAM_ALLOWED_USERS="42")
    ok, _ = svc.set_enabled("telegram", True)
    assert ok is True
    assert ("config_set", "platforms.telegram.enabled", "true") in stub.calls
    # disable selalu boleh
    ok, _ = svc.set_enabled("telegram", False)
    assert ok is True


def test_allow_all_butuh_konfirmasi_eksplisit(home):
    h, _ = home
    _env(h, TELEGRAM_BOT_TOKEN="abc", GATEWAY_ALLOW_ALL_USERS="true")
    ok, _ = svc.set_enabled("telegram", True)                 # tanpa konfirmasi
    assert ok is False
    ok, _ = svc.set_enabled("telegram", True, allow_all_confirmed=True)
    assert ok is True


def test_set_enabled_verifikasi_efek_nyata(home, monkeypatch):
    h, stub = home
    stub.effective = False                        # CLI "sukses" tanpa efek
    _env(h, TELEGRAM_BOT_TOKEN="abc", TELEGRAM_ALLOWED_USERS="42")
    ok, msg = svc.set_enabled("telegram", True)
    assert ok is False and "tidak berefek" in msg


def test_restart_gateway(home):
    _, stub = home
    ok, _ = svc.restart_gateway()
    assert ok is True and ("gateway", "restart") in stub.calls
