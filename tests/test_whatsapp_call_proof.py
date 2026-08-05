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
    """Aksi panggilan suara langsung terlihat — menu tidak perlu dibuka.

    S-18 memecah kontrol panggilan menjadi PEMBUKA MENU dan AKSI SUARA; yang
    disadap di sini adalah aksinya.
    """
    svc._page = page
    real_wait = ww._wait_visible

    def _wait_visible(target, selectors, timeout_ms: int = 8_000):
        if selectors is ww._VOICE_CALL_SELECTORS:
            return _Button(target) if CALL_BUTTON in target.visible else None
        if selectors is ww._CALL_MENU_SELECTORS:
            return None
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


# ── bukti DOM sungguhan (probe read-only, 2026-08-05) ─────────────────────

def test_call_selectors_match_the_real_indonesian_label():
    """S-16 — DOM WhatsApp Web sungguhan memakai aria-label "Telepon".

    Diambil dari `scripts/whatsapp_selector_probe.py` terhadap profil Chrome
    Jarvis yang benar-benar login (chat honbrew terbuka, state `ready`).
    Satu-satunya tombol panggilan yang ada:

        {"aria_label": "Telepon", "data_icon": "", "title": "", "tag": "button"}

    `_CALL_SELECTORS` lama hanya mencari "voice call" dan "panggilan suara",
    jadi TIDAK ADA yang cocok: `start_call` selalu gagal di
    "Tombol panggilan suara tidak ditemukan" sebelum bukti Fase 13 sempat
    berperan. Panggilan tidak pernah benar-benar dimulai.
    """
    import re

    from jarvis.integrations import whatsapp_web as ww

    def _matches(label: str) -> bool:
        for selector in ww._CALL_SELECTORS:
            # S-28 mengikat selector ke `#main`; parser ikut menyesuaikan.
            m = re.fullmatch(
                r'(?:#main )?button\[aria-label([*^]?)="([^"]+)" i\]',
                selector)
            if not m:
                continue
            op, value = m.groups()
            if op == "*" and value.casefold() in label.casefold():
                return True
            if op == "" and value.casefold() == label.casefold():
                return True
        return False

    assert _matches("Telepon"), (
        "label DOM sungguhan tidak dikenali — panggilan mustahil dimulai")
    # Bahasa Inggris tetap didukung; akun berbeda memakai locale berbeda.
    assert _matches("Voice call")


def test_call_selectors_do_not_grab_a_video_call():
    """Melonggarkan selector tidak boleh membuat Jarvis menelepon video."""
    import re

    from jarvis.integrations import whatsapp_web as ww

    for selector in ww._CALL_SELECTORS:
        m = re.fullmatch(r'(?:#main )?button\[aria-label([*^]?)="([^"]+)" i\]',
                         selector)
        if m and m.group(1) == "*":
            assert "video" not in m.group(2).casefold()


# ── S-18: "Telepon" adalah PEMBUKA MENU, bukan tombol panggil ─────────────

def test_voice_call_action_is_distinct_from_the_menu_opener():
    """Probe DOM sungguhan (2026-08-05, saat Takeda mengklik "Telepon"):

        {"aria_label": "Telepon"}        <- pembuka menu
        {"aria_label": "Telepon video"}
        {"aria_label": "Telepon suara"}  <- aksi panggilan suara

    Perbaikan S-16 mencocokkan "Telepon" persis, jadi `start_call` mengklik
    PEMBUKA MENU lalu menunggu bukti panggilan yang tidak akan pernah datang.
    Menu terbuka, panggilan tidak pernah dimulai \u2014 HP lawan bicara diam.
    Terbukti di lapangan: "hp honbrew tidak berdering".

    Dua kelompok selector harus terpisah, dan yang menelepon adalah aksinya.
    """
    from jarvis.integrations import whatsapp_web as ww

    assert hasattr(ww, "_VOICE_CALL_SELECTORS")
    assert hasattr(ww, "_CALL_MENU_SELECTORS")

    joined = " ".join(ww._VOICE_CALL_SELECTORS).casefold()
    assert "telepon suara" in joined, "label aksi sungguhan tidak dikenali"
    assert "video" not in joined, "jangan pernah memilih panggilan video"


