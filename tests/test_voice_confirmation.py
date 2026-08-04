"""Fase 15 — konfirmasi agent harus bisa dijawab dengan suara (S-2 akar).

`UIAdapter.ask` menunggu event BUS `confirm`/`cancel`, dan satu-satunya
penerbitnya adalah kata yang **DIKETIK** (`confirm`/`konfirmasi`) atau gestur
jempol. Perintah suara "telepon Honbrew" karena itu memaksa Takeda pindah ke
keyboard di tengah percakapan suara. Yang terasa sebagai "terlalu banyak
konfirmasi" bukan banyaknya pertanyaan, melainkan pertanyaan yang tidak bisa
dijawab lewat kanal yang sedang dipakai.

Kanal baru, gerbang lama: suara menerbitkan event BUS yang sama persis.
"""
from __future__ import annotations

import pytest

from jarvis.agent import voice_consent


# ── keputusan kata ────────────────────────────────────────────────────────

@pytest.mark.parametrize("spoken", [
    "ya", "Ya.", "iya", "lanjut", "setuju", "benar", "boleh", "ok", "oke",
    "ya sir", "lanjutkan jarvis",
])
def test_clear_consent_is_recognized(spoken):
    assert voice_consent.decide(spoken) == "confirm"


@pytest.mark.parametrize("spoken", [
    "tidak", "Tidak!", "jangan", "batal", "batalkan", "stop", "nggak",
    "jangan sir",
    # Penolakan dua kata yang lazim diucapkan — sebelumnya jatuh ke None.
    # Melewatkan penolakan tidak berbahaya (aksi tetap tidak jalan), tetapi
    # membuat user merasa tidak didengar.
    "ga usah", "gak usah", "tidak usah", "nanti saja", "jangan dulu",
])
def test_clear_refusal_is_recognized(spoken):
    assert voice_consent.decide(spoken) == "cancel"


def test_false_confirm_is_the_only_unsafe_direction():
    """Asimetri yang disengaja: ragu → None, bukan → confirm.

    Melewatkan persetujuan berarti bertanya sekali lagi. Melewatkan penolakan
    berarti tidak terjadi apa-apa. Menyetujui aksi eksternal yang tidak pernah
    disetujui adalah satu-satunya kesalahan yang tidak bisa ditarik kembali.
    """
    for spoken in ("ya sudah jangan jadi", "boleh tapi nanti saja",
                   "iya kalau memang perlu", "ok sekarang buka spotify"):
        assert voice_consent.decide(spoken) != "confirm"


@pytest.mark.parametrize("spoken", [
    "ya sudah jangan jadi",
    "tidak, maksudku telepon yang satunya",
    "boleh tapi nanti saja",
    "iya kalau memang perlu",
    "ok sekarang buka spotify",
    "benarkah dia sudah menelepon",
    "",
    "   ",
])
def test_ambiguous_or_qualified_speech_is_not_consent(spoken):
    """Hanya ucapan yang seluruhnya berupa jawaban tegas yang dihitung.

    Kalimat berkualifikasi harus jatuh ke percakapan biasa. Menyetujui aksi
    eksternal dari "ya sudah jangan jadi" jauh lebih buruk daripada bertanya
    sekali lagi.
    """
    assert voice_consent.decide(spoken) is None


def test_word_lists_come_from_config(monkeypatch):
    """Daftar kata milik config, bukan kode — bisa disetel tanpa rilis."""
    monkeypatch.setattr(
        voice_consent.config, "get",
        lambda path, default=None: {
            "agent.confirm.voice_yes": ["gaskeun"],
            "agent.confirm.voice_no": ["mundur"],
        }.get(path, default))

    assert voice_consent.decide("gaskeun") == "confirm"
    assert voice_consent.decide("mundur") == "cancel"
    assert voice_consent.decide("ya") is None


def test_decide_never_raises_on_junk():
    for value in (None, 12, object(), b"ya"):
        assert voice_consent.decide(value) is None


# ── gerbang: hanya selama agent bertanya ──────────────────────────────────

