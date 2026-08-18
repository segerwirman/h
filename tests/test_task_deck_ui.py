"""AUDIT_REPORT §8.5 — tiga lapis visibilitas Task Deck.

Fokus tes ini adalah kriteria yang gampang diam-diam salah:
orb TIDAK boleh berpindah ke EXECUTING, warna harus ikut tema, JSONL harus
dibaca inkremental, dan zona FROZEN harus tetap utuh.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication            # noqa: E402

from jarvis.agent.tasks import TaskRegistry         # noqa: E402
from jarvis.core import quiet                      # noqa: E402
from jarvis.ui import theme                         # noqa: E402
from jarvis.ui.orb import OrbState                  # noqa: E402
from jarvis.ui.task_deck import JsonlTail, TaskDeckPanel   # noqa: E402
from jarvis.ui.task_halo import TaskHaloOrb         # noqa: E402
from jarvis.ui.task_strip import TaskStrip          # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def reg():
    return TaskRegistry(bus=type("B", (), {"publish": lambda *a, **k: None})(),
                        max_concurrent=3, queue_max=20, poll_s=0.005)


# ── lapis 1: mini strip ──────────────────────────────────────────────────

def test_tiga_tugas_tiga_chip(app, reg) -> None:
    for i in range(3):
        t = reg.submit(f"tugas {i}")
        reg.mark_running(t.id)
        reg.update(t.id, iteration=5)
    strip = TaskStrip()
    strip.set_tasks(reg.snapshot())
    assert len(strip._views) == 3
    assert strip.isVisible() or strip._views, "strip tidak muncul"
    assert all(v.progress > 0 for v in strip._views), "progres tidak bergerak"


def test_strip_maksimum_tiga_chip_sisanya_overflow(app, reg) -> None:
    for i in range(5):
        t = reg.submit(f"tugas {i}")
        reg.mark_running(t.id)
    strip = TaskStrip()
    strip.set_tasks(reg.snapshot())
    assert len(strip._views) == 3
    assert strip._overflow == 2


def test_strip_tinggi_sesuai_config(app) -> None:
    from jarvis.core import config
    expected = int(config.get("ui.task_deck.mini_strip_height_px", 26))
    assert TaskStrip().height() == expected


def test_strip_autohide_setelah_semua_selesai(app, reg) -> None:
    strip = TaskStrip()
    strip._autohide_ms = 40                       # dipercepat untuk tes
    t = reg.submit("selesai cepat")
    reg.mark_running(t.id)
    strip.set_tasks(reg.snapshot())
    assert strip._views

    reg.finish(t.id, result="ok")
    strip.set_tasks(reg.snapshot())
    assert strip._all_done_since is not None, "hitung mundur auto-hide tidak mulai"
    assert strip._views == [], "chip aktif seharusnya kosong"

    time.sleep(0.06)
    strip._on_tick()
    assert strip.isHidden(), "strip tidak menghilang setelah tenggat"


def test_klik_chip_dan_tombol_batal_memancarkan_sinyal(app, reg) -> None:
    t = reg.submit("tugas klik")
    reg.mark_running(t.id)
    strip = TaskStrip()
    strip.resize(800, strip.height())
    strip.set_tasks(reg.snapshot())

    from PyQt6.QtGui import QPixmap
    from PyQt6.QtGui import QPainter
    pm = QPixmap(800, strip.height())
    painter = QPainter(pm)
    painter.end()
    strip.render(pm)                              # memaksa paintEvent → rects

    assert strip._chip_rects, "rect chip tidak terbentuk saat render"
    task_id, chip, close_btn = strip._chip_rects[0]
    assert task_id == t.id
    assert close_btn.width() > 0
    # tombol batal berada DI DALAM chip — kalau tidak, klik akan meleset
    assert chip.contains(close_btn.center())


# ── lapis 3: orb — kriteria paling kritis ────────────────────────────────

def test_orb_tetap_listening_saat_tugas_berjalan(app) -> None:
    """'Jarvis sibuk' ≠ 'Jarvis tidak tersedia'."""
    orb = TaskHaloOrb()
    orb.set_state(OrbState.LISTENING)
    orb.set_task_progress(0.42, count=2)
    assert orb.state is OrbState.LISTENING, "progres tugas mengubah state orb"
    assert orb.task_progress == pytest.approx(0.42)

    orb.set_task_progress(None)
    assert orb.state is OrbState.LISTENING


def test_lapis_task_tidak_pernah_mengubah_state_orb(app) -> None:
    """Invarian sebenarnya: modul Task Deck tidak boleh menyentuh state orb.

    Bukan sekadar 'tidak menyebut EXECUTING' — yang berbahaya adalah
    memanggil set_state sama sekali, apa pun nilainya.
    """
    import ast

    for name in ("task_halo.py", "task_wiring.py", "task_strip.py",
                 "task_deck.py"):
        tree = ast.parse(
            (ROOT / "jarvis" / "ui" / name).read_text(encoding="utf-8"))
        calls = [n.func.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)]
        assert "set_state" not in calls, (
            f"{name} memanggil set_state — itu bisa menghapus sinyal LISTENING")
        names = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)]
        assert "EXECUTING" not in names, f"{name} merujuk OrbState.EXECUTING"


def test_progress_arc_ter_clamp(app) -> None:
    orb = TaskHaloOrb()
    orb.set_task_progress(5.0)
    assert orb.task_progress == 1.0
    orb.set_task_progress(-2.0)
    assert orb.task_progress == 0.0


def test_orb_asli_tidak_diubah() -> None:
    """orb.py FROZEN — arc halo harus lewat subclass, bukan edit."""
    manifest = json.loads(
        (ROOT / "config" / "frozen_manifest.json").read_text(encoding="utf-8"))
    for name in ("jarvis/ui/orb.py", "jarvis/ui/theme.py"):
        entry = manifest["files"][name]
        digest = entry["sha256"] if isinstance(entry, dict) else entry
        mode = entry.get("mode", "text-lf") if isinstance(entry, dict) else "text-lf"
        raw = (ROOT / name).read_bytes()
        if mode == "text-lf":
            raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        assert hashlib.sha256(raw).hexdigest() == digest, f"{name} berubah"


# ── lapis 2: Task Deck + JSONL inkremental ───────────────────────────────

def test_jsonl_dibaca_inkremental(tmp_path: Path) -> None:
    path = tmp_path / "tools.jsonl"
    path.write_text(
        json.dumps({"tool": "web_search", "session": "s1", "ok": True}) + "\n",
        encoding="utf-8")
    tail = JsonlTail(path)

    assert tail.refresh() == 1
    first_offset = tail._offset
    assert tail.refresh() == 0, "berkas dibaca ulang penuh"
    assert tail._offset == first_offset

    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"tool": "file_read", "session": "s1",
                             "ok": False, "error": "x"}) + "\n")
    assert tail.refresh() == 1, "record baru tidak terbaca"
    assert len(tail.records()) == 2
    assert tail._offset > first_offset


def test_jsonl_rotasi_dan_baris_rusak(tmp_path: Path) -> None:
    path = tmp_path / "tools.jsonl"
    path.write_text('{"tool":"a","session":"s1"}\n{ RUSAK\n', encoding="utf-8")
    tail = JsonlTail(path)
    assert tail.refresh() == 1, "baris rusak menjatuhkan pembacaan"

    path.write_text('{"tool":"b","session":"s1"}\n', encoding="utf-8")  # rotasi
    tail.refresh()
    assert any(r.get("tool") == "b" for r in tail.records())


def test_jsonl_baris_rusak_mencatat_event(tmp_path: Path, monkeypatch) -> None:
    events = []
    monkeypatch.setattr(
        quiet, "swallowed",
        lambda event, exc=None, **_context: events.append(
            (event, type(exc).__name__ if exc is not None else None)),
    )
    path = tmp_path / "tools.jsonl"
    path.write_text(
        '{"tool":"a"}\n{ RUSAK\n{"tool":"b"}\n',
        encoding="utf-8")
    tail = JsonlTail(path)

    assert tail.refresh() == 2
    assert [record["tool"] for record in tail.records()] == ["a", "b"]
    assert events == [("ui.task_deck.line_skipped", "JSONDecodeError")]


def test_jsonl_hilang_tidak_menjatuhkan(tmp_path: Path) -> None:
    tail = JsonlTail(tmp_path / "tidak-ada.jsonl")
    assert tail.refresh() == 0
    assert tail.records() == []


def test_deck_filter_per_sesi(tmp_path: Path) -> None:
    path = tmp_path / "tools.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"tool": "a", "session": "s1", "ok": True}) + "\n")
        fh.write(json.dumps({"tool": "b", "session": "s2", "ok": True}) + "\n")
    tail = JsonlTail(path)
    tail.refresh()
    assert [r["tool"] for r in tail.for_session("s1")] == ["a"]
    assert tail.for_session("") == []


def test_deck_menampilkan_tugas_dan_detail(app, reg, tmp_path: Path) -> None:
    path = tmp_path / "tools.jsonl"
    path.write_text(
        json.dumps({"tool": "web_search", "session": "sess-1", "ok": True})
        + "\n", encoding="utf-8")
    tail = JsonlTail(path)
    tail.refresh()

    deck = TaskDeckPanel(tail=tail)
    t = reg.submit("riset laptop")
    reg.update(t.id, session_id="sess-1")
    reg.mark_running(t.id)
    reg.update(t.id, iteration=7, step="web_search → laptop")

    deck.set_tasks(reg.snapshot())
    assert deck._list.count() == 1
    deck.select(t.id)
    text = deck._detail.toPlainText()
    assert t.id in text
    assert "web_search → laptop" in text
    assert "JEJAK TOOL" in text
    assert deck._cancel_btn.isEnabled(), "tugas aktif harus bisa dibatalkan"


def test_deck_aktif_di_atas_selesai(app, reg) -> None:
    done = reg.submit("sudah selesai")
    reg.finish(done.id, result="ok")
    running = reg.submit("masih jalan")
    reg.mark_running(running.id)

    deck = TaskDeckPanel(tail=JsonlTail(Path("tidak-ada.jsonl")))
    deck.set_tasks(reg.snapshot())
    first = deck._list.item(0).text()
    assert running.id in first, "tugas aktif tidak diletakkan di atas"


def test_deck_kosong_tidak_crash(app, reg) -> None:
    deck = TaskDeckPanel(tail=JsonlTail(Path("tidak-ada.jsonl")))
    deck.set_tasks([])
    assert "Tidak ada tugas" in deck._detail.toPlainText()
    assert not deck._cancel_btn.isEnabled()


# ── tema ─────────────────────────────────────────────────────────────────

def test_warna_ikut_tema(app, reg) -> None:
    deck = TaskDeckPanel(tail=JsonlTail(Path("tidak-ada.jsonl")))
    original = theme.PAL.name
    try:
        theme.PAL.set_active("cyan_gold")
        deck.set_tasks([])
        cyan = deck._list.styleSheet()
        theme.PAL.set_active("stealth_dark")
        deck.set_tasks([])
        stealth = deck._list.styleSheet()
        assert cyan != stealth, "warna task deck tidak ikut berubah saat ganti tema"
    finally:
        theme.PAL.set_active(original)


def test_tidak_ada_warna_hardcode() -> None:
    """Aturan §8.5.1 — semua warna dari theme.py."""
    import re

    for name in ("task_strip.py", "task_deck.py", "task_halo.py",
                 "task_wiring.py"):
        src = (ROOT / "jarvis" / "ui" / name).read_text(encoding="utf-8")
        hits = re.findall(r"#[0-9a-fA-F]{3,8}\b", src)
        assert not hits, f"{name} memakai warna hardcode: {hits}"


# ── ikon ActionPanel ─────────────────────────────────────────────────────

def test_ikon_tasks_terdaftar_dan_ada_di_config() -> None:
    from jarvis.core import config
    from jarvis.ui import actionpanel, task_wiring

    assert task_wiring.ICON_NAME in actionpanel._ICONS, \
        "glyph tidak terdaftar sebelum ActionPanel dibangun"
    glyph, tip = actionpanel._ICONS[task_wiring.ICON_NAME]
    assert len(glyph) == 1, "ikon harus satu glyph, sekelas ikon lain"
    assert tip

    # Kunci nyatanya "action_panel.icons" (top-level), BUKAN
    # "ui.action_panel.icons" — actionpanel.py:139 memakai
    # config.section("action_panel").
    icons = config.get("action_panel.icons", [])
    assert task_wiring.ICON_NAME in icons
    assert config.get("ui.action_panel.icons", None) is None


def test_actionpanel_membuat_tombol_tasks(app) -> None:
    from jarvis.ui.actionpanel import ActionPanel
    from jarvis.ui import task_wiring

    panel = ActionPanel(None)
    assert task_wiring.ICON_NAME in panel._buttons, \
        "tombol tasks tidak dibuat — wiring tidak akan menemukannya"


# ── integrasi: MainWindow sungguhan ──────────────────────────────────────

@pytest.fixture()
def win(app):
    import os

    os.environ.setdefault("JARVIS_NO_MIC_METER", "1")
    from jarvis.core.focus_mode import FocusMode
    from jarvis.ui.window import MainWindow

    FocusMode._reset_for_tests()
    window = MainWindow(services={})
    yield window
    window.close()


def test_tiga_lapis_terpasang_di_window_nyata(win) -> None:
    from jarvis.agent.tasks import REGISTRY
    from jarvis.ui.task_halo import TaskHaloOrb

    assert win.stage.widget("tasks") is not None, "panel tasks tidak terdaftar"
    assert getattr(win, "task_strip", None) is not None, "mini strip tidak dibuat"
    assert isinstance(win.orb, TaskHaloOrb), "orb bukan subclass ber-arc"
    assert "tasks" in win.action_panel._buttons

    REGISTRY.clear()
    try:
        for i in range(2):
            t = REGISTRY.submit(f"tugas nyata {i}")
            REGISTRY.mark_running(t.id)
            REGISTRY.update(t.id, iteration=10)
        win._task_refresh()

        assert len(win.task_strip._views) == 2
        assert win.orb.task_progress is not None, "arc halo tidak menerima progres"
        assert win.orb.state is not OrbState.EXECUTING, \
            "orb berpindah ke EXECUTING — kriteria kritis §8.5 gagal"

        for view in REGISTRY.snapshot():
            REGISTRY.finish(view.id, result="ok")
        win._task_refresh()
        assert win.orb.task_progress is None, "arc tidak hilang saat semua selesai"
    finally:
        REGISTRY.clear()
