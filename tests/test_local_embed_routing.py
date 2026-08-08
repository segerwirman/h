"""Fase 26 — routing berbasis embedding, LOKAL.

Dua hal mendorong fase ini:

* Keluhan lapangan: *"jarvis belum optimal menggunakan tools browser
  Automation dan Computer Use; pastikan jarvis otomatis bisa menggunakannya
  ketika mendapat perintah dari saya"* dan *"optimalkan semua tools dan jarvis
  otomatis mengenali kegunaannya berdasarkan input perintah"*.
* Pengukuran Fase 24: recall/embedding ada di jalur kritis SETIAP giliran
  (3250 ms dingin, 422 ms hangat) karena setiap embedding adalah round trip
  jaringan.

`tool_selection` sekarang memakai regex kategori yang harus ditulis satu per
satu. Perintah yang tidak cocok jatuh ke registry penuh (90 tool) atau ke LLM.
Yang dibutuhkan: Jarvis belajar dari perintah yang SUDAH terbukti berhasil.

**Batas jujur fase ini.** Tidak ada model embedding teks di repo (hanya
`yolov8n.onnx` untuk visi), dan MiniLM berarti unduhan ~90 MB — keputusan yang
bukan milik kode. Jadi embedder di sini leksikal: n-gram karakter + token kata
yang di-hash, deterministik, <1 ms, tanpa dependensi baru. Untuk mencocokkan
perintah yang berulang dengan variasi kecil ("pause youtube" / "tolong pause
yt"), itu memang yang dibutuhkan. Antarmukanya sengaja dibuat agar model
neural bisa menggantikannya tanpa mengubah pemanggil.
"""
from __future__ import annotations

import pytest

from jarvis.core import local_embed


# ── embedder lokal ────────────────────────────────────────────────────────

def test_embedding_is_deterministic_across_calls():
    a = local_embed.embed("pause youtube")
    b = local_embed.embed("pause youtube")

    assert a == b
    assert len(a) == local_embed.DIM


def test_embedding_is_stable_across_processes():
    """Hash bawaan Python untuk str DIACAK tiap proses.

    Memakainya berarti indeks yang ditulis hari ini tidak cocok dengan yang
    dibaca besok — bug yang hanya muncul setelah restart, jenis yang paling
    mahal untuk dilacak.
    """
    import subprocess
    import sys

    code = (
        "import sys; sys.path.insert(0, r'.');"
        "from jarvis.core import local_embed;"
        "print(round(sum(local_embed.embed('pause youtube')), 6))"
    )
    runs = {
        subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, cwd=".").stdout.strip()
        for _ in range(2)
    }

    assert len(runs) == 1, f"embedding berubah antar proses: {runs}"


@pytest.mark.parametrize("a,b", [
    ("pause youtube", "tolong pause youtube"),
    ("pause youtube", "pause yt"),
    ("telepon Honbrew", "telpon honbrew"),
    ("buka spotify", "bukakan spotify"),
])
def test_variations_of_one_command_are_close(a, b):
    assert local_embed.similarity(local_embed.embed(a),
                                  local_embed.embed(b)) > 0.5


@pytest.mark.parametrize("a,b", [
    ("pause youtube", "hapus semua file di folder unduhan"),
    ("telepon Honbrew", "cuaca besok bagaimana"),
])
def test_unrelated_commands_are_far_apart(a, b):
    assert local_embed.similarity(local_embed.embed(a),
                                  local_embed.embed(b)) < 0.35


def test_embedding_never_raises_on_junk():
    for value in (None, 12, "", "   ", object()):
        vector = local_embed.embed(value)
        assert len(vector) == local_embed.DIM


def test_similarity_of_empty_vectors_is_zero():
    empty = local_embed.embed("")
    assert local_embed.similarity(empty, empty) == 0.0


# ── indeks perintah yang DIPELAJARI ───────────────────────────────────────

@pytest.fixture
def index(tmp_path, monkeypatch):
    from jarvis.agent import command_index

    monkeypatch.setattr(command_index, "_db_path",
                        lambda: tmp_path / "cmd.sqlite")
    command_index.reset()
    return command_index


def test_a_verified_command_is_remembered_and_suggested(index):
    index.remember("pause youtube", ["user_browser_media"])

    assert index.suggest("tolong pause youtube") == ["user_browser_media"]


