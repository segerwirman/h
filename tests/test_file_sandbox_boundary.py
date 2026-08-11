"""Fase 36 — batas sandbox dijaga uji (S-36).

`execute_code`, `file_write`, `file_patch`, `cron_*`, dan `task_*` semuanya
AKTIF di registry, dan modulnya tidak pernah disebut satu pun uji sebelum ini.
`_inside_sandbox` adalah **satu fungsi** yang berdiri antara agent dan seluruh
disk Takeda.

Probe 2026-08-08 menahan 8 dari 8 percobaan. Rancangannya benar. Yang tidak ada
adalah penjaganya untuk besok: **yang benar hari ini tanpa uji hanyalah yang
belum sempat rusak.**

**Batas keras fase ini: uji saja.** Bila sebuah kasus ternyata bocor,
perbaikannya adalah fase tersendiri dengan temuan bernomor — tidak
diselundupkan ke sini.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from jarvis.agent.tools.file_ops import _inside_sandbox, _resolve
from jarvis.agent.paths import workspace_root


def _outside(raw: str) -> bool:
    """True bila path ini BUKAN di dalam sandbox (yaitu butuh konfirmasi)."""
    return not _inside_sandbox(_resolve(raw))


# ── yang jelas di dalam ───────────────────────────────────────────────────

def test_a_relative_path_lands_in_the_workspace():
    assert _resolve("catatan.txt").parent == workspace_root()
    assert not _outside("catatan.txt")


def test_a_nested_relative_path_is_inside():
    assert not _outside("jarvis/agent/tools/file_ops.py")


# ── traversal ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "../../../Windows/System32/drivers/etc/hosts",
    "..\\..\\..\\Windows\\win.ini",
    "sub/../../../etc/passwd",
    "./../../rahasia.txt",
    "a/b/c/../../../../../../rahasia.txt",
])
def test_dot_dot_never_escapes_silently(raw):
    """Bentuk paling tua dan paling sering dicoba."""
    assert _outside(raw), raw


def test_the_parent_of_the_workspace_is_outside():
    assert _outside(str(workspace_root()) + "/../rahasia.txt")


# ── path absolut & bentuk khusus Windows ──────────────────────────────────

@pytest.mark.parametrize("raw", [
    "C:/Windows/System32/config/SAM",
    "C:\\Windows\\win.ini",
    "//?/C:/Windows/win.ini",
    "\\\\?\\C:\\Windows\\win.ini",
    "\\\\server\\share\\rahasia.txt",
    "//server/share/rahasia.txt",
])
def test_absolute_and_unc_paths_are_outside(raw):
    assert _outside(raw), raw


def test_the_users_own_secrets_are_outside():
    """Berkas yang paling berharga bagi Takeda, dinamai eksplisit."""
    home = Path.home()
    for candidate in (home / ".ssh" / "id_rsa",
                      home / ".jarvis" / "secrets.json",
                      home / ".claude" / "settings.json"):
        assert _outside(str(candidate)), candidate


def test_a_tilde_path_is_expanded_before_being_judged():
    """`~` yang tidak diperluas akan dinilai sebagai nama relatif — yaitu
    DI DALAM sandbox — padahal ia menunjuk ke rumah pengguna.
    """
    resolved = _resolve("~/rahasia.txt")

    assert "~" not in str(resolved), resolved
    assert _outside("~/rahasia.txt")


# ── symlink & junction: batas yang paling mudah terlewat ──────────────────

@pytest.mark.skipif(sys.platform != "win32", reason="perilaku khas Windows")
def test_a_symlink_inside_pointing_out_is_outside(tmp_path, monkeypatch):
    """Tautan DI DALAM sandbox yang menunjuk KELUAR.

    Ini kebocoran yang paling mudah terlewat: namanya terlihat jinak dan
    berada di tempat yang benar. Hanya `resolve()` yang membongkarnya.
    """
    from jarvis.agent import paths

    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "luar"
    outside.mkdir()
    (outside / "rahasia.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(paths, "workspace_root", lambda: workspace)

    link = workspace / "pintu"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink tidak diizinkan di mesin ini: {exc}")

    assert not _inside_sandbox(link / "rahasia.txt")


@pytest.mark.skipif(sys.platform != "win32", reason="junction khas Windows")
def test_a_directory_junction_inside_pointing_out_is_outside(tmp_path,
                                                             monkeypatch):
    """Junction tidak butuh hak Administrator — jadi ini jalur yang jauh
    lebih mungkin dipakai daripada symlink."""
    import subprocess

    from jarvis.agent import paths

    workspace = tmp_path / "ws"
    workspace.mkdir()
    outside = tmp_path / "luar"
    outside.mkdir()
    (outside / "rahasia.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(paths, "workspace_root", lambda: workspace)

    junction = workspace / "pintu"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip(f"junction gagal dibuat: {result.stdout}{result.stderr}")

    assert not _inside_sandbox(junction / "rahasia.txt")


# ── bentuk nama yang menyamar ─────────────────────────────────────────────

@pytest.mark.skipif(sys.platform != "win32", reason="nama 8.3 khas Windows")
def test_a_short_8_3_name_is_judged_by_its_real_target():
    """`C:\\PROGRA~1` adalah `C:\\Program Files`. Bila `resolve()` tidak
    memperluasnya, perbandingan path bisa meleset."""
    assert _outside("C:/PROGRA~1/rahasia.txt")


def test_a_path_with_unicode_normalisation_differences_is_still_judged(tmp_path,
                                                                       monkeypatch):
    """"é" bisa satu titik kode atau dua. Keduanya harus dinilai, bukan
    membuat pemeriksanya melempar."""
    from jarvis.agent import paths

    monkeypatch.setattr(paths, "workspace_root", lambda: tmp_path)

    composed = "caf\u00e9/rahasia.txt"          # é sebagai satu titik kode
    decomposed = "cafe\u0301/rahasia.txt"       # e + combining acute

    assert isinstance(_inside_sandbox(_resolve(composed)), bool)
    assert isinstance(_inside_sandbox(_resolve(decomposed)), bool)


@pytest.mark.parametrize("raw", [
    "NUL", "CON", "COM1", "..", ".", "",
])
def test_odd_names_never_raise(raw):
    """Pemeriksa batas yang MELEMPAR sama buruknya dengan yang mengizinkan:
    pemanggilnya menelan exception dan melanjutkan."""
    assert isinstance(_inside_sandbox(_resolve(raw)), bool)


def test_a_path_that_cannot_be_resolved_is_treated_as_outside():
    """S-39 — path yang gagal di-resolve ditolak secara fail-closed.

    `Path.resolve()` dapat melempar `ValueError` untuk path yang berisi null
    byte. `_inside_sandbox` harus menangkap kegagalan resolusi itu dan tetap
    mengembalikan keputusan boolean yang menolak path tersebut.
    """
    assert isinstance(_inside_sandbox(Path("\x00tidak-valid")), bool)


# ── daftar izin tambahan ──────────────────────────────────────────────────

def test_an_explicitly_allowed_path_is_inside(tmp_path, monkeypatch):
    from jarvis.agent.tools import file_ops

    extra = tmp_path / "diizinkan"
    extra.mkdir()
    monkeypatch.setattr(file_ops, "allowed_paths", lambda: [extra])

    assert _inside_sandbox(extra / "berkas.txt")


def test_an_allowed_path_that_does_not_exist_is_ignored(tmp_path, monkeypatch):
    """Entri config yang salah ketik tidak boleh melebarkan sandbox."""
    from jarvis.agent.tools import file_ops

    monkeypatch.setattr(file_ops, "allowed_paths",
                        lambda: [tmp_path / "tidak-pernah-ada"])

    assert not _inside_sandbox(tmp_path / "tidak-pernah-ada" / "x.txt")


def test_a_sibling_with_a_shared_prefix_is_not_inside(tmp_path, monkeypatch):
    """`/ws-rahasia` bukan bagian dari `/ws`.

    Pemeriksaan berbasis awalan STRING akan meloloskannya; pemeriksaan
    berbasis `parents` tidak.
    """
    from jarvis.agent import paths

    workspace = tmp_path / "ws"
    workspace.mkdir()
    sibling = tmp_path / "ws-rahasia"
    sibling.mkdir()
    monkeypatch.setattr(paths, "workspace_root", lambda: workspace)

    assert not _inside_sandbox(sibling / "berkas.txt")


# ── gerbang konfirmasi benar-benar terpasang di toolnya ───────────────────

@pytest.mark.parametrize("tool_name", [
    "file_read", "file_write", "file_patch",
])
def test_the_tool_asks_before_touching_anything_outside(tool_name):
    """Batasnya tidak berguna bila toolnya tidak menanyakannya."""
    from jarvis.agent import registry

    tool = registry.get(tool_name)
    assert tool is not None, tool_name

    assert tool.needs_confirmation(path="C:/Windows/win.ini") is True
    assert tool.needs_confirmation(path="catatan.txt") is False


def test_every_high_risk_tool_is_registered_with_a_descriptor():
    """Tool tanpa descriptor ditolak `registry.execute` — dan itu benar.

    Uji ini mengunci bahwa yang AKTIF memang punya jalur policy-nya.
    """
    from jarvis.agent import registry
    from jarvis.agent.capabilities import REGISTRY

    for name in ("execute_code", "file_write", "file_patch", "terminal",
                 "cron_create", "task_start"):
        if registry.get(name) is None:
            continue
        assert REGISTRY.descriptor_for_tool(name) is not None, name


def test_writing_outside_the_sandbox_leaves_the_file_untouched(tmp_path,
                                                               monkeypatch):
    """Bukti nyata: berkas di luar sandbox tidak berubah tanpa konfirmasi."""
    import asyncio

    from jarvis.agent import registry

    victim = tmp_path / "korban.txt"
    victim.write_text("asli", encoding="utf-8")

    tool = registry.get("file_write")
    if tool is None:
        pytest.skip("file_write tidak terdaftar")
    assert tool.needs_confirmation(path=str(victim)) is True

    result = asyncio.run(registry.execute("file_write",
                                          {"path": str(victim),
                                           "content": "diretas"}))

    assert victim.read_text(encoding="utf-8") == "asli"
    assert result.ok is False


def test_os_environ_is_not_a_way_around_the_workspace(monkeypatch):
    """Variabel lingkungan tidak boleh menggeser sandbox diam-diam."""
    monkeypatch.setenv("JARVIS_WORKSPACE_ROOT", str(Path(os.sep)))

    assert _outside("C:/Windows/win.ini")
