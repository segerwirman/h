"""Fase 4 — kegagalan pipeline suara harus TERLIHAT, bukan diam.

Insiden 2026-08-04: `import sounddevice` gagal di main.py:35, runner menelan
exception jadi satu baris log, boot tetap dilaporkan sukses, UI muncul, dan
JARVIS diam total untuk voice MAUPUN text. Lima kali restart tanpa petunjuk.

Kontrak yang dikunci di sini: setiap kegagalan pipeline menerbitkan
`boot.check` untuk subsystem `core.voice` dengan detail yang bisa
ditindaklanjuti, dan keberhasilan menerbitkan `ok=True`.
"""
from __future__ import annotations

import threading

import pytest

from jarvis.core.bus import BUS


@pytest.fixture
def captured():
    """Tangkap event boot.check yang diterbitkan ke bus."""
    events: list[dict] = []
    BUS.subscribe("boot.check", events.append)
    yield events


class _UI:
    """UI palsu seminimal mungkin sesuai kontrak yang dipakai runner."""

    def __init__(self):
        self.logs: list[str] = []
        self.on_text_command = None
        self.on_remote_clicked = None
        self.on_interrupt = None

    def write_log(self, text):
        self.logs.append(text)

    def wait_for_api_key(self):
        return None


def _run_pipeline_and_wait(monkeypatch, exc):
    """Jalankan _start_voice_pipeline dengan import legacy yang gagal."""
    from jarvis import main as jmain

    def boom():
        raise exc

    monkeypatch.setattr(jmain, "_import_legacy", boom)
    ui = _UI()
    thread = jmain._start_voice_pipeline(ui, stop_requested=threading.Event())
    thread.join(timeout=10)
    assert not thread.is_alive(), "runner menggantung — tidak boleh"
    return ui


def _voice_events(events):
    return [e for e in events if e.get("subsystem") == "core.voice"]


def test_dependency_hilang_menerbitkan_boot_check_gagal(monkeypatch, captured):
    exc = ModuleNotFoundError("No module named 'sounddevice'", name="sounddevice")
    _run_pipeline_and_wait(monkeypatch, exc)

    voice = _voice_events(captured)
    assert voice, "kegagalan pipeline tidak menerbitkan boot.check core.voice"
    ev = voice[-1]
    assert ev["ok"] is False
    assert "sounddevice" in ev["detail"], ev["detail"]


def test_detail_dependency_menyebut_perintah_perbaikan(monkeypatch, captured):
    exc = ModuleNotFoundError("No module named 'sounddevice'", name="sounddevice")
    _run_pipeline_and_wait(monkeypatch, exc)

    detail = _voice_events(captured)[-1]["detail"]
    assert "uv sync" in detail, f"detail tidak bisa ditindaklanjuti: {detail}"


def test_api_key_ditolak_mengarahkan_ke_settings(monkeypatch, captured):
    _run_pipeline_and_wait(monkeypatch, RuntimeError("API key not valid"))

    detail = _voice_events(captured)[-1]["detail"]
    assert "Settings" in detail, detail


def test_kegagalan_lain_tetap_membawa_sebab_asli(monkeypatch, captured):
    _run_pipeline_and_wait(monkeypatch, RuntimeError("websocket 1008 policy"))

    detail = _voice_events(captured)[-1]["detail"]
    assert "1008" in detail, detail


def test_ui_tetap_menerima_baris_log(monkeypatch, captured):
    exc = ModuleNotFoundError("No module named 'sounddevice'", name="sounddevice")
    ui = _run_pipeline_and_wait(monkeypatch, exc)

    assert any("voice" in line.lower() for line in ui.logs), ui.logs


def test_api_key_timeout_dilaporkan_bukan_menggantung(monkeypatch, captured):
    """Fase 5: wait_for_api_key habis waktu → pipeline melapor, tidak diam."""
    from jarvis import main as jmain

    class _TimingOutUI(_UI):
        def wait_for_api_key(self, timeout=None, should_stop=None):
            return False                      # batas waktu tercapai

    class _FakeLegacy:
        JarvisLive = lambda ui: None          # noqa: E731 — tak boleh terpanggil
        LIVE_MODEL = "models/dummy-live"

    monkeypatch.setattr(jmain, "_import_legacy", lambda: _FakeLegacy)
    monkeypatch.setattr(jmain, "_install_voice_seams", lambda legacy, logger: None)

    ui = _TimingOutUI()
    thread = jmain._start_voice_pipeline(ui, stop_requested=threading.Event())
    thread.join(timeout=10)
    assert not thread.is_alive(), "runner menggantung setelah timeout"

    voice = _voice_events(captured)
    assert voice and voice[-1]["ok"] is False
    assert "API key" in voice[-1]["detail"], voice[-1]["detail"]


def test_ui_lama_tanpa_argumen_tetap_didukung(monkeypatch, captured):
    """ui.py FROZEN hanya punya wait_for_api_key(self) dan mengembalikan None;
    perilakunya harus tetap dianggap sukses."""
    from jarvis import main as jmain

    seen: list[str] = []

    class _LegacyUI(_UI):
        def wait_for_api_key(self):           # tanpa kwargs, seperti ui.py
            seen.append("called")
            return None

    class _FakeLive:
        def __init__(self, ui):
            ui.on_text_command = lambda text: None

        def request_stop(self):
            pass

        async def run(self):
            return None

    class _FakeLegacy:
        JarvisLive = _FakeLive
        LIVE_MODEL = "models/dummy-live"

    monkeypatch.setattr(jmain, "_import_legacy", lambda: _FakeLegacy)
    monkeypatch.setattr(jmain, "_install_voice_seams", lambda legacy, logger: None)

    ui = _LegacyUI()
    thread = jmain._start_voice_pipeline(ui, stop_requested=threading.Event())
    thread.join(timeout=10)
    assert not thread.is_alive()

    assert seen == ["called"], "UI lama tidak dipanggil"
    assert ui.on_text_command is not None, "binding gagal untuk UI lama"
    voice = _voice_events(captured)
    assert voice and voice[-1]["ok"] is True


def test_pipeline_sukses_menerbitkan_core_voice_online(monkeypatch, captured):
    """Sisi positif: kalau pipeline hidup, core.voice dilaporkan ONLINE."""
    from jarvis import main as jmain

    started = threading.Event()

    class _FakeLive:
        def __init__(self, ui):
            ui.on_text_command = lambda text: None   # binding yang dulu hilang

        def request_stop(self):
            pass

        async def run(self):
            started.set()

    class _FakeLegacy:
        JarvisLive = _FakeLive
        LIVE_MODEL = "models/dummy-live"

        @staticmethod
        def _get_api_key():
            return ""

    monkeypatch.setattr(jmain, "_import_legacy", lambda: _FakeLegacy)
    monkeypatch.setattr(jmain, "_install_voice_seams", lambda legacy, logger: None)

    ui = _UI()
    thread = jmain._start_voice_pipeline(ui, stop_requested=threading.Event())
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert started.is_set(), "run() tidak pernah dipanggil"

    voice = _voice_events(captured)
    assert voice, "sukses tidak menerbitkan boot.check core.voice"
    assert voice[-1]["ok"] is True
    assert ui.on_text_command is not None, "on_text_command harus ter-bind"
