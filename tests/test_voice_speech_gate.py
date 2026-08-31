"""Test gerbang ucapan N-1: hasil tugas tidak memotong giliran suara.

Pola modular — tidak ada dependency audio/network/browser. Fake legacy module
dengan subclass fresh tiap test supaya _jarvis_speech_gate marker tidak bocor.
Batas timeout config dibuat agresif untuk kecepatan test yang deterministik.
"""
from __future__ import annotations

import asyncio
import threading
import time
import types

from jarvis.core import config
from jarvis.integrations import voice_speech, voice_speech_gate


class _FakeQueue:
    """Queue kosong tanpa state internal yang rumit."""

    def __init__(self) -> None:
        self._empty = True

    def empty(self) -> bool:
        return self._empty

    def put_nowait(self, _: object) -> None:
        self._empty = False


class _FakeLive:
    """JarvisLive fake minimal untuk verifikasi gerbang.

    ``speak`` wajib ada: ``install()`` membaca ``cls.speak`` dan mengembalikan
    ``False`` bila tidak callable (``voice_speech_gate.py:117-120``). Tanpa
    metode ini, install menolak memasang gerbang, lalu tes memanggil
    ``live.speak(...)`` pada metode yang memang tidak pernah ada — empat
    kegagalan ``AttributeError`` berasal dari sini, bukan dari produksi.
    """

    def __init__(self) -> None:
        self.audio_in_queue: asyncio.Queue | _FakeQueue = asyncio.Queue()
        self._is_speaking = False
        self.speak_calls: list[str] = []

    def set_speaking(self, v: bool) -> None:
        self._is_speaking = v

    def speak(self, text: str) -> None:
        self.speak_calls.append(str(text or ""))

    def original_speak(self, text: str) -> None:
        self.speak_calls.append(str(text or ""))


def _make_legacy():
    mod = types.ModuleType("fake_live_module")

    class _Live(_FakeLive):
        pass

    mod.JarvisLive = _Live
    return mod


def _make_drainable_legacy():
    """Live yang lane-nya bisa dikuras dari luar.

    Dua keadaan berurutan diperlukan untuk menguji drain, dan keduanya tidak
    bisa dicapai dengan satu tombol:

    1. lane **sibuk saat ``speak()`` dipanggil** — supaya teks ditahan, bukan
       langsung dikirim;
    2. lane **idle sesudahnya** — supaya ``_await_boundary`` bisa mengirim.

    Kesibukan dibuat lewat antrean, bukan ``_is_speaking``: ``_await_boundary``
    mengevaluasi ``not _lane_busy(live) and turn_boundary_safe(live)`` dengan
    short-circuit, jadi selama lane sibuk ``turn_boundary_safe`` **tidak pernah
    dipanggil** dan tidak bisa dipakai untuk melepaskan lane. Mengosongkan
    antrean dari luar adalah satu-satunya jalan keluar dari lingkaran itu.
    """
    mod = types.ModuleType("fake_live_module")

    class _Live(_FakeLive):
        def __init__(self) -> None:
            super().__init__()
            # Antrean penuh = lane sibuk, sehingga speak() menahan teks.
            self.audio_in_queue = _FakeQueue()
            self.audio_in_queue._empty = False

        def drain_lane(self) -> None:
            """Kosongkan antrean → lane idle, drain bisa mengirim."""
            self.audio_in_queue._empty = True

    mod.JarvisLive = _Live
    return mod


def test_install_idempotent_dan_aman():
    """install() harus idempoten dan tidak boleh crash bila structure berubah."""
    legacy = _make_legacy()
    assert voice_speech_gate.install(legacy) is True
    assert getattr(legacy.JarvisLive, "_jarvis_speech_gate", False) is True

    # Panggil kedua → tetap True, tidak error
    assert voice_speech_gate.install(legacy) is True

    # No side effect pada instance
    live = legacy.JarvisLive()
    assert isinstance(live.audio_in_queue, asyncio.Queue)


def test_install_fallback_aman_bila_no_class(monkeypatch):
    """Modul tanpa JarvisLive → return False, tidak crash."""
    mod = types.ModuleType("broken")
    result = voice_speech_gate.install(mod)
    assert result is False
    assert not getattr(mod, "_jarvis_speech_gate", False)


