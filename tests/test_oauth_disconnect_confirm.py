"""Tombol OAuth tidak boleh memutus koneksi tanpa konfirmasi.

Bukti insiden 2026-08-04 di logs/jarvis.log:

    09:18:48  oauth.connected  provider=openai_oauth
    09:18:48  oauth.logout     provider=openai_oauth

Login berhasil lalu token terhapus di detik yang sama. Penyebabnya satu
tombol dipakai untuk HUBUNGKAN dan PUTUSKAN (settings_providers.py:480-482)
dan cabang putus langsung memanggil logout() tanpa bertanya. Gejala yang
dilihat user: "sudah login dan berhasil terhubung, tapi tetap gagal
terkoneksi dengan model" — karena tokennya sudah hilang lagi.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

_APP_REF: QApplication | None = None
# Qt memiliki widget lewat parent C++; tanpa referensi Python yang hidup, host
# ikut ter-GC dan sheet-nya dihapus di tengah test ("wrapped C/C++ object ...
# has been deleted"). Simpan seperti _APP_REF.
_HOST_REFS: list[QWidget] = []


def _app() -> QApplication:
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


def _sheet_connected(monkeypatch, calls):
    """Panel dengan provider openai_oauth dalam keadaan TERHUBUNG."""
    from jarvis.agent import providers
    from jarvis.agent.providers import Provider
    from jarvis.integrations import openai_oauth
    from jarvis.ui.settings_providers import ProviderSettingsSheet

    oauth = Provider(name="openai_oauth", kind="openai_oauth",
                     label="OpenAI OAuth", model="gpt-light", auth="oauth",
                     enabled=True, capabilities=("chat", "tools"))
    monkeypatch.setattr(providers, "list_names", lambda: ["openai_oauth"])
    monkeypatch.setattr(providers, "active_name", lambda: "openai_oauth")
    monkeypatch.setattr(providers, "get_provider", lambda _name=None: oauth)
    monkeypatch.setattr(providers, "reset_clients", lambda: None)
    monkeypatch.setattr(openai_oauth, "status", lambda: {
        "connected": True, "needs_reauth": False,
        "token_refresh_due": False, "last_error_code": "",
    })
    monkeypatch.setattr(openai_oauth, "logout",
                        lambda: calls.append("logout"))

    _app()
    host = QWidget()
    _HOST_REFS.append(host)
    sheet = ProviderSettingsSheet(host)
    _HOST_REFS.append(sheet)
    return sheet


def test_batal_konfirmasi_tidak_memutus_token(monkeypatch):
    calls: list[str] = []
    sheet = _sheet_connected(monkeypatch, calls)
    monkeypatch.setattr(sheet, "_confirm_disconnect", lambda _name: False)

    sheet._oauth_action()

    assert "logout" not in calls, "token terputus padahal konfirmasi dibatalkan"


def test_konfirmasi_disetujui_baru_memutus(monkeypatch):
    calls: list[str] = []
    sheet = _sheet_connected(monkeypatch, calls)
    monkeypatch.setattr(sheet, "_confirm_disconnect", lambda _name: True)

    sheet._oauth_action()

    assert "logout" in calls, "konfirmasi disetujui tetapi tidak memutus"


def test_konfirmasi_ditanyakan_dengan_nama_provider(monkeypatch):
    seen: list[str] = []
    calls: list[str] = []
    sheet = _sheet_connected(monkeypatch, calls)
    monkeypatch.setattr(sheet, "_confirm_disconnect",
                        lambda name: (seen.append(name), False)[1])

    sheet._oauth_action()

    assert seen == ["openai_oauth"], seen
