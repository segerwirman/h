"""Fase 16 — panggilan ke kontak allowlist tanpa gerbang ganda (S-2).

Permintaan eksplisit Takeda: jangan minta konfirmasi berkali-kali, langsung
telepon. Baru aman dikerjakan setelah Fase 14 (klaim sukses tidak bisa
dikarang) dan Fase 15 (konfirmasi yang tersisa bisa dijawab dengan suara).

Yang dilonggarkan hanya `whatsapp_call` untuk kontak yang SUDAH lolos
allowlist. Kontak itu sudah melewati satu gerbang manual saat dimasukkan ke
`data/whatsapp_contacts.json`; bertanya lagi setiap kali adalah gerbang kedua
pada risiko yang sama.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.agent.tools.whatsapp_web import (
    WhatsAppAnswer,
    WhatsAppCall,
    WhatsAppSendMessage,
)
from jarvis.integrations import whatsapp_web as ww


@pytest.fixture
def contacts(tmp_path, monkeypatch):
    path = tmp_path / "contacts.json"
    path.write_text(json.dumps({"contacts": [
        {"name": "Honbrew", "phone": "628123456789", "allowed": True},
        {"name": "Belum Diizinkan", "phone": "628987654321", "allowed": False},
    ]}), encoding="utf-8")
    monkeypatch.setattr(ww, "_contacts_path", lambda: path)
    return path


def _mode(monkeypatch, value):
    """Setel mode tanpa menambal modul config global (pelajaran T7)."""
    from jarvis.agent.tools import whatsapp_web as tool_mod

    real = tool_mod.config

    class _Shim:
        def get(self, path, default=None):
            if path == "whatsapp_web.call_confirmation":
                return value
            return real.get(path, default)

        def __getattr__(self, name):
            return getattr(real, name)

    monkeypatch.setattr(tool_mod, "config", _Shim())


# ── mode default ──────────────────────────────────────────────────────────

def test_default_mode_is_allowlisted_only():
    from jarvis.core import config

    assert config.get("whatsapp_web.call_confirmation") == "allowlisted_only"


def test_allowlisted_contact_is_called_without_asking(contacts, monkeypatch):
    _mode(monkeypatch, "allowlisted_only")
    assert WhatsAppCall().needs_confirmation(contact="Honbrew") is False


def test_stt_variant_of_an_allowlisted_name_still_skips(contacts, monkeypatch):
    """Resolver yang sama dengan yang mengeksekusi panggilan yang memutuskan.

    Kalau gerbang memakai pencocokan yang lebih ketat daripada eksekusi,
    Jarvis akan bertanya untuk kontak yang toh akan ditelepon juga.
    """
    _mode(monkeypatch, "allowlisted_only")
    assert WhatsAppCall().needs_confirmation(contact="honbru") is False


def test_unknown_contact_still_asks(contacts, monkeypatch):
    _mode(monkeypatch, "allowlisted_only")
    assert WhatsAppCall().needs_confirmation(contact="Orang Asing") is True


def test_contact_present_but_not_allowed_still_asks(contacts, monkeypatch):
    _mode(monkeypatch, "allowlisted_only")
    assert WhatsAppCall().needs_confirmation(
        contact="Belum Diizinkan") is True


def test_empty_contact_still_asks(contacts, monkeypatch):
    _mode(monkeypatch, "allowlisted_only")
    assert WhatsAppCall().needs_confirmation(contact="") is True
    assert WhatsAppCall().needs_confirmation() is True


# ── mode lain ─────────────────────────────────────────────────────────────

def test_always_mode_restores_the_old_behaviour(contacts, monkeypatch):
    _mode(monkeypatch, "always")
    assert WhatsAppCall().needs_confirmation(contact="Honbrew") is True


def test_never_mode_skips_for_allowlisted_only_all_the_same(contacts,
                                                            monkeypatch):
    """`never` menghapus pertanyaan, BUKAN allowlist.

    Kontak di luar allowlist tetap tidak bisa ditelepon — resolver yang
    menolaknya saat eksekusi, bukan dialog konfirmasi.
    """
    _mode(monkeypatch, "never")
    assert WhatsAppCall().needs_confirmation(contact="Honbrew") is False
    assert WhatsAppCall().needs_confirmation(contact="Orang Asing") is False

    with pytest.raises(ww.WhatsAppError):
        ww.resolve_contact("Orang Asing")


def test_unknown_mode_fails_closed_to_asking(contacts, monkeypatch):
    for value in ("longgar", "", None, 5):
        _mode(monkeypatch, value)
        assert WhatsAppCall().needs_confirmation(contact="Honbrew") is True, value


def test_gate_never_raises_when_contacts_are_unreadable(monkeypatch):
    _mode(monkeypatch, "allowlisted_only")
    monkeypatch.setattr(
        ww, "resolve_contact",
        lambda _v: (_ for _ in ()).throw(RuntimeError("disk mati")))
    assert WhatsAppCall().needs_confirmation(contact="Honbrew") is True


# ── yang TIDAK dilonggarkan ───────────────────────────────────────────────

def test_sending_a_message_is_never_loosened(contacts, monkeypatch):
    """Isi pesan tidak bisa ditarik kembali, dan tidak terikat allowlist
    sebagaimana identitas kontak."""
    for value in ("allowlisted_only", "never"):
        _mode(monkeypatch, value)
        assert WhatsAppSendMessage().needs_confirmation(
            contact="Honbrew", message="halo") is True


def test_answering_an_incoming_call_is_out_of_scope(contacts, monkeypatch):
    """Di luar cakupan Fase 16 — tetap bertanya sampai diputuskan terpisah."""
    _mode(monkeypatch, "never")
    assert WhatsAppAnswer().needs_confirmation() is True


def test_direct_numbers_stay_denied(contacts, monkeypatch):
    """Melonggarkan konfirmasi DAN nomor bebas sekaligus berarti satu salah
    dengar STT bisa menelepon nomor acak."""
    from jarvis.core import config

    assert config.get("whatsapp_web.allow_direct_numbers") is False
    _mode(monkeypatch, "never")
    with pytest.raises(ww.WhatsAppError):
        ww.resolve_contact("628111111111")


# ── jejak yang terlihat ───────────────────────────────────────────────────

def test_unconfirmed_call_is_announced_before_dialing(contacts, monkeypatch):
    """Panggilan tanpa konfirmasi wajib meninggalkan jejak yang terlihat.

    Menghapus dialog boleh; menghapus kesempatan user menyadari panggilan
    sedang berjalan tidak.
    """
    from jarvis.agent.tools import whatsapp_web as tool_mod

    lines: list[str] = []

    class _Adapter:
        async def progress(self, text):
            lines.append(text)

    class _Svc:
        @staticmethod
        def start_call(contact):
            return {"state": "ringing", "contact": contact, "proven": True}

    monkeypatch.setattr(ww.WhatsAppWebService, "get", staticmethod(lambda: _Svc))
    monkeypatch.setattr(tool_mod, "_start_bridge",
                        lambda: {"active": False, "error": "bridge mati"})
    _mode(monkeypatch, "allowlisted_only")

    result = asyncio.run(
        WhatsAppCall().run(contact="Honbrew", _adapter=_Adapter()))

    assert result.ok is True
    assert any("Honbrew" in line for line in lines), lines