def test_menu_opener_alone_is_never_treated_as_a_started_call(contacts,
                                                              service,
                                                              monkeypatch):
    """Klik pembuka menu saja tidak boleh menghasilkan sukses."""
    page = FakePage(READY | {'button[aria-label="Telepon" i]'})
    service._page = page

    real_wait = ww._wait_visible
    clicks: list[str] = []

    class _Opener:
        def click(self):
            clicks.append("menu")

    def _wait_visible(target, selectors, timeout_ms: int = 8_000):
        if selectors is ww._VOICE_CALL_SELECTORS:
            return None                      # menu tidak pernah menampilkannya
        if selectors is ww._CALL_MENU_SELECTORS:
            return _Opener()
        return real_wait(target, selectors, timeout_ms)

    monkeypatch.setattr(ww, "_wait_visible", _wait_visible)

    with pytest.raises(ww.WhatsAppError):
        service.start_call("Ibu")

    assert clicks == ["menu"], "menu dibuka, tetapi tidak ada panggilan"


def test_call_flow_opens_the_menu_then_picks_voice(contacts, service,
                                                   monkeypatch):
    """Alur benar: buka menu, pilih "Telepon suara", baru buktikan."""
    MENU = 'button[aria-label="Telepon" i]'
    VOICE = 'button[aria-label="Telepon suara" i]'
    clicks: list[str] = []

    page = FakePage(READY | {MENU})
    service._page = page

    class _Click:
        def __init__(self, label, on_click=None):
            self.label = label
            self._on_click = on_click

        def click(self):
            clicks.append(self.label)
            if self._on_click:
                self._on_click()

    def _open_menu():
        page.visible.add(VOICE)

    def _start_call():
        page.visible.add(HANGUP)

    real_wait = ww._wait_visible

    def _wait_visible(target, selectors, timeout_ms: int = 8_000):
        if selectors is ww._CALL_MENU_SELECTORS:
            return _Click("menu", _open_menu) if MENU in target.visible else None
        if selectors is ww._VOICE_CALL_SELECTORS:
            return _Click("voice", _start_call) if VOICE in target.visible else None
        return real_wait(target, selectors, timeout_ms)

    monkeypatch.setattr(ww, "_wait_visible", _wait_visible)

    result = service.start_call("Ibu")

    assert clicks == ["menu", "voice"], clicks
    assert result["state"] in {"ringing", "in_call"}
    assert result["proven"] is True


def test_direct_voice_button_skips_the_menu(contacts, service, monkeypatch):
    """Bila aksi suara sudah terlihat, jangan buka menu lebih dulu."""
    VOICE = 'button[aria-label="Telepon suara" i]'
    clicks: list[str] = []

    page = FakePage(READY | {VOICE})
    service._page = page

    class _Click:
        def __init__(self, label):
            self.label = label

        def click(self):
            clicks.append(self.label)
            page.visible.add(HANGUP)

    real_wait = ww._wait_visible

    def _wait_visible(target, selectors, timeout_ms: int = 8_000):
        if selectors is ww._VOICE_CALL_SELECTORS:
            return _Click("voice") if VOICE in target.visible else None
        if selectors is ww._CALL_MENU_SELECTORS:
            raise AssertionError("menu tidak perlu dibuka")
        return real_wait(target, selectors, timeout_ms)

    monkeypatch.setattr(ww, "_wait_visible", _wait_visible)

    assert service.start_call("Ibu")["proven"] is True
    assert clicks == ["voice"]


# ── S-19: label bukti panggilan dari DOM sungguhan ────────────────────────

_LIVE_CALL_LABELS = (
    # Terekam probe linimasa 2026-08-05 saat panggilan Takeda BERDERING,
    # detik ke-16 dan ke-17, pages=1 (overlay di halaman yang sama):
    "Akhiri telepon",
    "Kontrol telepon",
    "Pindahkan ke jendela baru",
    "Izinkan akses kamera untuk beralih ke video",
)


