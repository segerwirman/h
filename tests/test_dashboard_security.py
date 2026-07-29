"""Phase 14 — dashboard exposure policy stays local-first."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


def test_default_dashboard_bind_ke_loopback_dan_tidak_perlu_firewall():
    from jarvis.core.dashboard_security import exposure_from_config

    policy = exposure_from_config({}, tls_available=False)

    assert policy.host == "127.0.0.1"
    assert policy.port == 8000
    assert policy.lan_enabled is False
    assert policy.needs_firewall is False
    assert policy.allows_remote_mutation is False


def test_lan_dashboard_tanpa_tls_ditolak_sebelum_bind():
    from jarvis.core.dashboard_security import (
        DashboardSecurityError,
        exposure_from_config,
    )

    with pytest.raises(DashboardSecurityError, match="TLS"):
        exposure_from_config(
            {"lan_enabled": True, "lan_read_only": True,
             "lan_allowed_origins": ["https://panel.example.test:8000"]},
            tls_available=False,
        )


@pytest.mark.parametrize("settings", [
    {"lan_enabled": True, "lan_read_only": False,
     "lan_allowed_origins": ["https://panel.example.test:8000"]},
    {"lan_enabled": True, "lan_read_only": True, "lan_allowed_origins": []},
    {"lan_enabled": True, "lan_read_only": True,
     "lan_allowed_origins": ["http://panel.example.test"]},
    {"lan_enabled": True, "lan_read_only": True,
     "lan_allowed_origins": ["https://panel.example.test/path"]},
    {"lan_enabled": True, "lan_read_only": True,
     "lan_allowed_origins": ["https://user@panel.example.test"]},
])
def test_lan_dashboard_konfigurasi_tidak_aman_ditolak(settings):
    from jarvis.core.dashboard_security import DashboardSecurityError, exposure_from_config

    with pytest.raises(DashboardSecurityError):
        exposure_from_config(settings, tls_available=True)


def test_lan_dashboard_menerima_hanya_origin_https_eksak():
    from jarvis.core.dashboard_security import exposure_from_config

    policy = exposure_from_config(
        {"lan_enabled": True, "lan_read_only": True,
         "lan_allowed_origins": ["https://Panel.Example.Test:8000"]},
        tls_available=True,
    )

    assert policy.host == "0.0.0.0"
    # LAN bind is explicit, but firewall/UAC remains an operator action.
    assert policy.needs_firewall is False
    assert policy.allows_origin("https://panel.example.test:8000") is True
    assert policy.allows_origin("https://evil.example.test") is False
    assert policy.allows_origin("") is False


def test_rate_limiter_membatasi_client_tanpa_menyimpan_payload():
    from jarvis.core.dashboard_security import FixedWindowRateLimiter

    now = [100.0]
    limiter = FixedWindowRateLimiter(limit=2, window_seconds=60, now=lambda: now[0])

    assert limiter.allow("127.0.0.1") is True
    assert limiter.allow("127.0.0.1") is True
    assert limiter.allow("127.0.0.1") is False
    assert limiter.allow("127.0.0.2") is True
    now[0] += 60.0
    assert limiter.allow("127.0.0.1") is True


def test_dashboard_crypto_asset_hanya_vendor_lokal_tanpa_cdn(monkeypatch, tmp_path):
    from dashboard import server as dashboard_server
    from dashboard.server import DashboardServer
    from fastapi.testclient import TestClient

    vendor = tmp_path / "crypto-js.min.js"
    monkeypatch.setattr(dashboard_server, "_CRYPTOJS_FILE", vendor)
    server = DashboardServer()
    response = TestClient(server.app).get("/static/crypto.js", follow_redirects=False)

    assert response.status_code == 503
    assert "location" not in response.headers


def test_dashboard_html_memasang_csp_tanpa_script_origin_eksternal():
    from dashboard.server import DashboardServer
    from fastapi.testclient import TestClient

    response = TestClient(DashboardServer().app).get("/")

    assert "content-security-policy" in response.headers
    assert "script-src 'self' 'unsafe-inline'" in response.headers["content-security-policy"]
    assert "https:" not in response.headers["content-security-policy"]


def test_dashboard_server_default_memakai_exposure_loopback():
    from dashboard.server import DashboardServer

    server = DashboardServer()

    assert server.exposure.host == "127.0.0.1"
    assert "://127.0.0.1:" in server.get_url()


def test_dashboard_server_loopback_tidak_menjadwalkan_firewall(monkeypatch):
    from dashboard import server as dashboard_server

    calls = []

    class FakeServer:
        def __init__(self, config):
            self._config = config

        async def serve(self):
            calls.append(("serve", self._config.kwargs))

    class FakeConfig:
        def __init__(self, _app, **kwargs):
            self.kwargs = kwargs

    async def _run():
        dashboard = dashboard_server.DashboardServer()
        monkeypatch.setattr(dashboard, "_ssl_enabled", lambda: False)
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "run_in_executor",
                            lambda *_args: calls.append(("firewall", None)))
        monkeypatch.setattr(dashboard_server, "uvicorn",
                            SimpleNamespace(Config=FakeConfig, Server=FakeServer))
        await dashboard.serve()

    asyncio.run(_run())

    assert ("firewall", None) not in calls
    assert calls == [("serve", {"host": "127.0.0.1", "port": 8000,
                                 "log_level": "warning"})]


def test_dashboard_config_default_tetap_loopback_dan_lan_read_only():
    from jarvis.core import config

    settings = config.section("dashboard")

    assert settings["lan_enabled"] is False
    assert settings["bind_host"] == "127.0.0.1"
    assert settings["lan_read_only"] is True
    assert settings["require_tls_for_lan"] is True


def test_dashboard_lan_read_only_menolak_command_bertoken():
    from dashboard.server import DashboardServer
    from fastapi.testclient import TestClient
    from jarvis.core.dashboard_security import exposure_from_config

    exposure = exposure_from_config(
        {"lan_enabled": True, "lan_read_only": True,
         "lan_allowed_origins": ["https://panel.example.test:8000"]},
        tls_available=True,
    )
    server = DashboardServer(exposure=exposure)
    server._tokens.add("safe-token")
    client = TestClient(server.app)

    response = client.post(
        "/api/command", json={"text": "harus tidak dijalankan"},
        headers={"authorization": "Bearer safe-token",
                 "origin": "https://panel.example.test:8000"},
    )

    assert response.status_code == 403
    assert server._command_queue.empty()


@pytest.mark.parametrize("path,payload", [
    ("/login", {"pin": "unknown"}),
    ("/api/wake", {}),
    ("/api/revoke-devices", {}),
    ("/api/device-login", {"device_token": "unknown"}),
])
def test_dashboard_lan_read_only_menolak_mutasi_http(path, payload):
    from dashboard.server import DashboardServer
    from fastapi.testclient import TestClient
    from jarvis.core.dashboard_security import exposure_from_config

    exposure = exposure_from_config(
        {"lan_enabled": True, "lan_read_only": True,
         "lan_allowed_origins": ["https://panel.example.test:8000"]},
        tls_available=True,
    )
    server = DashboardServer(exposure=exposure)
    server._tokens.add("safe-token")
    response = TestClient(server.app).post(
        path, json=payload,
        headers={"authorization": "Bearer safe-token",
                 "origin": "https://panel.example.test:8000"},
    )

    assert response.status_code == 403


def test_dashboard_lan_read_only_menolak_upload_sebelum_menulis_file(tmp_path):
    from dashboard.server import DashboardServer
    from fastapi.testclient import TestClient
    from jarvis.core.dashboard_security import exposure_from_config

    exposure = exposure_from_config(
        {"lan_enabled": True, "lan_read_only": True,
         "lan_allowed_origins": ["https://panel.example.test:8000"]},
        tls_available=True,
    )
    server = DashboardServer(exposure=exposure)
    server._uploads_dir = tmp_path
    server._tokens.add("safe-token")
    response = TestClient(server.app).post(
        "/api/upload", files={"file": ("notes.txt", b"private", "text/plain")},
        headers={"authorization": "Bearer safe-token",
                 "origin": "https://panel.example.test:8000"},
    )

    assert response.status_code == 403
    assert list(tmp_path.iterdir()) == []


def test_dashboard_lan_menolak_api_dari_origin_tidak_terdaftar():
    from dashboard.server import DashboardServer
    from fastapi.testclient import TestClient
    from jarvis.core.dashboard_security import exposure_from_config

    exposure = exposure_from_config(
        {"lan_enabled": True, "lan_read_only": True,
         "lan_allowed_origins": ["https://panel.example.test:8000"]},
        tls_available=True,
    )
    server = DashboardServer(exposure=exposure)
    server._tokens.add("safe-token")
    client = TestClient(server.app)

    blocked = client.get(
        "/api/control-plane", headers={"authorization": "Bearer safe-token",
                                        "origin": "https://evil.example.test"},
    )
    allowed = client.get(
        "/api/control-plane", headers={"authorization": "Bearer safe-token",
                                        "origin": "https://panel.example.test:8000"},
    )
    preflight = client.options(
        "/api/control-plane", headers={"origin": "https://panel.example.test:8000"},
    )

    assert blocked.status_code == 403
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://panel.example.test:8000"
    assert preflight.status_code == 204
    assert preflight.headers["access-control-allow-origin"] == "https://panel.example.test:8000"


def test_dashboard_command_rate_limit_ditolak_sebelum_enqueue():
    from dashboard.server import DashboardServer
    from fastapi.testclient import TestClient
    from jarvis.core.dashboard_security import FixedWindowRateLimiter

    server = DashboardServer()
    server._tokens.add("safe-token")
    server._command_rate_limiter = FixedWindowRateLimiter(limit=1, window_seconds=60)
    client = TestClient(server.app)
    headers = {"authorization": "Bearer safe-token"}

    first = client.post("/api/command", json={"text": "satu"}, headers=headers)
    blocked = client.post("/api/command", json={"text": "dua"}, headers=headers)

    assert first.status_code == 200
    assert blocked.status_code == 429
    assert server._command_queue.qsize() == 1


def test_dashboard_command_queue_memiliki_batas_aman():
    from dashboard.server import DashboardServer

    server = DashboardServer()

    assert server._command_queue.maxsize > 0


def test_dashboard_lan_read_only_menolak_websocket_command():
    from dashboard.server import DashboardServer
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from jarvis.core.dashboard_security import exposure_from_config

    exposure = exposure_from_config(
        {"lan_enabled": True, "lan_read_only": True,
         "lan_allowed_origins": ["https://panel.example.test:8000"]},
        tls_available=True,
    )
    server = DashboardServer(exposure=exposure)
    server._tokens.add("safe-token")

    with pytest.raises(WebSocketDisconnect) as closed:
        with TestClient(server.app).websocket_connect(
            "/ws?token=safe-token", headers={"origin": "https://panel.example.test:8000"}
        ):
            pass

    assert closed.value.code == 4003
    assert server._command_queue.empty()