def test_an_unrelated_command_gets_no_suggestion(index):
    index.remember("pause youtube", ["user_browser_media"])

    assert index.suggest("hapus semua file di folder unduhan") is None


def test_an_empty_index_suggests_nothing(index):
    assert index.suggest("apa saja") is None


def test_the_newest_tools_win_for_the_same_command(index):
    """Perintah yang sama dengan hasil berbeda: yang terbaru yang benar."""
    index.remember("pause youtube", ["browser_media"])
    index.remember("pause youtube", ["user_browser_media"])

    assert index.suggest("pause youtube") == ["user_browser_media"]


def test_the_index_is_bounded(index):
    for number in range(index.MAX_ENTRIES + 40):
        index.remember(f"perintah unik nomor {number}", ["clarify"])

    assert index.count() <= index.MAX_ENTRIES


def test_nothing_is_remembered_without_tools(index):
    index.remember("perintah tanpa tool", [])
    assert index.count() == 0


def test_index_never_raises_on_junk(index):
    index.remember(None, None)
    index.remember(12, ["x"])
    assert index.suggest(None) is None


# ── terpasang di pemilihan tool ───────────────────────────────────────────

def test_learned_command_fills_the_gap_where_regex_misses(index, monkeypatch):
    """Perintah yang tidak cocok kategori mana pun kini punya jawaban.

    Sebelumnya ia jatuh ke registry penuh (90 tool) atau ke LLM.
    """
    from jarvis.agent import tool_selection

    # Frasa yang sengaja TIDAK memuat kata kunci kategori mana pun — di situlah
    # celahnya. ("video"/"layar" akan cocok kategori dan menempuh jalur lain.)
    phrase = "lanjutkan yang barusan itu"
    tools = {"user_browser_media": object(), "clarify": object()}
    index.remember(phrase, ["user_browser_media"])

    selected = tool_selection.select_tool_names(phrase, tools)

    assert selected is not None
    assert "user_browser_media" in selected


def test_deterministic_categories_still_win(index, monkeypatch):
    """Yang sudah pasti tidak boleh dikalahkan yang dipelajari."""
    from jarvis.agent import tool_selection

    monkeypatch.setattr(tool_selection.config, "get", lambda _p, d=None: d)
    WhatsAppTool = type("W", (), {"__module__":
                                  "jarvis.agent.tools.whatsapp_web"})
    tools = {"whatsapp_call": WhatsAppTool()}
    index.remember("telepon Ibu lewat WhatsApp", ["clarify"])

    selected = tool_selection.select_tool_names("telepon Ibu lewat WhatsApp",
                                                tools)

    assert selected == ["whatsapp_call"]


def test_a_suggestion_naming_unknown_tools_is_ignored(index):
    """Tool bisa hilang antar versi; saran basi tidak boleh mempersempit."""
    from jarvis.agent import tool_selection

    index.remember("perintah lama sekali", ["tool_yang_sudah_dihapus"])

    assert tool_selection.select_tool_names("perintah lama sekali",
                                            {"clarify": object()}) is None


# ── hanya sukses TERBUKTI yang dipelajari ─────────────────────────────────

def test_only_verified_successes_are_learned():
    """Mesin kontrak bukti (Fase 14) sudah memisahkan sukses nyata dari narasi
    model. Menyimpan apa pun selain itu berarti mengabadikan klaim palsu dan
    mengulanginya lebih cepat setiap hari.
    """
    import inspect

    from jarvis.agent import dispatch

    source = inspect.getsource(dispatch)
    assert "command_index.remember" in source

    # Pemanggilannya harus berada di jalur SUKSES, bukan di `finally` yang
    # berjalan apa pun hasilnya.
    before_call = source.split("_learn_command(task, session)")[0]
    assert "if result.ok:" in before_call


