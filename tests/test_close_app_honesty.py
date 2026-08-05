"""Fase 20 — `close_app` harus menyebut apa yang BENAR-BENAR ditutup (S-20).

Takeda: *"perintah untuk menutup browser, jarvis hanya memberikan klaim palsu
kalau dia sudah berhasil menutup browser."*

Dua cacat yang menghasilkan satu klaim palsu.

1. Kata "browser" tidak menunjuk Chrome. `app_registry.resolve('browser')`
   mengembalikan ``None``, dan pencocokan substring mendarat di aplikasi lain
   yang kebetulan memuat kata itu (di mesin Takeda: **Tabbit Browser**).
2. Pesan suksesnya ``f"{target.title()} ditutup."`` menggemakan **kata yang
   diucapkan user**, bukan proses yang sungguh tertutup. User bilang
   "browser" → dijawab "Browser ditutup."

Gabungannya: Jarvis menutup aplikasi yang salah lalu melaporkannya memakai
kata user, sehingga terdengar persis seperti keberhasilan. Melaporkan
PERMINTAAN, bukan HASIL — penyakit S-1, kali ini ditulis kode kita sendiri.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from actions import close_app as ca


@dataclass
class _App:
    name: str
    pid: int
    window_title: str = ""


def _wire(monkeypatch, running, *, resolve=None, alive_after=()):
    """Pasang dunia palsu: daftar proses, resolver, dan siapa yang selamat."""
    from jarvis.core import app_registry

    monkeypatch.setattr(app_registry, "list_running", lambda: list(running))
    monkeypatch.setattr(app_registry, "resolve", lambda _q: resolve)
    monkeypatch.setattr(ca.process_guard, "assert_not_self", lambda _a: None)
    monkeypatch.setattr(ca.process_guard, "refers_to_jarvis", lambda _n: False)
    monkeypatch.setattr(ca.process_guard, "is_protected_name", lambda _n: False)

    survivors = set(alive_after)
    monkeypatch.setattr(ca, "_graceful", lambda _a: True)
    monkeypatch.setattr(ca, "_hard_kill", lambda _a: True)
    monkeypatch.setattr(ca, "_alive", lambda pid: pid in survivors)


# ── cacat 2: pesan menggemakan permintaan ─────────────────────────────────

def test_success_names_the_process_that_actually_closed(monkeypatch):
    """Nama aplikasinya, bukan kata user — dan bukan pula judul jendela saja.

    "ChatGPT - Tabbit ditutup" memberitahu jendela mana, tetapi tidak
    memberitahu APLIKASI apa yang hilang dari layar.
    """
    running = [_App("Tabbit Browser.exe", 19844, "ChatGPT - Tabbit")]
    _wire(monkeypatch, running)

    outcome = ca.close_app("tabbit browser", grace_s=0.0)

    assert outcome.ok is True
    assert "Tabbit" in outcome.message, (
        f"pesan harus menyebut yang sungguh ditutup, bukan kata user: "
        f"{outcome.message!r}")


def test_success_message_is_not_merely_the_requested_word(monkeypatch):
    running = [_App("notepad.exe", 501, "Untitled - Notepad")]
    _wire(monkeypatch, running)

    outcome = ca.close_app("notepad", grace_s=0.0)

    assert outcome.ok is True
    assert outcome.closed, "daftar closed tidak boleh kosong saat sukses"
    assert any(item in outcome.message for item in outcome.closed)


# ── cacat 1: tebakan longgar diperlakukan sebagai kepastian ───────────────

def test_loose_name_match_asks_instead_of_closing(monkeypatch):
    """"browser" tidak dikenal registry dan hanya cocok sebagai substring.

    Menutupnya diam-diam berarti menutup aplikasi yang tidak diminta user.
    Yang benar: sebutkan apa yang ditemukan, lalu tanya.
    """
    running = [_App("Tabbit Browser.exe", 19844, "ChatGPT - Tabbit")]
    _wire(monkeypatch, running, resolve=None)

    outcome = ca.close_app("browser", grace_s=0.0)

    assert outcome.ok is False
    assert outcome.status == ca.STATUS_AMBIGUOUS
    assert "Tabbit" in outcome.message or any(
        "Tabbit" in c for c in outcome.candidates)


def test_exact_name_still_closes_without_asking(monkeypatch):
    """Gerbang yang menanyakan semuanya sama tidak bergunanya."""
    running = [_App("Tabbit Browser.exe", 19844, "ChatGPT - Tabbit")]
    _wire(monkeypatch, running, resolve=None)

    outcome = ca.close_app("tabbit browser", grace_s=0.0)

    assert outcome.ok is True
    assert outcome.status == ca.STATUS_CLOSED


def test_registry_resolved_name_closes_without_asking(monkeypatch):
    """Nama yang dikenal app_registry adalah niat yang jelas."""
    class _Match:
        key = "google chrome"

    running = [_App("chrome.exe", 2108, "WhatsApp - Google Chrome")]
    _wire(monkeypatch, running, resolve=_Match())

    outcome = ca.close_app("chrome", grace_s=0.0)

    assert outcome.ok is True
    assert "Chrome" in outcome.message


def test_many_windows_still_asks(monkeypatch):
    running = [
        _App("chrome.exe", 2108, "WhatsApp - Google Chrome"),
        _App("chrome.exe", 36080, "Search - Google Chrome"),
    ]

    class _Match:
        key = "google chrome"

    _wire(monkeypatch, running, resolve=_Match())

    outcome = ca.close_app("chrome", grace_s=0.0)

    assert outcome.ok is False
    assert outcome.status == ca.STATUS_AMBIGUOUS


# ── bukti: proses harus benar-benar hilang ────────────────────────────────

def test_a_surviving_process_is_never_reported_as_closed(monkeypatch):
    running = [_App("notepad.exe", 501, "Untitled - Notepad")]
    _wire(monkeypatch, running, alive_after={501})

    outcome = ca.close_app("notepad", grace_s=0.0)

    assert outcome.ok is False
    assert outcome.status == ca.STATUS_FAILED
    assert "Notepad" in " ".join(outcome.candidates)


def test_not_running_says_so_without_claiming_success(monkeypatch):
    _wire(monkeypatch, [])

    outcome = ca.close_app("spotify", grace_s=0.0)

    assert outcome.ok is False
    assert outcome.status == ca.STATUS_NOT_RUNNING


# ── jalur suara ikut jujur ────────────────────────────────────────────────

def test_voice_handler_reports_the_real_name(monkeypatch):
    from jarvis.integrations import voice_safety

    running = [_App("Tabbit Browser.exe", 19844, "ChatGPT - Tabbit")]
    _wire(monkeypatch, running)

    message, ok = voice_safety.handle_close_app({"name": "tabbit browser"})

    assert ok is True
    assert "Tabbit" in message


def test_voice_handler_does_not_close_on_a_loose_guess(monkeypatch):
    from jarvis.integrations import voice_safety

    running = [_App("Tabbit Browser.exe", 19844, "ChatGPT - Tabbit")]
    _wire(monkeypatch, running, resolve=None)

    message, ok = voice_safety.handle_close_app({"name": "browser"})

    assert ok is False
    assert "Tabbit" in message


@pytest.mark.parametrize("name", ["", "   "])
def test_empty_name_asks(monkeypatch, name):
    _wire(monkeypatch, [])
    outcome = ca.close_app(name, grace_s=0.0)
    assert outcome.status == ca.STATUS_AMBIGUOUS
