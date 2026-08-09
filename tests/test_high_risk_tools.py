"""Fase 36 — tool berisiko tinggi yang selama ini tanpa uji (S-36).

Audit 2026-08-08: 35 modul tidak pernah disebut satu pun uji. Di antaranya
`code_exec`, `file_ops`, `cron_tools`, `task_tools`, dan `session_tools` —
semuanya **aktif** di registry, dan semuanya bisa menjalankan kode, menulis
berkas, atau menjadwalkan pekerjaan.

Tiap tool di sini mendapat minimal satu jalur bahagia dan satu penolakan.
Jalur bahagia saja tidak cukup: yang menjaga Takeda adalah penolakannya, dan
penolakan yang tidak pernah diuji adalah penolakan yang tidak diketahui masih
bekerja.
"""
from __future__ import annotations

import asyncio

import pytest

from jarvis.agent import registry


def _run(name: str, args: dict):
    tool = registry.get(name)
    if tool is None:
        pytest.skip(f"{name} tidak terdaftar di mesin ini")
    return asyncio.run(tool.run(**args))


# ── execute_code ──────────────────────────────────────────────────────────

@pytest.mark.xfail(strict=True, reason="S-40 — interpreter tak dikutip; fase ini uji saja")
def test_execute_code_runs_and_returns_output():
    """S-40 — `execute_code` TIDAK PERNAH bisa jalan di mesin Takeda.

    `_RUNNERS["python"]` memakai `sys.executable` apa adanya di dalam
    `f'{cmd_prefix} "{script}"'` dengan `shell=True`. Path instalasi ini
    memuat spasi (`E:\jarvis agent\h`), jadi perintahnya terpotong::

        'E:\jarvis' is not recognized as an internal or external command

    Script-nya dikutip, interpreternya tidak. Tool ini terdaftar, terbuka
    untuk model, dan gagal setiap kali — tidak ada yang menyadarinya karena
    tidak ada satu pun uji.
    """
    result = _run("execute_code", {"code": "print(6 * 7)"})

    assert result.ok is True
    assert "42" in str(result.content)


def test_execute_code_reports_a_failing_snippet_as_failure():
    """Kode yang meledak harus dilaporkan gagal, bukan sukses dengan stderr."""
    result = _run("execute_code", {"code": "raise SystemExit(3)"})

    assert result.ok is False


@pytest.mark.xfail(strict=True, reason="S-40 — gagal lebih dulu sebelum sempat timeout")
def test_execute_code_is_bounded_by_a_timeout():
    """Tanpa batas waktu, satu loop tak berujung membekukan agent."""
    result = _run("execute_code", {"code": "while True:\n    pass",
                                   "timeout": 2})

    assert result.ok is False
    assert "waktu" in str(result.error or "").lower() \
        or "timeout" in str(result.error or "").lower()


def test_execute_code_rejects_an_unknown_language():
    result = _run("execute_code", {"code": "echo x", "language": "brainfuck"})

    assert result.ok is False


@pytest.mark.xfail(strict=True, reason="S-40 — interpreter tak dikutip")
def test_execute_code_runs_outside_the_workspace(tmp_path):
    """Sandbox subprocess-nya harus punya cwd sendiri, bukan root proyek —
    kalau tidak, satu skrip nyasar menulis di tengah kode sumber."""
    result = _run("execute_code", {"code": "import os; print(os.getcwd())"})

    assert result.ok is True
    assert "sandbox" in str(result.content).lower()


# ── file_ops ──────────────────────────────────────────────────────────────

def test_file_write_then_read_round_trips(tmp_path, monkeypatch):
    from jarvis.agent import paths
    from jarvis.agent.tools import file_ops

    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(file_ops, "workspace_root", lambda: tmp_path)

    written = _run("file_write", {"path": "catatan.txt", "content": "halo"})
    assert written.ok is True

    read = _run("file_read", {"path": "catatan.txt"})
    assert read.ok is True
    assert "halo" in str(read.content)