def test_speak_bypassbila_delivery_scope_active(monkeypatch):
    """Ucapan ber-scope (ack/final/konfirmasi) → bypass gate, langsung speak."""
    # ``voice_speech.py`` tidak mengimpor config sama sekali (nol penyebutan).
    # Yang membaca konfigurasi adalah ``voice_speech_gate``, jadi patch harus
    # diarahkan ke sana — menimpa ``voice_speech.config`` tidak berdampak apa
    # pun pada kecepatan test ini.
    monkeypatch.setattr(voice_speech_gate.config, "get",
                        lambda k, d=None: {"voice.playback.poll_s": 0.005}.get(k, d))

    legacy = _make_legacy()
    voice_speech_gate.install(legacy)

    live = legacy.JarvisLive()
    live.set_speaking(True)          # busy tapi scope-boundak bypass gate

    # Mock delivery scope active
    from unittest.mock import patch

    # ``speak`` mengimpor nama ini secara lambat dari ``voice_speech``
    # (voice_speech_gate.py:128), jadi yang harus ditimpa adalah atribut di
    # ``voice_speech`` — bukan di ``voice_speech_gate``.
    with patch("jarvis.integrations.voice_speech.current_delivery_scope",
               return_value="mock-scope"):
        # Langsung ke original_speak, tidak ditahan
        live.speak("scope text")

    assert "scope text" in live.speak_calls


def test_hold_until_boundary_with_timeout_safe(monkeypatch):
    """Hold teks sampai boundary aman; timeout fallback aman → text tetap dikirim."""
    events = []

    class _CaptureLog:
        def warning(self, event: str, **fields: object) -> None:
            events.append((event, fields))

        def info(self, event: str, **fields: object) -> None:
            # ``install()`` memanggil ``_logger.info("...installed")`` di baris
            # 136. Logger pengganti yang hanya punya ``warning`` membuat seluruh
            # pemasangan gagal dengan AttributeError sebelum tes dimulai.
            events.append((event, fields))

    monkeypatch.setattr(voice_speech_gate, "_logger", _CaptureLog())

    # Timeout cepat + poll cepat
    monkeypatch.setattr(config, "get",
                        lambda k, d=None: {
                            "voice.speech_gate.max_hold_s": 0.15,
                            "voice.speech_gate.poll_s": 0.01,
                        }.get(k, d))

    legacy = _make_legacy()
    voice_speech_gate.install(legacy)

    live = legacy.JarvisLive()
    live.set_speaking(True)          # simulate still speaking

    # Call dengan teks yang akan dihold
    live.speak("should be held")

    # Seharusnya belum terkirim segera (held dalam pending)
    assert "should be held" not in live.speak_calls

    # Biarkan timeout terjadi
    time.sleep(0.2)

    # Setelah timeout, speech tetap dikirim (fallback safety)
    assert "should be held" in live.speak_calls

    # Harus ada warning boundary_timeout
    names = [e[0] for e in events]
    assert any("boundary_timeout" in n for n in names)


def test_fifo_ordering_preserved(monkeypatch):
    """Urutan FIFO: item pertama dikirim dulu, tidak ada dropout."""
    events = []

    class _CaptureLog:
        def warning(self, event: str, **fields: object) -> None:
            events.append((event, fields))

        def info(self, event: str, **fields: object) -> None:
            events.append((event, fields))

    monkeypatch.setattr(voice_speech_gate, "_logger", _CaptureLog())

    # Timeout lama agar urutan terjaga
    monkeypatch.setattr(config, "get",
                        lambda k, d=None: {
                            "voice.speech_gate.max_hold_s": 5.0,
                            "voice.speech_gate.poll_s": 0.02,
                        }.get(k, d))

    legacy = _make_drainable_legacy()
    voice_speech_gate.install(legacy)

    live = legacy.JarvisLive()      # lane sibuk sejak awal (antrean penuh)

    # Multiple concurrent sends
    live.speak("first")
    live.speak("second")
    live.speak("third")

    # Belum terkirim semua karena holding
    assert len(live.speak_calls) < 3

    # Simulate boundary safe
    from unittest.mock import patch

    # ``turn_boundary_safe`` hidup di ``voice_speech`` (baris 219), dan
    # ``_await_boundary`` memanggilnya sebagai ``voice_speech.turn_boundary_safe``.
    # Menempelkannya ke ``voice_speech_gate`` tidak mengubah apa pun yang dibaca
    # gerbang, sehingga drain tidak pernah melihat batas aman.
    with patch.object(voice_speech, 'turn_boundary_safe', return_value=True):
        live.drain_lane()           # lane idle → drain bisa mengirim
        time.sleep(0.5)  # allow drain to happen

    # All three should be sent in order
    assert live.speak_calls == ["first", "second", "third"]


