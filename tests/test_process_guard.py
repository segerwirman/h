"""DIAGNOSIS_2 MASALAH 3 — Jarvis tidak boleh membunuh dirinya sendiri.

Ini satu-satunya kode di repo yang kalau salah bisa mematikan Jarvis di
tengah pekerjaan user. Karena itu yang diuji bukan hanya "jalur normal benar"
tapi juga **setiap cara guard bisa dilewati**: parameter, force, nama
alternatif, psutil hilang, pid tak terbaca.
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from jarvis.core import process_guard as pg
from jarvis.core.process_guard import SelfTerminationBlocked
from jarvis.core.router import Intent, IntentRouter


@pytest.fixture(autouse=True)
def _fresh_cache():
    pg._reset_cache_for_tests()
    yield
    pg._reset_cache_for_tests()


# ── inti guard ───────────────────────────────────────────────────────────

def test_pid_sendiri_selalu_terdeteksi() -> None:
    assert pg.is_self(pid=os.getpid()) is True
    assert os.getpid() in pg.own_pids()


def test_hanya_anak_python_dilindungi_dan_parent_bukan_jarvis() -> None:
    """Visi Python dilindungi; child browser dan launcher tetap bisa ditutup."""
    pids = pg.own_pids()
    assert os.getpid() in pids
    try:
        import psutil
        me = psutil.Process(os.getpid())
        parent = me.parent()
        if parent is not None:
            assert parent.pid not in pids
        for child in me.children(recursive=True):
            name = pg._normalize(child.name())
            if name in pg.PROTECTED_NAMES:
                assert child.pid in pids
            else:
                assert child.pid not in pids
    except (ImportError, PermissionError):
        pytest.skip("psutil tidak terpasang")


@pytest.mark.parametrize("name", [
    "python", "pythonw", "python3", "Python.exe", "PYTHONW.EXE",
    "jarvis", "Jarvis", "dirimu", "yourself", "asisten",
])
def test_nama_terlindungi_ditolak(name) -> None:
    assert pg.is_self(name=name) is True, name


@pytest.mark.parametrize("name", ["instagram", "chrome", "notepad", "spotify"])
def test_aplikasi_lain_boleh(name) -> None:
    assert pg.is_self(name=name) is False, name


def test_tanpa_identitas_ditolak() -> None:
    """Fail-safe: target tanpa pid maupun nama tidak bisa dibuktikan aman."""
    assert pg.is_self() is True
    assert pg.is_self(pid=None, name=None) is True
    assert pg.is_self(name="") is True
    assert pg.is_self(name="   ") is True


def test_pid_tidak_terbaca_ditolak() -> None:
    assert pg.is_self(pid="bukan angka") is True   # type: ignore[arg-type]
    assert pg.is_self(pid=0) is True
    assert pg.is_self(pid=-5) is True


def test_nama_mengandung_nama_proses_kita_ditolak() -> None:
    """'python3.11' harus ikut tertolak, bukan lolos karena beda persis."""
    assert pg.is_self(name="python3.11") is True


# ── assert_not_self ──────────────────────────────────────────────────────

def test_assert_melempar_untuk_diri_sendiri() -> None:
    with pytest.raises(SelfTerminationBlocked):
        pg.assert_not_self(os.getpid())
    with pytest.raises(SelfTerminationBlocked):
        pg.assert_not_self("python")
    with pytest.raises(SelfTerminationBlocked):
        pg.assert_not_self(None)


def test_assert_lolos_untuk_target_lain() -> None:
    pg.assert_not_self("instagram")
    pg.assert_not_self(SimpleNamespace(pid=999999, name="chrome"))


def test_assert_membaca_objek_ber_atribut() -> None:
    own = SimpleNamespace(pid=os.getpid(), name="apa pun")
    with pytest.raises(SelfTerminationBlocked):
        pg.assert_not_self(own)


def test_pesan_penolakan_menjelaskan_alternatif() -> None:
    with pytest.raises(SelfTerminationBlocked) as exc:
        pg.assert_not_self("jarvis")
    text = str(exc.value)
    assert "Jarvis sendiri" in text
    assert "eksplisit" in text, "penolakan harus menawarkan jalan yang benar"


def test_guard_tanpa_psutil_tetap_melindungi(monkeypatch) -> None:
    """psutil hilang = kurang informasi = harus LEBIH ketat, bukan longgar."""
    import builtins

    real_import = builtins.__import__

    def _no_psutil(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("psutil dimatikan untuk tes")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_psutil)
    pg._reset_cache_for_tests()
    assert os.getpid() in pg.own_pids()
    assert pg.is_self(pid=os.getpid()) is True
    assert pg.is_self(name="python") is True


def test_tidak_ada_parameter_bypass() -> None:
    """Guard tidak boleh punya force/allow_self/override apa pun.

    Diperiksa lewat AST, bukan grep teks: docstring modul ini justru
    MENYEBUT kata-kata itu untuk menjelaskan bahwa mereka tidak ada.
    """
    import ast
    import inspect

    sig = inspect.signature(pg.assert_not_self)
    assert list(sig.parameters) == ["target"], \
        f"assert_not_self punya parameter tambahan: {list(sig.parameters)}"

    forbidden = {"allow_self", "bypass", "override", "skip_guard", "force"}
    tree = ast.parse(inspect.getsource(pg))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = node.args
        names = {a.arg for a in (args.posonlyargs + args.args + args.kwonlyargs)}
        leaked = names & forbidden
        assert not leaked, f"{node.name}() punya jalan pintas: {leaked}"


def test_refers_to_jarvis() -> None:
    assert pg.refers_to_jarvis("tutup jarvis") is True
    assert pg.refers_to_jarvis("matikan dirimu") is True
    assert pg.refers_to_jarvis("tutup instagram") is False


# ── close_app ────────────────────────────────────────────────────────────

def test_close_app_menolak_diri_sendiri() -> None:
    from actions.close_app import STATUS_BLOCKED, close_app

    for name in ("jarvis", "python", "dirimu"):
        outcome = close_app(name)
        assert outcome.ok is False, name
        assert outcome.status == STATUS_BLOCKED, name
        assert "saya sendiri" in outcome.message.lower()


def test_close_app_force_tidak_melewati_guard() -> None:
    """'force' hanya mempercepat langkah terakhir — bukan pintu belakang."""
    from actions.close_app import STATUS_BLOCKED, close_app

    outcome = close_app("python", force=True, all_windows=True)
    assert outcome.status == STATUS_BLOCKED
    assert outcome.closed == []


def test_close_app_tanpa_nama_bertanya() -> None:
    from actions.close_app import STATUS_AMBIGUOUS, close_app

    outcome = close_app("")
    assert outcome.status == STATUS_AMBIGUOUS
    assert "mana" in outcome.message.lower()


def test_close_app_tidak_berjalan_dilaporkan(monkeypatch) -> None:
    """Tidak diam, tidak crash."""
    from actions import close_app as mod

    monkeypatch.setattr(mod, "_matches", lambda _n: [])
    outcome = mod.close_app("aplikasitidakada")
    assert outcome.status == mod.STATUS_NOT_RUNNING
    assert "tidak sedang berjalan" in outcome.message


def test_close_app_banyak_jendela_bertanya(monkeypatch) -> None:
    from actions import close_app as mod
    from jarvis.core.app_registry import RunningApp

    monkeypatch.setattr(mod, "_matches", lambda _n: [
        RunningApp("chrome.exe", 4001, "Tab A"),
        RunningApp("chrome.exe", 4002, "Tab B"),
        RunningApp("chrome.exe", 4003, "Tab C"),
    ])
    outcome = mod.close_app("chrome")
    assert outcome.status == mod.STATUS_AMBIGUOUS
    assert "3 jendela" in outcome.message
    assert len(outcome.candidates) == 3


def test_close_app_anggun_dulu_bukan_kill(monkeypatch) -> None:
    """SIGKILL tidak boleh jadi langkah pertama — data user hilang."""
    from actions import close_app as mod
    from jarvis.core.app_registry import RunningApp

    order: list[str] = []
    monkeypatch.setattr(mod, "_matches",
                        lambda _n: [RunningApp("chrome.exe", 4001, "Chrome")])
    monkeypatch.setattr(mod, "_graceful",
                        lambda app: order.append("graceful") or True)
    monkeypatch.setattr(mod, "_alive", lambda pid: False)
    monkeypatch.setattr(mod, "_hard_kill",
                        lambda app: order.append("kill") or True)

    outcome = mod.close_app("chrome", grace_s=0.05)
    assert outcome.ok is True
    assert order == ["graceful"], f"urutan salah: {order}"


def test_close_app_paksa_hanya_setelah_anggun_gagal(monkeypatch) -> None:
    from actions import close_app as mod
    from jarvis.core.app_registry import RunningApp

    order: list[str] = []
    monkeypatch.setattr(mod, "_matches",
                        lambda _n: [RunningApp("chrome.exe", 4001, "Chrome")])
    monkeypatch.setattr(mod, "_graceful",
                        lambda app: order.append("graceful") or True)
    alive = {"n": 0}

    def _alive(_pid):
        alive["n"] += 1
        return alive["n"] < 6            # bertahan sebentar, lalu mati
    monkeypatch.setattr(mod, "_alive", _alive)
    monkeypatch.setattr(mod, "_hard_kill",
                        lambda app: order.append("kill") or True)

    mod.close_app("chrome", force=True, grace_s=0.05)
    assert order[0] == "graceful", "kill mendahului penutupan anggun"


def test_close_app_tanpa_force_tidak_membunuh(monkeypatch) -> None:
    from actions import close_app as mod
    from jarvis.core.app_registry import RunningApp

    killed: list[int] = []
    monkeypatch.setattr(mod, "_matches",
                        lambda _n: [RunningApp("chrome.exe", 4001, "Chrome")])
    monkeypatch.setattr(mod, "_graceful", lambda app: True)
    monkeypatch.setattr(mod, "_alive", lambda pid: True)   # menolak tutup
    monkeypatch.setattr(mod, "_hard_kill",
                        lambda app: killed.append(app.pid) or True)

    outcome = mod.close_app("chrome", grace_s=0.05)
    assert killed == [], "membunuh tanpa diminta"
    assert outcome.status == mod.STATUS_FAILED
    assert "paksa" in outcome.message.lower()


def test_hard_kill_tetap_memeriksa_guard() -> None:
    """Lapisan terakhir mengulang guard — pemanggil bisa saja berubah."""
    from actions import close_app as mod

    with pytest.raises(SelfTerminationBlocked):
        mod._hard_kill(SimpleNamespace(pid=os.getpid(), name="python"))


# ── routing "tutup X" ────────────────────────────────────────────────────

@pytest.fixture
def router():
    r = IntentRouter()
    r._llm_fallback = False
    return r


@pytest.mark.parametrize("text,expected", [
    ("tutup aplikasi instagram", "instagram"),
    ("tutup instagram", "instagram"),
])
def test_tutup_bernama_ke_close_app(router, text, expected) -> None:
    c = router._rules(text)
    assert c.intent is Intent.SYSTEM
    assert c.slots["action"] == "close_app"
    assert c.slots["value"] == expected


@pytest.mark.parametrize("text", ["tutup aplikasi", "tutup jendela ini"])
def test_tutup_tanpa_target_bertanya(router, text) -> None:
    """JANGAN pakai jendela aktif sebagai default — itu sering Jarvis."""
    c = router._rules(text)
    assert c.intent is Intent.CLARIFY, f"{text} -> {c.intent}"
    assert "mana" in c.slots["question"].lower()


def test_tutup_semua_chrome(router) -> None:
    c = router._rules("tutup semua chrome")
    assert c.slots["action"] == "close_app"
    assert c.slots["value"] == "chrome"
    assert c.slots["all_windows"] is True


def test_tutup_python_ditolak_router(router) -> None:
    c = router._rules("tutup python")
    assert c.slots["action"] == "close_blocked"


@pytest.mark.parametrize("text", ["tutup jarvis", "matikan dirimu",
                                  "matikan jarvis", "stop jarvis"])
def test_permintaan_berhenti_ke_jalur_konfirmasi(router, text) -> None:
    c = router._rules(text)
    assert c.intent is Intent.SYSTEM
    assert c.slots["action"] == "shutdown_jarvis_request", text


@pytest.mark.parametrize("text,action", [
    ("matikan wifi", "wifi_off"),
    ("matikan komputer", "shutdown"),
    ("matikan suara", "volume_mute"),
    ("tutup kamera", "vision_close"),
])
def test_pola_lama_tidak_regresi(router, text, action) -> None:
    assert router._rules(text).slots["action"] == action


# ── shutdown berkonfirmasi ───────────────────────────────────────────────

def test_shutdown_butuh_dua_langkah(monkeypatch) -> None:
    from jarvis.integrations import voice_safety

    done: list[bool] = []
    monkeypatch.setattr(voice_safety, "graceful_shutdown",
                        lambda live=None: done.append(True))
    voice_safety.reset_confirmation()

    msg, ok = voice_safety.handle_shutdown({})
    assert ok and not done, "langsung mati tanpa konfirmasi"
    assert "konfirmasi" in msg.lower()

    msg2, ok2 = voice_safety.handle_shutdown({"confirmed": "yes"})
    assert ok2 and done == [True]


def test_confirmed_tanpa_permintaan_awal_tidak_mematikan(monkeypatch) -> None:
    """Model tidak boleh melompati langkah pertama dengan mengarang flag."""
    from jarvis.integrations import voice_safety

    done: list[bool] = []
    monkeypatch.setattr(voice_safety, "graceful_shutdown",
                        lambda live=None: done.append(True))
    voice_safety.reset_confirmation()

    _msg, _ok = voice_safety.handle_shutdown({"confirmed": "yes"})
    assert done == [], "confirmed=yes melewati konfirmasi"


def test_konfirmasi_kedaluwarsa(monkeypatch) -> None:
    from jarvis.integrations import voice_safety

    done: list[bool] = []
    monkeypatch.setattr(voice_safety, "graceful_shutdown",
                        lambda live=None: done.append(True))
    voice_safety.reset_confirmation()
    voice_safety.handle_shutdown({})
    monkeypatch.setattr(voice_safety, "CONFIRM_WINDOW_S", -1.0)
    voice_safety.handle_shutdown({"confirmed": "yes"})
    assert done == [], "konfirmasi basi tetap diterima"


def test_deskripsi_shutdown_mencegah_salah_pilih() -> None:
    from jarvis.integrations import voice_safety

    decl = {d["name"]: d for d in voice_safety.declarations()}
    desc = decl["shutdown_jarvis"]["description"]
    assert "HANYA untuk mematikan Jarvis sendiri" in desc
    assert "JANGAN PERNAH" in desc
    assert "close_app" in desc
    assert "close_app" in decl


def test_install_safety_tidak_menyentuh_frozen() -> None:
    import hashlib
    from pathlib import Path

    from jarvis.integrations import voice_safety

    root = Path(__file__).resolve().parents[1]
    before = {n: hashlib.sha256((root / n).read_bytes()).hexdigest()
              for n in ("main.py", "core/prompt.txt")}

    legacy = SimpleNamespace(
        TOOL_DECLARATIONS=[{"name": "shutdown_jarvis",
                            "description": "deskripsi LAMA yang berbahaya"},
                           {"name": "open_app"}],
        JarvisLive=type("L", (), {"_execute_tool": lambda self, fc: None}),
        types=SimpleNamespace(FunctionResponse=dict),
        _load_system_prompt=lambda: "PERSONA USER",
    )
    voice_safety.install(legacy)

    decls = {d["name"]: d for d in legacy.TOOL_DECLARATIONS}
    assert "open_app" in decls
    assert "close_app" in decls
    assert "LAMA" not in decls["shutdown_jarvis"]["description"], \
        "deskripsi berbahaya tidak tergantikan"
    assert "[MENUTUP SESUATU]" in legacy._load_system_prompt()

    after = {n: hashlib.sha256((root / n).read_bytes()).hexdigest()
             for n in ("main.py", "core/prompt.txt")}
    assert before == after, "berkas FROZEN berubah"


# ── computer_settings tidak lagi buta ────────────────────────────────────

def test_close_app_lama_wajib_target() -> None:
    from actions import computer_settings as cs

    msg = cs.close_app()
    assert "mana" in msg.lower()
    msg2 = cs.close_window()
    assert "mana" in msg2.lower() or "jendela" in msg2.lower()


def test_aksi_destruktif_tidak_ditawarkan_ke_penebak() -> None:
    """_detect_action menyuruh model 'pick the closest action' — daftar itu
    tidak boleh memuat aksi yang tak bisa dibatalkan."""
    import inspect

    from actions import computer_settings as cs

    src = inspect.getsource(cs._detect_action)
    assert "_UNGUESSABLE" in src
    assert "close_app" in src
