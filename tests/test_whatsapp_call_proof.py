"""Fase 13.1 — panggilan hanya boleh mengaku berhasil bila terbukti (S-1).

``start_call`` dahulu mengklik tombol, menunggu 500 ms, lalu mengembalikan
``{"state": "calling"}`` tanpa membaca ulang halaman. Klik yang mendarat di
elemen salah, akun tanpa fitur calling, atau overlay yang tidak pernah muncul
tetap dilaporkan sukses — lalu model menarasikannya sebagai "sudah saya
telepon". Itulah klaim palsu yang dilaporkan Takeda.

Bukti yang sah hanya satu: keadaan panggilan benar-benar terlihat di halaman
(tombol akhiri panggilan, atau indikator memanggil).
"""
from __future__ import annotations

import json

import pytest

from jarvis.integrations import whatsapp_web as ww


class _Locator:
    def __init__(self, visible: bool):
        self._visible = visible

    def count(self) -> int:
        return 1 if self._visible else 0

    def nth(self, _index: int) -> "_Locator":
        return self

    def is_visible(self) -> bool:
        return self._visible


class FakePage:
    """Halaman yang dapat diskenariokan lewat himpunan selector terlihat."""

    def __init__(self, visible: set[str], *, on_call_click=None):
        self.visible = set(visible)
        self.url = "https://web.whatsapp.com/"
        self.clicks: list[str] = []
        self.waits_ms = 0
        self._on_call_click = on_call_click

    # — API Playwright yang dipakai whatsapp_web —
    def locator(self, selector: str) -> _Locator:
        return _Locator(selector in self.visible)

    def wait_for_timeout(self, ms: int) -> None:
        self.waits_ms += int(ms)

    def goto(self, url: str, **_) -> None:
        self.url = url

    def set_default_navigation_timeout(self, _ms: int) -> None:
        pass

    def set_default_timeout(self, _ms: int) -> None:
        pass

    def get_by_title(self, *_a, **_k):  # pragma: no cover - kontak by phone
        raise AssertionError("jalur pencarian nama tidak dipakai tes ini")

    # — dipakai fake tombol —
    def click_call(self) -> None:
        self.clicks.append("call")
        if self._on_call_click is not None:
            self._on_call_click(self)


class _Button:
    def __init__(self, page: FakePage):
        self._page = page

    def click(self) -> None:
        self._page.click_call()


READY = {"#pane-side"}
CALL_BUTTON = 'button[aria-label*="voice call" i]'
HANGUP = 'button[aria-label*="end call" i]'