def test_dispatch_learns_the_tools_that_actually_ran(monkeypatch, tmp_path):
    import threading

    from jarvis.agent import command_index, dispatch
    from jarvis.agent import loop as agent_loop
    from jarvis.agent.base import ToolResult
    from jarvis.agent.loop import RunResult
    from jarvis.agent.session import Session

    monkeypatch.setattr(command_index, "_db_path",
                        lambda: tmp_path / "cmd.sqlite")
    command_index.reset()
    monkeypatch.setattr(dispatch, "available", lambda: True)
    monkeypatch.setattr(Session, "finish", lambda *a, **k: None)
    done = threading.Event()

    async def fake_run(_task, *, adapter, session, **_kwargs):
        # Jejak tool sesi — sumber yang SELALU terisi, bukan bukti kontrak yang
        # hanya dikumpulkan untuk tugas berkontrak.
        session.record_tool("open_app", {"name": "spotify"},
                            ToolResult.success("dibuka"), 0.01)
        await adapter.send("Spotify dibuka.")
        return RunResult(ok=True, text="Spotify dibuka.", session_id=session.id)

    monkeypatch.setattr(agent_loop, "run", fake_run)

    assert dispatch.dispatch_async("bukakan lagu di spotify",
                                   on_done=lambda _r: done.set(),
                                   on_error=lambda _e: done.set())
    assert done.wait(20)

    assert command_index.suggest("bukakan lagu di spotify") == ["open_app"]


# ── pemisahan yang DIUKUR, bukan ditebak ──────────────────────────────────

_SAME_TOOL = [
    ("buka kamera", "tolong bukakan kameranya"),
    ("buka kamera", "buka kamera dong sekarang"),
    ("buka kamera", "buka kamera depan"),
    ("telepon honbrew lewat whatsapp", "telpon honbrew via wa"),
    ("telepon honbrew", "tolong telepon honbrew sekarang"),
    ("pause youtube", "tolong pause yt"),
    ("putar lagu di spotify", "putarkan lagunya di spotify"),
    ("cari berita hari ini", "tolong carikan berita hari ini"),
    ("kirim pesan ke honbrew", "kirimkan pesan ke honbrew"),
    ("screenshot layar", "tolong screenshot layarnya"),
]

_DIFFERENT_TOOL = [
    ("buka kamera", "tutup kamera"),
    ("putar lagu di spotify", "hentikan lagu di spotify"),
    ("buka whatsapp", "tutup whatsapp"),
    ("telepon honbrew", "kirim pesan ke honbrew"),
    ("buka kamera", "buka spotify"),
    ("pause youtube", "lanjutkan youtube"),
    ("cari berita hari ini", "cari lagu hari ini"),
    ("buka kamera", "buka browser"),
    ("telepon honbrew", "telepon ibu"),
    ("putar lagu di spotify", "cari berita hari ini"),
]


def _score(pair):
    return local_embed.similarity(local_embed.embed(pair[0]),
                                  local_embed.embed(pair[1]))


@pytest.mark.parametrize("pair", _DIFFERENT_TOOL)
def test_opposite_commands_never_reach_the_threshold(pair):
    """Ini kegagalan yang PALING mahal: "tutup kamera" dirutekan ke tool buka.

    Meleset hanya mengembalikan perilaku lama; salah rute mematahkan perintah.
    """
    from jarvis.agent import command_index

    assert _score(pair) < command_index.DEFAULT_THRESHOLD, pair


@pytest.mark.parametrize("pair", _SAME_TOOL)
def test_paraphrases_of_one_command_clear_the_threshold(pair):
    from jarvis.agent import command_index

    assert _score(pair) >= command_index.DEFAULT_THRESHOLD, pair


def test_the_threshold_sits_inside_a_real_gap():
    """Kunci pemisahannya, bukan cuma ambangnya.

    Tanpa ini, satu perubahan pembobotan bisa merapatkan kedua kelompok
    sampai berimpit sementara semua uji di atas masih hijau.
    """
    from jarvis.agent import command_index

    lowest_same = min(_score(pair) for pair in _SAME_TOOL)
    highest_different = max(_score(pair) for pair in _DIFFERENT_TOOL)

    assert highest_different < command_index.DEFAULT_THRESHOLD <= lowest_same
    assert lowest_same - highest_different > 0.1, (
        f"pemisahan menyempit: {highest_different:.3f} .. {lowest_same:.3f}")


def test_politeness_and_affixes_do_not_change_the_command():
    """Keluhan lapangan aslinya berbahasa sehari-hari, bukan kata kunci."""
    assert local_embed.tokens("tolong bukakan kameranya dong sekarang") ==         local_embed.tokens("buka kamera")
    assert local_embed.tokens("telpon honbrew via wa") ==         local_embed.tokens("telepon honbrew lewat whatsapp")
