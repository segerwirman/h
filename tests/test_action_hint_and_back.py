"""Hint hover ActionPanel + tombol kembali Task Deck.

Dua hal yang paling mudah salah diam-diam diuji keras di sini: warna yang
di-hardcode (rusak saat ganti tema) dan ESC yang meregresi interupsi suara.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QEvent, QPointF, Qt              # noqa: E402
from PyQt6.QtGui import QEnterEvent                      # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget        # noqa: E402

from jarvis.ui import action_hint, theme                 # noqa: E402
from jarvis.ui.action_hint import HINT_TEXT, ActionHint  # noqa: E402
from jarvis.ui.stage_history import StageHistory         # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# ── Bagian 1: hint hover ─────────────────────────────────────────────────

def test_teks_hint_lengkap_untuk_semua_ikon() -> None:
    from jarvis.core import config

    icons = config.get("action_panel.icons", [])
    missing = [name for name in icons if name not in HINT_TEXT]
    assert not missing, f"ikon tanpa teks hint: {missing}"


def _code_only(path: Path) -> str:
    """Buang komentar DAN docstring sebelum memeriksa.

    Kesalahan ini sudah terulang tiga kali: tes yang menggrep teks mentah
    gagal karena dokumentasi modul MENYEBUT hal yang dilarang, justru untuk
    menjelaskan kenapa hal itu tidak dipakai.
    """
    import ast
    import io
    import tokenize

    src = path.read_text(encoding="utf-8")
    pieces = [tok.string for tok in
              tokenize.generate_tokens(io.StringIO(src).readline)
              if tok.type != tokenize.COMMENT]
    stripped = " ".join(pieces)
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node)
            if doc:
                stripped = stripped.replace(doc, "")
    return stripped


def test_hint_tidak_memakai_warna_hardcode() -> None:
    """Ganti tema harus ikut mengubah hint (uji §UI 4)."""
    code = _code_only(ROOT / "jarvis" / "ui" / "action_hint.py")
    hits = re.findall(r"#[0-9a-fA-F]{3,8}\b", code)
    assert not hits, f"warna hardcode di KODE: {hits}"


def test_hint_memakai_token_paling_terang(app) -> None:
    """User minta teks PUTIH. theme.py FROZEN, jadi dipakai orb_core —
    token paling terang yang memang sudah ada di tiap preset."""
    parent = QWidget()            # dipegang: tanpa ini Qt membuangnya
    hint = ActionHint(parent)
    hint._text = "Panel Visi (F6)"
    hint._restyle()
    style = hint.styleSheet()
    assert theme.PAL.orb_core in style
    assert theme.PAL.accent in style, "border accent hilang"


def test_hint_ikut_ganti_tema(app) -> None:
    parent = QWidget()
    hint = ActionHint(parent)
    original = theme.PAL.name
    try:
        theme.PAL.set_active("cyan_gold")
        hint._restyle()
        cyan = hint.styleSheet()
        theme.PAL.set_active("stealth_dark")
        hint._restyle()
        stealth = hint.styleSheet()
        assert cyan != stealth, "hint tidak ikut berganti tema"
    finally:
        theme.PAL.set_active(original)


def test_hint_dijepit_di_dalam_jendela(app) -> None:
    """Ikon di tepi jendela → hint tidak boleh terpotong."""
    parent = QWidget()
    parent.resize(400, 300)
    hint = ActionHint(parent)
    hint.setText("Teks hint yang cukup panjang untuk melewati tepi")
    hint.adjustSize()

    for pos in ((0, 0), (395, 295), (0, 295), (395, 0)):
        target = QWidget(parent)
        target.setFixedSize(30, 30)
        target.move(*pos)
        hint._reposition(target)
        assert hint.x() >= 0, f"keluar kiri pada {pos}"
        assert hint.y() >= 0, f"keluar atas pada {pos}"
        assert hint.x() + hint.width() <= parent.width(), f"keluar kanan {pos}"
        assert hint.y() + hint.height() <= parent.height(), f"keluar bawah {pos}"


def test_hint_di_atas_ikon_bila_muat(app) -> None:
    parent = QWidget()
    parent.resize(400, 300)
    hint = ActionHint(parent)
    hint.setText("Spotify")
    hint.adjustSize()
    target = QWidget(parent)
    target.setFixedSize(30, 30)
    target.move(180, 200)
    hint._reposition(target)
    assert hint.y() + hint.height() <= 200, "hint tidak berada di atas ikon"


def test_hover_cepat_tidak_berkedip(app) -> None:
    """Delay masuk 120 ms: kursor yang sekadar lewat tidak memunculkan hint."""
    parent = QWidget()
    hint = ActionHint(parent)
    target = QWidget(parent)

    hint.request(target, "Spotify")
    assert hint._show_timer.isActive(), "tidak ada delay masuk"
    assert not hint.isVisible(), "muncul seketika — akan berkedip"
    hint.release(target)
    assert not hint._show_timer.isActive(), "timer tidak dibatalkan"


def test_install_tanpa_menyentuh_actionpanel(app) -> None:
    """actionpanel.py semi-frozen — hover diambil lewat eventFilter luar."""
    import hashlib

    before = hashlib.sha256(
        (ROOT / "jarvis" / "ui" / "actionpanel.py").read_bytes()).hexdigest()

    from jarvis.ui.actionpanel import ActionPanel
    panel = ActionPanel(None)
    host = QWidget()
    hint = action_hint.install(panel, host)
    assert hint is not None

    after = hashlib.sha256(
        (ROOT / "jarvis" / "ui" / "actionpanel.py").read_bytes()).hexdigest()
    assert before == after

    button = panel._buttons["spotify"]
    button.setParent(host)
    QApplication.sendEvent(
        button, QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))
    assert hint._text == "Spotify", "eventFilter tidak menangkap hover"
    QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
    assert hint._hide_timer.isActive()


def test_install_bisa_dimatikan_config(app, monkeypatch) -> None:
    from jarvis.core import config

    real = config.get
    monkeypatch.setattr(
        config, "get",
        lambda k, d=None: (False if k == "ui.action_panel.hint.enabled"
                           else real(k, d)))
    from jarvis.ui.actionpanel import ActionPanel
    assert action_hint.install(ActionPanel(None), QWidget()) is None


# ── Bagian 2: riwayat panel ──────────────────────────────────────────────

class _FakeStage:
    def __init__(self) -> None:
        self.current: str | None = None
        self.calls: list[str] = []

    def show_child(self, name: str) -> None:
        self.current = name
        self.calls.append(name)

    def hide_all(self) -> None:
        self.current = None
        self.calls.append("EMPTY")


def test_back_kembali_ke_panel_sebelumnya() -> None:
    stage = _FakeStage()
    history = StageHistory(stage)

    stage.show_child("vision")
    history.record("tasks")
    stage.show_child("tasks")

    assert history.back() == "vision"
    assert stage.current == "vision"


def test_back_kosong_jadi_empty() -> None:
    stage = _FakeStage()
    history = StageHistory(stage)
    stage.show_child("tasks")
    assert history.back() is None
    assert stage.current is None


def test_riwayat_dibatasi_lima() -> None:
    stage = _FakeStage()
    history = StageHistory(stage, max_depth=5)
    for i in range(9):
        stage.show_child(f"panel{i}")
        history.record(f"panel{i + 1}")
    assert history.depth() == 5, "kedalaman tidak dibatasi"


def test_back_tidak_mencatat_dirinya_sendiri() -> None:
    """Kalau langkah mundur ikut tercatat, back() akan berputar-putar."""
    stage = _FakeStage()
    history = StageHistory(stage)
    stage.show_child("vision")
    history.record("tasks")
    stage.show_child("tasks")
    history.back()
    assert history.depth() == 0


def test_tidak_mencatat_panel_yang_sama_dua_kali() -> None:
    stage = _FakeStage()
    history = StageHistory(stage)
    stage.show_child("vision")
    history.record("tasks")
    history.record("tasks")
    assert history.depth() == 1


# ── ESC: do-not-regress ──────────────────────────────────────────────────

class _FakeWin:
    """Cukup meniru permukaan MainWindow yang dibaca _do_interrupt."""

    def __init__(self, state: str, panel: str | None) -> None:
        self._legacy_state = state
        self.stage = _FakeStage()
        self.stage.current = panel
        self.interrupted = False
        self.on_interrupt = lambda: setattr(self, "interrupted", True)
        self.stage_history = StageHistory(self.stage)


def _esc(win) -> None:
    from jarvis.ui.window import MainWindow
    MainWindow._do_interrupt(win)


@pytest.mark.parametrize("state", ["SPEAKING", "TRANSCRIBING"])
def test_esc_saat_bicara_tetap_interrupt(state) -> None:
    """do-not-regress: memotong ucapan adalah alasan utama tombol ini ada."""
    win = _FakeWin(state, "tasks")
    _esc(win)
    assert win.interrupted is True, "ESC tidak lagi memotong ucapan — REGRESI"
    assert win.stage.calls == [], "panel ikut ditutup saat harus interrupt"


def test_esc_saat_diam_dan_panel_terbuka_jadi_back() -> None:
    win = _FakeWin("LISTENING", "tasks")
    _esc(win)
    assert win.interrupted is False
    assert win.stage.calls == ["EMPTY"]


def test_esc_saat_diam_tanpa_panel_tetap_interrupt() -> None:
    win = _FakeWin("LISTENING", None)
    _esc(win)
    assert win.interrupted is True


# ── umpan balik instan tombol batal ──────────────────────────────────────

def test_chip_langsung_menandai_pembatalan(app) -> None:
    from jarvis.agent.tasks import TaskRegistry
    from jarvis.ui.task_strip import TaskStrip

    reg = TaskRegistry(bus=type("B", (), {"publish": lambda *a, **k: None})(),
                       max_concurrent=3, queue_max=20, poll_s=0.005)
    task = reg.submit("tugas panjang")
    reg.mark_running(task.id)

    strip = TaskStrip()
    strip.resize(800, strip.height())
    strip.set_tasks(reg.snapshot())

    seen: list[str] = []
    strip.cancel_requested.connect(seen.append)

    # Tandai seperti yang dilakukan mousePressEvent, tanpa mensimulasi klik.
    strip._cancelling.add(task.id)
    strip.cancel_requested.emit(task.id)

    assert seen == [task.id]
    assert task.id in strip._cancelling, "tanda pembatalan tidak tersimpan"


def test_tanda_pembatalan_dibersihkan_saat_task_selesai(app) -> None:
    from jarvis.agent.tasks import TaskRegistry
    from jarvis.ui.task_strip import TaskStrip

    reg = TaskRegistry(bus=type("B", (), {"publish": lambda *a, **k: None})(),
                       max_concurrent=3, queue_max=20, poll_s=0.005)
    task = reg.submit("tugas")
    reg.mark_running(task.id)
    strip = TaskStrip()
    strip.set_tasks(reg.snapshot())
    strip._cancelling.add(task.id)

    reg.finish(task.id, status=None, error="dibatalkan")
    strip.set_tasks(reg.snapshot())
    assert task.id not in strip._cancelling, "tanda menempel selamanya"


# ── audit tombol Task Deck ───────────────────────────────────────────────

def test_semua_tombol_task_deck_tersambung(app) -> None:
    """Tombol mati merusak kepercayaan pada seluruh UI — jadi didaftar."""
    from pathlib import Path as _P

    from jarvis.ui.task_deck import JsonlTail, TaskDeckPanel

    deck = TaskDeckPanel(tail=JsonlTail(_P("tidak-ada.jsonl")))
    for name in ("_back_btn", "_cancel_btn", "_result_btn"):
        button = getattr(deck, name, None)
        assert button is not None, f"{name} tidak ada"
        assert button.receivers(button.clicked) > 0, f"{name} tidak tersambung"

    assert deck._list.receivers(deck._list.currentItemChanged) > 0, \
        "klik baris tugas tidak tersambung"


def test_tombol_hasil_aktif_hanya_saat_ada_hasil(app) -> None:
    from pathlib import Path as _P

    from jarvis.agent.tasks import TaskRegistry
    from jarvis.ui.task_deck import JsonlTail, TaskDeckPanel

    reg = TaskRegistry(bus=type("B", (), {"publish": lambda *a, **k: None})(),
                       max_concurrent=3, queue_max=20, poll_s=0.005)
    deck = TaskDeckPanel(tail=JsonlTail(_P("tidak-ada.jsonl")))

    running = reg.submit("masih jalan")
    reg.mark_running(running.id)
    deck.set_tasks(reg.snapshot())
    deck.select(running.id)
    assert deck._cancel_btn.isEnabled() is True
    assert deck._result_btn.isEnabled() is False

    reg.finish(running.id, result="ini hasilnya")
    deck.set_tasks(reg.snapshot())
    deck.select(running.id)
    assert deck._cancel_btn.isEnabled() is False
    assert deck._result_btn.isEnabled() is True
