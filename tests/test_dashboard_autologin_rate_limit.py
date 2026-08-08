"""Fase 10.3 — `/auto-login` harus dibatasi laju seperti `/login`.

`/login` menolak percobaan berlebih dengan 429 lewat ``_auth_rate_limiter``
(server.py:529). `/auto-login?key=` menerima kunci sekali-pakai yang sama
tetapi dulu tidak punya pembatas apa pun — asimetri yang membuat satu-satunya
penghalang tebak-kunci adalah panjang kuncinya.

Risiko nyatanya rendah (``_mutation_allowed()`` menolak seluruh mutasi saat
LAN aktif, dan default-nya loopback), tetapi asimetri di sekitar credential
tidak layak dibiarkan.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from fastapi.testclient import TestClient

from dashboard.server import DashboardServer


def _throttle(server, limit: int) -> None:
    """Pasang limiter baru lewat konstruktor publik — jangan mengutak-atik
    atribut privat, yang dulu membuat test ini diam-diam tidak menguji apa pun."""
    from jarvis.core.dashboard_security import FixedWindowRateLimiter
    server._auth_rate_limiter = FixedWindowRateLimiter(limit=limit,
                                                       window_seconds=60)


@pytest.fixture()
def client():
    server = DashboardServer()
    _throttle(server, 3)          # batas kecil supaya test cepat
    with TestClient(server.app) as http:
        yield http, server


def test_auto_login_kunci_salah_akhirnya_429(client):
    http, _ = client
    codes = [http.get("/auto-login", params={"key": f"SALAH{i}"},
                      follow_redirects=False).status_code
             for i in range(8)]
    assert 429 in codes, f"tidak pernah dibatasi: {codes}"


def test_auto_login_batas_sama_dengan_login(client):
    """Keduanya memakai limiter yang sama — bukan dua kebijakan berbeda."""
    http, server = client
    _throttle(server, 2)
    first = http.get("/auto-login", params={"key": "AAA"},
                     follow_redirects=False).status_code
    assert first != 429, "permintaan pertama tidak boleh langsung ditolak"
    for _ in range(6):
        http.get("/auto-login", params={"key": "AAA"}, follow_redirects=False)
    # limiter yang sama sudah jenuh → /login ikut menolak
    assert http.post("/login", json={"pin": "AAA"}).status_code == 429


def test_kunci_sah_tetap_diterima_sebelum_batas(client):
    """Pembatas tidak boleh memblokir pemakaian normal QR pertama."""
    http, server = client
    key = server.new_key()
    r = http.get("/auto-login", params={"key": key}, follow_redirects=False)
    assert r.status_code == 200
    assert key not in server._pending_keys, "kunci sekali-pakai harus habis"