def test_install_ditolak_bila_kelas_tanpa_speak():
    """Kelas tanpa ``speak`` → ``install`` menolak, bukan membungkus sembarangan.

    Penolakan ini tidak punya penguji sebelum 2026-08-31: mutan yang menghapus
    pemeriksaan ``callable(original_speak)`` (baris 118) **selamat** karena
    tidak satu pun tes memanggil ``install`` pada kelas seperti ini.
    """
    mod = types.ModuleType("no_speak")

    class _NoSpeak:
        pass

    mod.JarvisLive = _NoSpeak

    assert voice_speech_gate.install(mod) is False
    assert getattr(_NoSpeak, "_jarvis_speech_gate", False) is False


def test_hanya_satu_drainer_yang_mengirim(monkeypatch):
    """Sepuluh hold bersamaan → tepat satu pengirim aktif, tidak ada yang ganda.

    ``test_concurrent_holds_safe`` hanya memeriksa *isi akhir* antrean, dan
    penghapusan penjaga ``_draining`` (baris 69-71) tidak mengubah isi itu —
    mutannya selamat dengan sepuluh thread mengirim serentak. Yang
    membedakan adalah **konkurensi pengiriman**, diukur di sini dengan
    penghitung masuk/aktif.

    Diukur 2026-08-31, 5/5 run: produksi bersih ``max_concurrent == 1``,
    dengan penjaga dihapus ``max_concurrent == 10``.
    """
    monkeypatch.setattr(config, "get",
                        lambda k, d=None: {
                            "voice.speech_gate.max_hold_s": 5.0,
                            "voice.speech_gate.poll_s": 0.02,
                        }.get(k, d))

    class _CountingLive(_FakeLive):
        """Menghitung pengirim yang aktif bersamaan; kirim diperlambat."""

        def __init__(self) -> None:
            super().__init__()
            self.max_concurrent = 0
            self._active = 0
            self._counter_lock = threading.Lock()
            self._send_lock = threading.Lock()

        # Penghitung harus di ``speak``, BUKAN di ``original_speak``:
        # ``install`` menangkap ``getattr(cls, "speak")`` sebagai
        # ``original_speak`` (voice_speech_gate.py:117), jadi yang dipanggil
        # gerbang saat mengirim adalah fungsi ``speak`` yang didefinisikan di
        # sini. Menaruh penghitung di ``original_speak`` membuatnya tak pernah
        # berjalan — terukur di sini pada 2026-08-31: ``max_concurrent``
        # terbaca 0 sementara sepuluh teks sudah terkirim.
        def speak(self, text: str) -> None:
            with self._counter_lock:
                self._active += 1
                self.max_concurrent = max(self.max_concurrent, self._active)
            with self._send_lock:
                # Jendela lebar: tanpa penjaga, sepuluh thread masuk bersamaan.
                time.sleep(0.05)
                self.speak_calls.append(str(text or ""))
            with self._counter_lock:
                self._active -= 1

    class _Held(_CountingLive):
        def __init__(self) -> None:
            super().__init__()
            self.audio_in_queue = _FakeQueue()
            self.audio_in_queue._empty = False      # lane sibuk sejak awal

        def drain_lane(self) -> None:
            self.audio_in_queue._empty = True

    mod = types.ModuleType("counting_live")
    mod.JarvisLive = _Held
    voice_speech_gate.install(mod)

    live = mod.JarvisLive()
    for i in range(10):
        live.speak(f"task-{i}")

    from unittest.mock import patch

    with patch.object(voice_speech, "turn_boundary_safe", return_value=True):
        live.drain_lane()
        time.sleep(1.5)

    assert live.speak_calls == [f"task-{i}" for i in range(10)]
    assert live.max_concurrent == 1, (
        f"pengirim serentak: {live.max_concurrent} — penjaga drainer tunggal "
        f"tidak berjalan"
    )