def _matches(selectors, label: str) -> bool:
    import re

    for selector in selectors:
        m = re.fullmatch(r'(?:button)?\[aria-label([*^]?)="([^"]+)" i\]',
                         selector)
        if not m:
            continue
        op, value = m.groups()
        if op == "*" and value.casefold() in label.casefold():
            return True
        if op == "" and value.casefold() == label.casefold():
            return True
    return False


def test_hangup_selectors_match_the_real_live_call_label():
    """S-19 — WhatsApp Indonesia memakai "telepon", bukan "panggilan".

    `_HANGUP_SELECTORS` mencari "akhiri panggilan" / "end call" /
    data-icon="call-end". DOM sungguhan saat panggilan hidup memberi
    "Akhiri telepon". Tidak satu pun cocok, sehingga:

      * `_prove_call_started` selalu gagal \u2192 panggilan yang BENAR-BENAR
        berdering dilaporkan tidak terbukti;
      * `_status_on_page` tidak pernah melaporkan `in_call`;
      * `whatsapp_hangup` tidak pernah menemukan tombolnya \u2014 Jarvis tidak
        bisa menutup panggilan yang ia mulai sendiri.
    """
    from jarvis.integrations import whatsapp_web as ww

    assert _matches(ww._HANGUP_SELECTORS, "Akhiri telepon")
    # Bahasa Inggris tetap didukung.
    assert _matches(ww._HANGUP_SELECTORS, "End call")


def test_call_proof_selectors_do_not_match_an_idle_chat():
    """Bukti harus MEMBEDAKAN. Label yang selalu ada bukan bukti.

    Ini yang menjaga agar melonggarkan selector tidak berubah menjadi
    "selalu terbukti" \u2014 kegagalan arah sebaliknya dari S-1.
    """
    from jarvis.integrations import whatsapp_web as ww

    idle_labels = ("Telepon", "Telepon suara", "Telepon video",
                   "Pesan suara", "Cari", "Menu")
    for label in idle_labels:
        assert not _matches(ww._HANGUP_SELECTORS, label), label
        assert not _matches(ww._RINGING_SELECTORS, label), label


def test_ringing_selectors_recognise_the_live_call_controls():
    from jarvis.integrations import whatsapp_web as ww

    assert _matches(ww._RINGING_SELECTORS, "Kontrol telepon")


def test_status_reports_in_call_from_the_real_label(service, monkeypatch):
    """`_status_on_page` ikut pulih: label yang sama yang dipakainya."""
    page = FakePage(READY | {'button[aria-label="Akhiri telepon" i]'})

    status = ww.WhatsAppWebService._status_on_page(page)

    assert status["state"] == "in_call"


# ── S-26: dua kegagalan nyata dari log sesi Takeda ────────────────────────

def test_a_loading_page_is_waited_for_not_rejected(contacts, service,
                                                   monkeypatch):
    """Log sesi 2026-08-05 21:29:

        "WhatsApp Web belum siap (status: loading)."

    Halaman masih memuat dan `_require_ready` langsung menyerah. WhatsApp Web
    butuh beberapa detik untuk siap; menyerah pada detik pertama berarti
    perintah pertama setelah Jarvis menyala hampir selalu gagal.
    """
    page = FakePage(set())          # belum ada #pane-side: masih loading
    service._page = page

    ticks = {"n": 0}
    real_wait_timeout = page.wait_for_timeout

    def _tick(ms):
        real_wait_timeout(ms)
        ticks["n"] += 1
        if ticks["n"] >= 3:         # setelah beberapa detik, halaman siap
            page.visible.add("#pane-side")

    page.wait_for_timeout = _tick

    ww.WhatsAppWebService._await_ready(page, timeout_s=5.0)

    assert ww.WhatsAppWebService._status_on_page(page)["state"] == "ready"