def _fake_window(monkeypatch, *, ask_active: bool, reply_consumes=False):
    from jarvis.ui import window as win_mod

    monkeypatch.setattr(win_mod, "_agent_ask_active", lambda: ask_active)

    class _ReplyFlow:
        def handle_utterance(self, _text):
            return reply_consumes

    class _Classified:
        intent = object()
        slots: dict = {}

    class _Router:
        def classify(self, _text):
            return _Classified()

    class _Fake:
        reply_flow = _ReplyFlow()
        router = _Router()
        _pending_close_decision = None
        _pending_voice_proposal_id = None
        # Metode nyata, bukan tiruan — yang diuji adalah kabelnya.
        _handle_spoken_confirmation = (
            win_mod.MainWindow._handle_spoken_confirmation)

        def write_log(self, _text):
            pass

    return win_mod, _Fake()


def _published(monkeypatch):
    from jarvis.core.bus import BUS

    events: list[str] = []
    original = BUS.publish
    monkeypatch.setattr(
        BUS, "publish",
        lambda topic, **kw: (events.append(topic), original(topic, **kw))[0]
        if topic in {"confirm", "cancel"} else original(topic, **kw))
    return events


def test_spoken_yes_confirms_while_agent_is_asking(monkeypatch):
    win_mod, fake = _fake_window(monkeypatch, ask_active=True)
    events = _published(monkeypatch)

    win_mod.MainWindow._voice_intercept(fake, "ya")

    assert events == ["confirm"]


def test_spoken_no_cancels_while_agent_is_asking(monkeypatch):
    win_mod, fake = _fake_window(monkeypatch, ask_active=True)
    events = _published(monkeypatch)

    win_mod.MainWindow._voice_intercept(fake, "batal")

    assert events == ["cancel"]


def test_spoken_yes_outside_the_ask_window_is_ordinary_speech(monkeypatch):
    """Kata setuju tidak boleh melayang menyetujui aksi yang belum ditanyakan."""
    win_mod, fake = _fake_window(monkeypatch, ask_active=False)
    events = _published(monkeypatch)

    win_mod.MainWindow._voice_intercept(fake, "ya")

    assert events == []


def test_active_reply_flow_keeps_its_own_ya(monkeypatch):
    """Dua konteks konfirmasi tidak boleh saling mencuri.

    ReplyFlow hanya melahap ucapan saat state-nya CONFIRM; selama itu "ya"
    miliknya, bukan milik gerbang agent.
    """
    win_mod, fake = _fake_window(monkeypatch, ask_active=True,
                                 reply_consumes=True)
    events = _published(monkeypatch)

    win_mod.MainWindow._voice_intercept(fake, "ya")

    assert events == []


# ── pertanyaannya harus terdengar ─────────────────────────────────────────

def test_confirmation_question_is_spoken_not_just_announced(monkeypatch):
    """User harus MENDENGAR pertanyaannya, bukan sekadar tahu ada pertanyaan.

    Bentuk lama mengucapkan "Saya butuh konfirmasi Anda, sir" dan membuang isi
    pertanyaannya ke panel teks — mustahil dijawab tanpa melihat layar.
    """
    import asyncio

    from jarvis.agent.adapters import ui as ui_adapter

    spoken: list[str] = []

    class _Win:
        def write_log(self, _text):
            pass

        def _speak_line(self, line):
            spoken.append(line)

    monkeypatch.setattr(ui_adapter, "current_window", lambda: _Win())
    monkeypatch.setattr(ui_adapter.config, "get",
                        lambda path, default=None:
                        0.2 if path == "agent.confirm_timeout_s" else default)

    adapter = ui_adapter.UIAdapter.__new__(ui_adapter.UIAdapter)
    answer = asyncio.run(
        adapter.ask("Telepon Honbrew melalui WhatsApp sekarang?",
                    ["Lanjut", "Batal"]))

    assert answer is None                      # timeout, tidak disetujui
    assert any("Honbrew" in line for line in spoken), spoken