def test_file_read_of_a_missing_file_fails_clearly(tmp_path, monkeypatch):
    from jarvis.agent import paths
    from jarvis.agent.tools import file_ops

    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(file_ops, "workspace_root", lambda: tmp_path)

    result = _run("file_read", {"path": "tidak-pernah-ada.txt"})

    assert result.ok is False
    assert result.error


def test_file_list_walks_the_workspace(tmp_path, monkeypatch):
    from jarvis.agent import paths
    from jarvis.agent.tools import file_ops

    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(file_ops, "workspace_root", lambda: tmp_path)

    result = _run("file_list", {})

    assert result.ok is True
    assert "a.txt" in str(result.content)


# ── cron_tools ────────────────────────────────────────────────────────────

def test_cron_list_answers_without_raising():
    result = _run("cron_list", {})

    assert result.ok is True


def test_cron_delete_of_an_unknown_job_fails():
    """Menghapus yang tidak ada harus GAGAL, bukan melaporkan sukses kosong."""
    result = _run("cron_delete", {"id": "tidak-pernah-ada"})

    assert result.ok is False


def test_cron_delete_asks_before_deleting():
    tool = registry.get("cron_delete")
    if tool is None:
        pytest.skip("cron_delete tidak terdaftar")

    assert tool.requires_confirmation is True


# ── task_tools ────────────────────────────────────────────────────────────

def test_task_status_of_an_unknown_id_fails():
    result = _run("task_status", {"id": "tidak-pernah-ada"})

    assert result.ok is False


def test_task_cancel_of_an_unknown_id_fails():
    """Membatalkan yang tidak ada tidak boleh terlihat berhasil."""
    result = _run("task_cancel", {"id": "tidak-pernah-ada"})

    assert result.ok is False


# ── session_tools ─────────────────────────────────────────────────────────

def test_session_search_answers_a_plain_query():
    result = _run("session_search", {"query": "spotify"})

    assert result.ok is True


@pytest.mark.xfail(strict=True, reason="S-41 — kegagalan internal dilaporkan sukses")
def test_session_search_reports_an_internal_failure_as_failure():
    """S-41 — `session_search` mencatat ERROR lalu melapor `ok=True`.

    Dengan `query=None` ia melempar `AttributeError` di dalam, mencatat
    `session.search_failed` di log, lalu mengembalikan
    `ok=True, "tidak ada sesi yang cocok"`. Model membacanya sebagai
    "sudah dicari, memang tidak ada" — padahal pencariannya tidak pernah
    terjadi.

    Kegagalan palsu dalam bentuk terbalik: bukan sukses yang dinarasikan,
    melainkan kegagalan yang menyamar jadi hasil kosong yang sah.
    """
    result = _run("session_search", {"query": None})

    assert result.ok is False


# ── kontrak yang berlaku untuk semuanya ───────────────────────────────────

@pytest.mark.parametrize("name", [
    "execute_code", "file_read", "file_write", "file_patch", "file_list",
    "cron_list", "cron_create", "task_start", "task_status", "session_search",
])
def test_a_high_risk_tool_never_raises_to_its_caller(name):
    """`registry.execute` menjanjikan "tidak pernah raise"; toolnya sendiri
    juga tidak boleh, karena argumen datang dari MODEL."""
    tool = registry.get(name)
    if tool is None:
        pytest.skip(f"{name} tidak terdaftar")

    from jarvis.agent.base import ToolResult

    result = asyncio.run(registry.execute(name, {"path": None, "code": None,
                                                 "id": None, "query": None}))

    # Yang dijanjikan adalah TIDAK MELEMPAR — bukan harus gagal. Tool yang
    # memang tidak butuh argumen (cron_list, task_status) berhak berhasil.
    assert isinstance(result, ToolResult)
    assert result.ok or result.error