def test_waiting_for_ready_still_gives_up_eventually(contacts, service):
    """Menunggu tidak boleh berarti menggantung selamanya."""
    page = FakePage(set())

    with pytest.raises(ww.WhatsAppError) as excinfo:
        ww.WhatsAppWebService._await_ready(page, timeout_s=0.2)

    assert "siap" in str(excinfo.value).casefold()


def test_login_required_is_reported_immediately_not_waited_out(contacts):
    """QR belum dipindai bukan keadaan yang akan membaik dengan menunggu."""
    page = FakePage({"canvas"})

    with pytest.raises(ww.WhatsAppError) as excinfo:
        ww.WhatsAppWebService._await_ready(page, timeout_s=5.0)

    assert "qr" in str(excinfo.value).casefold()


def test_a_missing_voice_option_records_what_was_visible(contacts, service,
                                                         monkeypatch):
    """Log sesi 2026-08-05 21:29:

        "Menu panggilan terbuka tetapi pilihan panggilan suara tidak ditemukan."

    Padahal probe membuktikan `button[aria-label="Telepon suara" i]` ADA di DOM
    sungguhan. Menebak sebabnya sudah dua kali meleset di siklus ini, jadi
    kegagalan ini harus MEREKAM apa yang benar-benar terlihat saat itu \u2014 bukan
    menyisakan tiga kandidat terbuka lagi.
    """
    MENU = 'button[aria-label="Telepon" i]'
    seen: list = []

    page = FakePage(READY | {MENU})
    page.evaluate = lambda _script: [{"aria_label": "Telepon video"}]
    service._page = page

    monkeypatch.setattr(
        ww._logger, "warning",
        lambda event, **kw: seen.append({"event": event, **kw}))

    real_wait = ww._wait_visible

    class _Opener:
        def click(self):
            pass

    def _wait_visible(target, selectors, timeout_ms: int = 8_000):
        if selectors is ww._VOICE_CALL_SELECTORS:
            return None
        if selectors is ww._CALL_MENU_SELECTORS:
            return _Opener()
        return real_wait(target, selectors, timeout_ms)

    monkeypatch.setattr(ww, "_wait_visible", _wait_visible)

    with pytest.raises(ww.WhatsAppError):
        service.start_call("Ibu")

    assert any("voice_option_missing" in str(item.get("event", ""))
               for item in seen), seen


# ── S-28: "Telepon" yang diklik ternyata TAB SIDEBAR, bukan tombol chat ───

def test_call_controls_are_scoped_to_the_open_conversation():
    """Log `whatsapp.voice_option_missing` (2026-08-05 22:03) menyebutkan
    label yang terlihat saat kegagalan:

        Chat, Telepon, Status, Saluran, Komunitas, Meta AI, Media, Anda,
        Panel telepon (tersembunyi), Telepon baru, Cari nama atau nomor,
        Daftar chat, ...

    Itu seluruhnya RAIL NAVIGASI KIRI. Tidak ada satu pun kontrol header chat.
    Jadi `button[aria-label="Telepon"]` yang dicocokkan S-16 adalah **tab
    Telepon di sidebar**, bukan tombol panggilan di dalam percakapan —
    mengkliknya berpindah ke daftar panggilan, tempat "Telepon suara" memang
    tidak ada.

    Selector kontrol panggilan karena itu harus terikat pada percakapan yang
    terbuka (`#main`), bukan pada seluruh halaman.
    """
    from jarvis.integrations import whatsapp_web as ww

    for selector in ww._CALL_MENU_SELECTORS + ww._VOICE_CALL_SELECTORS:
        assert selector.startswith("#main"), selector


def test_sidebar_calls_tab_is_no_longer_matched():
    """Tab sidebar berada di luar #main, jadi ia tidak lagi terjangkau."""
    from jarvis.integrations import whatsapp_web as ww

    page = FakePage(READY | {'button[aria-label="Telepon" i]'})

    assert ww._first_visible(page, ww._CALL_MENU_SELECTORS) is None
