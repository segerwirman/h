"""DIAGNOSIS_2 MASALAH 1 & 2 — resolusi niat aplikasi vs situs, dan bertanya
saat benar-benar ambigu.

Prinsipnya: router boleh salah, tapi tidak boleh MENEBAK saat tidak tahu.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.core import app_registry as ar
from jarvis.core import clarify_state
from jarvis.core.router import Intent, IntentRouter

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Alias/preferensi ke berkas sementara — jangan sentuh data user."""
    path = tmp_path / "app_aliases.json"
    monkeypatch.setattr(ar, "_store_path", lambda: path)
    return path


@pytest.fixture
def apps(monkeypatch):
    """Indeks aplikasi palsu: mesin CI/dev tidak selalu memasang Instagram."""
    fake = {
        "instagram": ar.AppMatch("instagram", "Instagram", "Instagram.lnk",
                                 "start_menu"),
        "spotify": ar.AppMatch("spotify", "Spotify", "Spotify.lnk",
                               "start_menu"),
        "notepad": ar.AppMatch("notepad", "Notepad", "notepad.exe",
                               "start_menu"),
        "visual studio code": ar.AppMatch("visual studio code",
                                          "Visual Studio Code", "code.exe",
                                          "start_menu"),
    }
    monkeypatch.setattr(ar, "_index", fake)
    monkeypatch.setattr(ar, "_index_built_at", 9e9)
    monkeypatch.setattr(ar.shutil, "which", lambda *_a, **_k: None)
    return fake


@pytest.fixture
def router(apps, store):
    r = IntentRouter()
    r._llm_fallback = False          # isolasi jalur deterministik
    clarify_state.clear()
    yield r
    clarify_state.clear()


def _route(router, text):
    return router._rules(text)


# ── kelas 1: JELAS APLIKASI ──────────────────────────────────────────────

@pytest.mark.parametrize("text,expected_app", [
    ("buka app instagram", "instagram"),
    ("buka aplikasi spotify", "spotify"),
    ("buka program notepad", "notepad"),
    ("buka aplikasinya spotify", "spotify"),
])
def test_kata_kunci_aplikasi_selalu_menang(router, text, expected_app) -> None:
    c = _route(router, text)
    assert c is not None and c.intent is Intent.OPEN_APP, text
    # Nama harus BERSIH — "app instagram" akan gagal dicari di mana pun.
    assert c.slots["app"] == expected_app


# ── kelas 2: JELAS SITUS ─────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "buka instagram.com",
    "buka website instagram",
    "buka situs instagram",
    "buka https://instagram.com",
])
def test_kata_kunci_situs_selalu_menang(router, text) -> None:
    c = _route(router, text)
    assert c is not None and c.intent is Intent.OPEN_URL, text
    assert "instagram" in c.slots["url"]


def test_situs_memakai_known_sites_bukan_pencarian(router) -> None:
    """Regresi: penanda 'website' tidak boleh ikut jadi bagian nama."""
    c = _route(router, "buka website instagram")
    assert c.slots["url"] == "https://www.instagram.com"
    assert "search" not in c.slots["url"]


# ── kelas 3: AMBIGU → BERTANYA ───────────────────────────────────────────

def test_ambigu_bertanya_bukan_menebak(router) -> None:
    """Inti perbaikan: known_sites TIDAK lagi menang otomatis."""
    c = _route(router, "buka instagram")
    assert c is not None
    assert c.intent is Intent.CLARIFY, \
        f"masih menebak: {c.intent.value} {c.slots}"
    assert "Instagram" in c.slots["question"]
    assert c.slots["options"] == ["aplikasi", "browser"]
    assert c.slots["app"] == "instagram"
    assert c.slots["url"] == "https://www.instagram.com"