def test_kegagalan_kirim_dicatat_bukan_dilempar(monkeypatch):
    """TTS gagal di jalur drain → dicatat, caller tidak kena exception.

    ``test_error_handling_graceful`` menimpa ``original_speak`` pada
    *instance*, padahal ``install`` menangkap ``original_speak`` dari *kelas*.
    Akibatnya speak yang rusak itu tidak pernah dipanggil, tes tidak menegaskan
    apa pun, dan mutan yang mengganti penanganan ``except`` dengan ``raise``
    (baris 85-88) **selamat**. Di sini kegagalan ditempatkan di kelas, dan
    ``send_failed`` ditegaskan benar-benar tercatat.

    Catatan jujur: jalur lane-idle sengaja **tidak** menelan exception —
    ``hold_or_send`` memanggil ``original_speak`` langsung agar perilaku lama
    tetap utuh. Perlindungan ini hanya berlaku bagi teks yang ditahan.
    """
    monkeypatch.setattr(config, "get",
                        lambda k, d=None: {
                            "voice.speech_gate.max_hold_s": 5.0,
                            "voice.speech_gate.poll_s": 0.02,
                        }.get(k, d))

    events: list[tuple[str, dict]] = []

    class _CaptureLog:
        def warning(self, event: str, **fields: object) -> None:
            events.append((event, fields))

        def info(self, event: str, **fields: object) -> None:
            events.append((event, fields))

    monkeypatch.setattr(voice_speech_gate, "_logger", _CaptureLog())

    class _Raising:
        def __init__(self) -> None:
            self.audio_in_queue = _FakeQueue()
            self.audio_in_queue._empty = False      # sibuk → teks ditahan
            self._is_speaking = False

        def set_speaking(self, v: bool) -> None:
            self._is_speaking = v

        def drain_lane(self) -> None:
            self.audio_in_queue._empty = True

        def speak(self, text: str) -> None:
            raise RuntimeError("simulated TTS error")

    mod = types.ModuleType("raising_live")
    mod.JarvisLive = _Raising
    assert voice_speech_gate.install(mod) is True

    live = _Raising()
    live.speak("risky text")                 # ditahan, belum dikirim

    from unittest.mock import patch

    with patch.object(voice_speech, "turn_boundary_safe", return_value=True):
        live.drain_lane()                    # lane idle → drain mengirim → gagal
        time.sleep(0.6)

    names = [e[0] for e in events]
    assert "voice.speech_gate.send_failed" in names, names


def test_lane_busy_logic():
    """_lane_busy benar: true jika _is_speaking atau queue tidak kosong."""
    legacy = _make_legacy()
    live = legacy.JarvisLive()

    # Empty queue + not speaking = idle
    assert voice_speech_gate._lane_busy(live) is False

    # Speaking = busy
    live.set_speaking(True)
    assert voice_speech_gate._lane_busy(live) is True
    live.set_speaking(False)

    # Non-empty queue = busy
    live.audio_in_queue = _FakeQueue()
    live.audio_in_queue._empty = False
    assert voice_speech_gate._lane_busy(live) is True


def test_error_handling_graceful():
    """Original speak failure → log warning, tetap lanjut drain, tidak crash."""

    class BrokenSpeak(Exception):
        """Simulasi speak exception."""
        pass

    legacy = _make_legacy()
    voice_speech_gate.install(legacy)

    live = legacy.JarvisLive()
    live.set_speaking(True)

    # Make original_speak raise
    def broken_original(self, text):
        raise BrokenSpeak("simulated TTS error")

    original_speak = live.original_speak
    live.original_speak = lambda t: broken_original(live, t)

    # Should not crash
    live.speak("risky text")

    # After timeout, it will try and fail gracefully
    time.sleep(0.2)

    # System should continue, not crash


def test_concurrent_holds_safe():
    """Multiple concurrent holds → single drainer, no duplicates."""
    legacy = _make_drainable_legacy()
    voice_speech_gate.install(legacy)

    live = legacy.JarvisLive()      # lane sibuk sejak awal (antrean penuh)

    # Rapid concurrent calls
    for i in range(10):
        live.speak(f"task-{i}")

    # All should be queued, but only one drainer
    assert len(live.speak_calls) == 0  # all held initially

    # After drain, all should be present exactly once
    from unittest.mock import patch

    with patch.object(voice_speech, 'turn_boundary_safe', return_value=True):
        live.drain_lane()           # lane idle → drain bisa mengirim
        time.sleep(0.3)

    expected = [f"task-{i}" for i in range(10)]
    assert live.speak_calls == expected
