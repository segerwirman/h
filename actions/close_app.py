"""Menutup aplikasi BERNAMA — dengan anggun, dan tidak pernah Jarvis sendiri.

DIAGNOSIS_2 MASALAH 3: satu-satunya cara menutup aplikasi selama ini adalah
``actions/computer_settings.py:174`` ``close_app()`` yang menekan Alt+F4 buta
ke jendela yang sedang fokus — tanpa parameter, tanpa target, tanpa
konfirmasi. Setelah user bicara ke Jarvis, jendela fokus sering kali Jarvis.

Modul ini menggantikannya dengan alur yang eksplisit:

    1. resolusi target dari proses yang benar-benar berjalan
    2. ``process_guard.assert_not_self`` — SEBELUM tindakan apa pun
    3. tidak ketemu   → laporkan, jangan diam
    4. ketemu satu    → tutup ANGGUN (WM_CLOSE/SIGTERM), tunggu, baru paksa
    5. ketemu banyak  → tanya, jangan tebak

Penutupan anggun adalah default dan tidak bisa ditawar. ``force`` hanya
mempercepat langkah TERAKHIR setelah cara sopan gagal — ia tidak pernah
melewati guard.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from jarvis.core import log, process_guard, quiet
from jarvis.core.process_guard import SelfTerminationBlocked

_logger = log.get("actions.close_app")

GRACE_SECONDS = 3.0

STATUS_CLOSED = "closed"
STATUS_NOT_RUNNING = "not_running"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_BLOCKED = "blocked"
STATUS_FAILED = "failed"


@dataclass
class CloseOutcome:
    ok: bool
    status: str
    message: str
    closed: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"ok": self.ok, "status": self.status, "message": self.message,
                "closed": self.closed, "candidates": self.candidates}


def _matches(name: str) -> list:
    """Proses berjalan yang cocok dengan nama, lewat skor app_registry."""
    from jarvis.core import app_registry

    query = app_registry.normalize(name)
    if not query:
        return []
    match = app_registry.resolve(query)
    targets = {query}
    if match is not None:
        targets.add(app_registry.normalize(match.key))

    out = []
    for app in app_registry.list_running():
        key = app_registry.normalize(app.name.rsplit(".", 1)[0])
        title = app_registry.normalize(app.window_title)
        hit = any(t == key or t in key or key in t for t in targets if t)
        if not hit and title:
            hit = any(t and t in title for t in targets)
        if hit:
            out.append(app)
    return out


def _names_the_app(name: str, apps: list) -> bool:
    """Apakah permintaan ini benar-benar MENYEBUT aplikasi yang ditemukan?

    S-20: "browser" tidak dikenal ``app_registry`` dan hanya cocok sebagai
    SUBSTRING dari "Tabbit Browser". Perlakuan lama menganggapnya kepastian
    dan menutup aplikasi yang tidak pernah diminta user, lalu melaporkannya
    memakai kata user sehingga terdengar seperti keberhasilan.

    Kuat bila: registry memetakan namanya ke sebuah aplikasi, ATAU nama proses
    salah satu kandidat sama persis dengan yang diminta.
    """
    from jarvis.core import app_registry

    query = app_registry.normalize(name)
    if not query:
        return False
    if app_registry.resolve(query) is not None:
        return True
    for app in apps:
        key = app_registry.normalize(
            str(getattr(app, "name", "")).rsplit(".", 1)[0])
        if key and key == query:
            return True
    return False


def _graceful(app) -> bool:
    """WM_CLOSE dulu (aplikasi masih bisa menawarkan simpan), lalu SIGTERM.

    Sengaja TIDAK memakai psutil.terminate() sebagai langkah pertama di
    Windows: di sana ia memanggil TerminateProcess — pembunuhan keras yang
    membuang data user tanpa peringatan.
    """
    try:
        import pygetwindow as gw
        import win32process

        for win in gw.getAllWindows():
            if not (getattr(win, "title", "") or "").strip():
                continue
            try:
                _tid, pid = win32process.GetWindowThreadProcessId(win._hWnd)
            except Exception as exc:                         # noqa: BLE001
                quiet.swallowed("close_app.window_probe_failed", exc,
                                pid=app.pid)
                continue
            if int(pid or 0) == app.pid:
                win.close()                                  # WM_CLOSE
                return True
    except Exception as exc:                                 # noqa: BLE001
        quiet.swallowed("close_app.wm_enum_failed", exc, pid=app.pid)

    try:
        import psutil
        psutil.Process(app.pid).terminate()                  # SIGTERM
        return True
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("close_app.graceful_failed", pid=app.pid,
                        error=str(exc)[:100])
        return False


def _alive(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid) and psutil.Process(pid).is_running()
    except Exception:                                        # noqa: BLE001
        return False


def _hard_kill(app) -> bool:
    # Guard diulang di sini dengan sengaja: ini titik paling tidak bisa
    # dibatalkan di seluruh repo, dan pemanggil bisa saja berubah.
    process_guard.assert_not_self(app)
    try:
        import psutil
        psutil.Process(app.pid).kill()
        return True
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("close_app.kill_failed", pid=app.pid,
                        error=str(exc)[:100])
        return False


def close_app(name: str, force: bool = False, all_windows: bool = False,
              grace_s: float = GRACE_SECONDS) -> CloseOutcome:
    """Tutup aplikasi bernama. Tidak pernah menutup Jarvis."""
    target = str(name or "").strip()
    if not target:
        return CloseOutcome(
            False, STATUS_AMBIGUOUS,
            "Aplikasi mana yang harus ditutup? Sebutkan namanya.")

    # Penolakan paling awal: nama yang jelas-jelas menunjuk Jarvis tidak
    # perlu menyentuh daftar proses sama sekali.
    if process_guard.refers_to_jarvis(target) or \
            process_guard.is_protected_name(target):
        return CloseOutcome(
            False, STATUS_BLOCKED,
            f"Saya tidak menutup '{target}' lewat perintah ini — itu saya "
            f"sendiri. Kalau memang ingin saya berhenti, katakan langsung "
            f"'matikan dirimu' dan saya akan meminta konfirmasi dulu.")

    found = _matches(target)

    # Guard diterapkan ke SETIAP kandidat sebelum apa pun terjadi.
    for app in found:
        try:
            process_guard.assert_not_self(app)
        except SelfTerminationBlocked as blocked:
            return CloseOutcome(False, STATUS_BLOCKED, str(blocked))

    if not found:
        return CloseOutcome(
            False, STATUS_NOT_RUNNING,
            f"{target.title()} sepertinya tidak sedang berjalan.")

    # S-20 — tebakan longgar bukan kepastian. Nama yang tidak dikenal registry
    # dan hanya cocok sebagai substring bisa mendarat di aplikasi yang sama
    # sekali lain ("browser" -> Tabbit Browser). Sebutkan apa yang ditemukan,
    # lalu tanya; jangan menutup milik user atas dasar tebakan.
    if not _names_the_app(target, found):
        labels = [str(a.window_title or a.name) for a in found[:4]]
        return CloseOutcome(
            False, STATUS_AMBIGUOUS,
            f"'{target}' tidak saya kenali sebagai nama aplikasi. Yang cocok: "
            f"{', '.join(labels)}. Tutup yang mana?",
            candidates=labels)

    distinct = {app.pid for app in found}
    if len(distinct) > 1 and not all_windows:
        titles = [f"{a.window_title or a.name}" for a in found[:4]]
        return CloseOutcome(
            False, STATUS_AMBIGUOUS,
            f"Ada {len(distinct)} jendela {target.title()}. Semuanya, atau "
            f"yang mana?",
            candidates=titles)

    closed: list[str] = []
    stubborn: list = []
    for app in found:
        label = app.window_title or app.name
        if _graceful(app):
            stubborn.append((app, label))
        else:
            _logger.info("close_app.graceful_unavailable", pid=app.pid)
            stubborn.append((app, label))

    deadline = time.monotonic() + max(0.0, grace_s)
    while time.monotonic() < deadline:
        stubborn = [(a, lb) for a, lb in stubborn if _alive(a.pid)]
        if not stubborn:
            break
        time.sleep(0.1)

    for app, label in list(stubborn):
        if not _alive(app.pid):
            stubborn.remove((app, label))

    for app, label in stubborn:
        if not force:
            continue
        if _hard_kill(app):
            closed.append(label)

    survivors = [lb for a, lb in stubborn if _alive(a.pid)]
    for app in found:
        label = app.window_title or app.name
        if not _alive(app.pid) and label not in closed:
            closed.append(label)

    if survivors and not force:
        return CloseOutcome(
            False, STATUS_FAILED,
            f"{target.title()} belum menutup — mungkin ada dialog 'simpan "
            f"perubahan' yang menunggu. Katakan 'paksa tutup' kalau memang "
            f"ingin dipaksa.",
            closed=closed, candidates=survivors)
    if survivors:
        return CloseOutcome(False, STATUS_FAILED,
                            f"Gagal menutup {', '.join(survivors)}.",
                            closed=closed, candidates=survivors)

    # S-20 — sebut yang BENAR-BENAR tertutup, bukan kata yang diucapkan user.
    # Bentuk lama `f"{target.title()} ditutup."` menggemakan permintaan,
    # sehingga menutup aplikasi yang salah tetap terdengar seperti keberhasilan.
    names = ", ".join(dict.fromkeys(closed)) or target.title()
    return CloseOutcome(True, STATUS_CLOSED, f"{names} ditutup.",
                        closed=closed)


def close_app_action(parameters: dict | None = None, response=None,
                     player=None, session_memory=None) -> str:
    """Adaptor gaya ``actions/*`` untuk lane suara legacy."""
    params = parameters or {}
    outcome = close_app(
        str(params.get("app_name") or params.get("name") or ""),
        force=str(params.get("force", "")).lower() in ("1", "true", "yes",
                                                       "paksa"),
        all_windows=str(params.get("all_windows", "")).lower() in ("1", "true",
                                                                   "yes"))
    if player is not None:
        try:
            player.write_log(f"[close_app] {outcome.status}")
        except Exception as exc:                             # noqa: BLE001
            quiet.swallowed("close_app.player_log_failed", exc,
                            status=outcome.status)
    return outcome.message


__all__ = ["close_app", "close_app_action", "CloseOutcome", "GRACE_SECONDS",
           "STATUS_CLOSED", "STATUS_NOT_RUNNING", "STATUS_AMBIGUOUS",
           "STATUS_BLOCKED", "STATUS_FAILED"]