def test_tidak_ambigu_tidak_bertanya(router) -> None:
    """Notepad hanya aplikasi; bertanya di sini sama menyebalkannya."""
    c = _route(router, "buka notepad")
    assert c.intent is Intent.OPEN_APP
    # Nama dari indeks (kapitalisasi asli) lebih tepat daripada ketikan user —
    # peluncur macOS/.desktop peka huruf besar-kecil.
    assert c.slots["app"] == "Notepad"


def test_situs_saja_tetap_langsung(router) -> None:
    c = _route(router, "buka github")
    assert c.intent is Intent.OPEN_URL
    assert c.slots["site"] == "github"


def test_tak_dikenal_diserahkan_ke_llm(router) -> None:
    """Tidak cocok apa pun → JANGAN mengarang; biarkan model yang menilai."""
    assert _route(router, "buka zxqwvbn tidak ada") is None


# ── pembelajaran preferensi ──────────────────────────────────────────────

def test_preferensi_tersimpan_dan_menghentikan_pertanyaan(router, store) -> None:
    assert _route(router, "buka instagram").intent is Intent.CLARIFY

    ask = clarify_state.set_pending(
        topic="instagram", question="Aplikasi Instagram atau browser?",
        options=["aplikasi", "browser"], app="instagram",
        url="https://www.instagram.com")
    assert ask.topic == "instagram"

    outcome = clarify_state.resolve("aplikasi")
    assert outcome is not None
    kind, resolved = outcome
    assert kind == "app"
    assert resolved.app == "instagram"

    assert ar.preference_for("instagram") == "app"
    saved = json.loads(store.read_text(encoding="utf-8"))
    assert saved["preferences"]["instagram"] == "app"

    # dan sekarang TIDAK bertanya lagi
    c = _route(router, "buka instagram")
    assert c.intent is Intent.OPEN_APP
    assert c.slots["source"] == "learned"


def test_preferensi_web_juga_dihormati(router, store) -> None:
    ar.remember_preference("instagram", "web")
    c = _route(router, "buka instagram")
    assert c.intent is Intent.OPEN_URL
    assert c.slots["url"] == "https://www.instagram.com"


def test_kata_kunci_eksplisit_mengalahkan_preferensi(router, store) -> None:
    """User yang menyebut 'situs' harus dituruti walau preferensinya app."""
    ar.remember_preference("instagram", "app")
    c = _route(router, "buka situs instagram")
    assert c.intent is Intent.OPEN_URL


# ── penafsiran jawaban ───────────────────────────────────────────────────

@pytest.mark.parametrize("answer,expected", [
    ("aplikasi", "app"), ("app", "app"), ("yang pertama", "app"),
    ("browser", "web"), ("website", "web"), ("situs", "web"),
    ("batal", "declined"), ("lupakan", "declined"),
])
def test_interpretasi_jawaban(store, answer, expected) -> None:
    clarify_state.set_pending(topic="instagram", question="?")
    assert clarify_state.interpret(answer) == expected
    clarify_state.clear()


def test_kalimat_panjang_bukan_jawaban(store) -> None:
    """User yang ganti topik tidak boleh dianggap menjawab."""
    clarify_state.set_pending(topic="instagram", question="?")
    assert clarify_state.interpret(
        "ngomong-ngomong tolong cek cuaca hari ini di jakarta") is None
    assert clarify_state.pending() is not None, "state ikut terhapus"
    clarify_state.clear()


def test_jawaban_ambigu_tetap_bukan_jawaban(store) -> None:
    clarify_state.set_pending(topic="instagram", question="?")
    assert clarify_state.interpret("aplikasi atau browser ya") is None
    clarify_state.clear()


def test_pending_kedaluwarsa(store, monkeypatch) -> None:
    clarify_state.set_pending(topic="x", question="?")
    monkeypatch.setattr(clarify_state, "TTL_S", -1.0)
    assert clarify_state.pending() is None


def test_resolve_tanpa_pending_aman(store) -> None:
    clarify_state.clear()
    assert clarify_state.resolve("aplikasi") is None


# ── app_registry ─────────────────────────────────────────────────────────