@pytest.fixture
def contacts(tmp_path, monkeypatch):
    path = tmp_path / "contacts.json"
    path.write_text(
        json.dumps({"contacts": [
            {"name": "Ibu", "phone": "628123456789", "allowed": True}
        ]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(ww, "_contacts_path", lambda: path)
    return path


class _ConfigShim:
    """Bayangan modul config, hanya untuk namespace whatsapp_web.

    Sengaja TIDAK menambal ``jarvis.core.config.get`` langsung. Menambal atribut
    modul bersama berarti setiap pembaca config di seluruh proses melewati
    lambda tes selama fixture hidup — persis kelas kerapuhan yang membuat T7
    (cache registry tercemar patch aktif) butuh bisect biner untuk ditemukan.
    Rebinding nama di dalam satu modul jauh lebih sempit dan dipulihkan utuh.
    """

    def __init__(self, real, overrides: dict):
        self._real = real
        self._overrides = overrides

    def get(self, path, default=None):
        if path in self._overrides:
            return self._overrides[path]
        return self._real.get(path, default)

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.fixture
def service(monkeypatch):
    """Jalankan operasi langsung di halaman palsu, tanpa Playwright."""
    svc = ww.WhatsAppWebService()

    def _call(function, timeout: float = 60):
        return function(svc._page)

    monkeypatch.setattr(svc, "_call", _call)
    # Bukti panggilan harus cepat gagal dalam tes — jendela nyata 8 detik
    # membuat setiap kasus negatif menunggu sia-sia.
    monkeypatch.setattr(
        ww, "config",
        _ConfigShim(ww.config, {"whatsapp_web.call_confirm_timeout_s": 0.3}),
    )
    return svc


def _wire(svc, page: FakePage, monkeypatch) -> None:
    svc._page = page
    real_wait = ww._wait_visible

    def _wait_visible(target, selectors, timeout_ms: int = 8_000):
        if selectors is ww._CALL_SELECTORS:
            return _Button(target) if CALL_BUTTON in target.visible else None
        return real_wait(target, selectors, timeout_ms)

    monkeypatch.setattr(ww, "_wait_visible", _wait_visible)


def test_call_fails_when_page_never_shows_a_call(contacts, service, monkeypatch):
    """Tombol diklik tetapi panggilan tidak pernah muncul → GAGAL, bukan sukses."""
    page = FakePage(READY | {CALL_BUTTON})     # klik tidak mengubah apa pun
    _wire(service, page, monkeypatch)

    with pytest.raises(ww.WhatsAppError) as excinfo:
        service.start_call("Ibu")

    assert page.clicks == ["call"], "tombol tetap harus diklik"
    assert "tidak" in str(excinfo.value).casefold()


def test_call_succeeds_only_with_visible_call_state(contacts, service,
                                                    monkeypatch):
    """Overlay panggilan muncul setelah klik → state terbukti."""

    def _on_click(page: FakePage) -> None:
        page.visible.add(HANGUP)

    page = FakePage(READY | {CALL_BUTTON}, on_call_click=_on_click)
    _wire(service, page, monkeypatch)

    result = service.start_call("Ibu")

    assert result["state"] in {"ringing", "in_call"}
    assert result["contact"] == "Ibu"
    assert result["proven"] is True


def test_failure_message_claims_only_what_is_knowable(contacts, service,
                                                      monkeypatch):
    """Gagal bukti ≠ tidak ada panggilan. Jangan menukar satu klaim palsu
    dengan klaim palsu arah sebaliknya.

    Bukti bisa gagal karena selector tidak cocok dengan DOM WhatsApp, bukan
    karena panggilan tidak dimulai. Bila kliknya ternyata benar-benar
    menelepon, HP lawan bicara berdering sementara kita melapor gagal.
    Memutusnya otomatis mustahil: tombol akhiri panggilan dicari dengan
    selector yang sama yang baru saja terbukti tidak cocok.

    Yang tersisa dan jujur: nyatakan bahwa keadaannya TIDAK DIKETAHUI, dan
    suruh user memeriksa jendelanya sendiri.
    """
    page = FakePage(READY | {CALL_BUTTON})
    _wire(service, page, monkeypatch)

    with pytest.raises(ww.WhatsAppError) as excinfo:
        service.start_call("Ibu")

    message = str(excinfo.value).casefold()
    assert "tidak ada panggilan" not in message, (
        "kita tidak bisa tahu itu — jangan mengklaimnya")
    assert "periksa" in message or "cek" in message
    assert "whatsapp" in message


def test_call_never_reports_the_unproven_calling_state(contacts, service,
                                                       monkeypatch):
    """State 'calling' lama tidak boleh terbit dari klik semata."""
    page = FakePage(READY | {CALL_BUTTON})
    _wire(service, page, monkeypatch)

    with pytest.raises(ww.WhatsAppError):
        service.start_call("Ibu")

    assert service._last_status.get("state") != "calling"


def test_answer_requires_proof_too(service, monkeypatch):
    page = FakePage({'button[aria-label*="answer" i]'})
    service._page = page

    real_wait = ww._wait_visible

    def _wait_visible(target, selectors, timeout_ms: int = 8_000):
        if selectors is ww._ANSWER_SELECTORS:
            return _Button(target)
        return real_wait(target, selectors, timeout_ms)

    monkeypatch.setattr(ww, "_wait_visible", _wait_visible)

    with pytest.raises(ww.WhatsAppError):
        service.answer_call()


def test_call_tool_does_not_dress_failure_as_success(monkeypatch):
    """Panggilan tak terbukti → tool gagal, bukan sukses berpesan halus."""
    import asyncio

    from jarvis.agent.tools.whatsapp_web import WhatsAppCall

    class _Svc:
        @staticmethod
        def start_call(_contact):
            raise ww.WhatsAppError("Panggilan tidak terbukti aktif.")

    monkeypatch.setattr(ww.WhatsAppWebService, "get", staticmethod(lambda: _Svc))

    result = asyncio.run(WhatsAppCall().run(contact="Ibu"))

    assert result.ok is False
    assert "terbukti" in str(result.error).casefold()


def test_call_display_separates_call_state_from_audio_bridge(monkeypatch):
    """Bridge audio mati tidak boleh terbaca sebagai panggilan yang cacat.

    Keduanya fakta terpisah: panggilan tersambung, tetapi Jarvis tidak bisa
    bicara di dalamnya. Kalimat yang menggabungkannya membuat model menyimpulkan
    salah satu dari dua arah yang sama-sama keliru.
    """
    import asyncio

    from jarvis.agent.tools import whatsapp_web as tool_mod
    from jarvis.agent.tools.whatsapp_web import WhatsAppCall

    class _Svc:
        @staticmethod
        def start_call(_contact):
            return {"state": "ringing", "contact": "Ibu", "proven": True}

    monkeypatch.setattr(ww.WhatsAppWebService, "get", staticmethod(lambda: _Svc))
    monkeypatch.setattr(
        tool_mod, "_start_bridge",
        lambda: {"active": False, "error": "virtual audio tidak siap"},
        raising=False,
    )

    result = asyncio.run(WhatsAppCall().run(contact="Ibu"))

    assert result.ok is True
    display = result.display.casefold()
    assert "ibu" in display
    # Keadaan panggilan dinyatakan, dan ketidakmampuan bicara dinyatakan juga.
    assert "berdering" in display or "ringing" in display
    assert "tidak bisa bicara" in display or "audio" in display


def test_agent_prompt_forbids_unproven_success_claims():
    """Fase 13.4 — larangan klaim tanpa bukti harus ada di prompt agent berat.

    Lane suara cepat sudah memilikinya (voice_native_tools). Agent beratlah
    yang menarasikan hasil panggilan, dan justru di sanalah larangan itu hilang.
    """
    from pathlib import Path

    text = Path("jarvis/agent/prompts/system.md").read_text(
        encoding="utf-8").casefold()

    assert "jangan" in text and "bukti" in text
    assert "aksi eksternal" in text
