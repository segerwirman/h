"""Fase 10.1 — WebhookReceiver harus menghormati port/host yang dioper.

Bug: ``self.port = int(port or _env("RELAY_WEBHOOK_PORT", "8791"))``.
``port=0`` bernilai falsy, jadi idiom baku "pilih port bebas" jatuh ke default
env dan receiver selalu merebut 8791 — port produksi.

Akibat nyata (terreproduksi 2026-08-04): `test_relay.py::test_webhook_end_to_end`
mengoper ``port=0`` namun tetap mengikat 8791, sehingga gagal setiap kali
JARVIS sedang berjalan. Lebih buruk lagi, dengan SO_REUSEADDR di Windows dua
proses bisa sama-sama "berhasil" bind ke port yang sama dan permintaan test
nyasar ke server produksi.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from jarvis.integrations.relay.store import RelayStore
from jarvis.integrations.relay.webhook import WebhookReceiver

SECRET = "rahasia-uji"


@pytest.fixture()
def store():
    return RelayStore(db_path=pathlib.Path(tempfile.mkdtemp()) / "wh.sqlite")


def _receiver(store, **kwargs):
    kwargs.setdefault("host", "127.0.0.1")
    kwargs.setdefault("path", "/relay/webhook")
    kwargs.setdefault("secret", SECRET)
    return WebhookReceiver(store=store, **kwargs)


def test_port_nol_berarti_ephemeral_bukan_default_env(store):
    """port=0 adalah permintaan eksplisit "pilih port bebas", bukan "kosong"."""
    assert _receiver(store, port=0).port == 0


def test_port_nol_benar_benar_mengikat_port_bebas(store):
    wh = _receiver(store, port=0)
    assert wh.start()
    try:
        bound = wh._server.server_address[1]
        assert bound != 8791, "merebut port produksi meski diminta ephemeral"
        assert bound > 0
    finally:
        wh.stop()


def test_port_eksplisit_tetap_dihormati(store):
    assert _receiver(store, port=18791).port == 18791


def test_tanpa_port_jatuh_ke_default(store):
    """Perilaku lama untuk pemanggil yang tidak menyebut port sama sekali."""
    assert _receiver(store, port=None).port == 8791


def test_dua_receiver_ephemeral_tidak_bertabrakan(store):
    """Dua instance uji harus bisa hidup berdampingan — inti dari isolasi."""
    a, b = _receiver(store, port=0), _receiver(store, port=0)
    assert a.start()
    try:
        assert b.start()
        try:
            assert a._server.server_address[1] != b._server.server_address[1]
        finally:
            b.stop()
    finally:
        a.stop()