def test_normalisasi_membuang_kata_penanda() -> None:
    assert ar.normalize("app instagram") == "instagram"
    assert ar.normalize("aplikasi Spotify") == "spotify"
    assert ar.normalize("  Visual  Studio  Code ") == "visual studio code"


def test_fuzzy_alias_dan_prefix(apps, store) -> None:
    assert ar.resolve("insta").key == "instagram"        # prefix
    assert ar.resolve("ig").key == "instagram"           # seed alias
    assert ar.resolve("vsc").key == "visual studio code"  # akronim/alias
    assert ar.resolve("spotify").score == 1.0
    assert ar.resolve("zzzznope") is None


def test_alias_yang_dipelajari_mengalahkan_heuristik(apps, store) -> None:
    assert ar.resolve("gram") is None or ar.resolve("gram").key == "instagram"
    ar.learn_alias("gram", "Instagram")
    assert ar.resolve("gram").key == "instagram"
    saved = json.loads(store.read_text(encoding="utf-8"))
    assert saved["aliases"]["gram"] == "instagram"


def test_indeks_nyata_terbangun() -> None:
    """Bukan mock: mesin ini harus benar-benar menghasilkan indeks."""
    count = ar.refresh(force=True)
    assert count > 0, "penemuan aplikasi tidak menemukan apa pun"
    assert all(isinstance(v, ar.AppMatch) for v in ar.index().values())


def test_store_rusak_tidak_menjatuhkan(store) -> None:
    store.write_text("{ bukan json", encoding="utf-8")
    assert ar.preference_for("apa pun") is None
    assert ar.remember_preference("x", "app") is True


# ── lane suara ───────────────────────────────────────────────────────────

def test_clarify_dideklarasikan_ke_lane_suara() -> None:
    from jarvis.integrations import voice_clarify

    decls = {d["name"]: d for d in voice_clarify.declarations()}
    assert "clarify" in decls
    params = decls["clarify"]["parameters"]
    assert params["type"] == "OBJECT"
    assert "question" in params["properties"]
    assert params["required"] == ["question"]
    assert "topic" in params["properties"], "tanpa topic, preferensi tak bisa disimpan"


def test_install_suara_tanpa_menyentuh_frozen(store) -> None:
    import hashlib
    from types import SimpleNamespace

    from jarvis.integrations import voice_clarify

    before = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in ("main.py", "core/prompt.txt")
    }

    legacy = SimpleNamespace(
        TOOL_DECLARATIONS=[{"name": "open_app"}],
        JarvisLive=type("L", (), {"_execute_tool": lambda self, fc: None}),
        types=SimpleNamespace(FunctionResponse=dict),
        _load_system_prompt=lambda: "PERSONA USER",
    )
    voice_clarify.install(legacy)

    names = [d["name"] for d in legacy.TOOL_DECLARATIONS]
    assert "clarify" in names
    assert "open_app" in names, "deklarasi legacy hilang"

    prompt = legacy._load_system_prompt()
    assert prompt.startswith("PERSONA USER")
    assert "[SAAT RAGU" in prompt
    assert legacy._load_system_prompt().count("[SAAT RAGU") == 1

    after = {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in ("main.py", "core/prompt.txt")
    }
    assert before == after, "berkas FROZEN berubah"


def test_handle_clarify_mencatat_pending(store) -> None:
    from jarvis.integrations import voice_clarify

    clarify_state.clear()
    out = voice_clarify.handle({
        "question": "Aplikasi Instagram atau browser?",
        "options": ["aplikasi", "browser"], "topic": "instagram"})
    assert "Ajukan pertanyaan" in out
    ask = clarify_state.pending()
    assert ask is not None and ask.topic == "instagram"
    clarify_state.clear()


def test_handle_clarify_tanpa_pertanyaan(store) -> None:
    from jarvis.integrations import voice_clarify

    clarify_state.clear()
    assert "Tidak ada pertanyaan" in voice_clarify.handle({})
    assert clarify_state.pending() is None
