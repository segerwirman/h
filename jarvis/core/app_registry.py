"""Indeks aplikasi terpasang — supaya router tahu, bukan menebak.

DIAGNOSIS_2 MASALAH 1: penemuan aplikasi selama ini hanya tabel alias
hardcoded + ``shutil.which`` + tebakan Start Menu buta
(``actions/open_app.py:103-112`` menekan Win, mengetik nama, lalu Enter —
kalau Windows tak menemukan apa pun, Enter membuka pencarian web). Modul ini
menggantikan tebakan itu dengan indeks nyata.

Sumber per platform:
    Windows : pintasan Start Menu (.lnk), Start Apps/UWP, registry, PATH
    macOS   : /Applications, ~/Applications, mdfind
    Linux   : .desktop di /usr/share/applications, ~/.local/share/applications

Tiga hal yang membuat modul ini berguna, bukan sekadar daftar:

1. ``resolve()`` mengembalikan **skor**, sehingga pemanggil bisa membedakan
   "yakin" dari "mungkin" — dan memilih bertanya saat ragu.
2. Alias yang dipelajari disimpan ke disk, jadi "ig" → Instagram makin akurat
   seiring pemakaian.
3. Preferensi ambigu ("kalau saya bilang instagram, maksud saya aplikasi")
   disimpan terpisah, sehingga Jarvis hanya bertanya **sekali**.

Tidak pernah melempar: indeks yang gagal dibangun = indeks kosong, dan
pemanggil tetap berjalan.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from jarvis.core import config, log, quiet

_logger = log.get("core.app_registry")
_SYSTEM = platform.system()
_lock = threading.RLock()

# Seed alias — singkatan yang lazim dipakai orang tapi tidak akan pernah
# ditemukan oleh pencocokan string apa pun ("wa" vs "WhatsApp").
_SEED_ALIASES: dict[str, str] = {
    "ig": "instagram", "insta": "instagram",
    "wa": "whatsapp", "tg": "telegram",
    "vsc": "visual studio code", "vscode": "visual studio code",
    "code": "visual studio code",
    "ps": "photoshop", "ae": "after effects", "pr": "premiere pro",
    "chrome": "google chrome", "yt": "youtube",
    "explorer": "file explorer", "cmd": "command prompt",
    "calc": "calculator", "kalkulator": "calculator",
}

_CACHE_TTL_S = 900.0
_MIN_SCORE = 0.60

_index: dict[str, "AppMatch"] = {}
_index_built_at: float = 0.0
_refreshing = False


@dataclass(frozen=True)
class AppMatch:
    key: str          # nama ternormalisasi
    name: str         # nama tampil
    target: str       # yang diluncurkan (exe / path .lnk / bundle / .desktop)
    source: str       # start_menu | start_apps | registry | path | applications | desktop
    score: float = 1.0


@dataclass(frozen=True)
class RunningApp:
    name: str
    pid: int
    window_title: str = ""


# ── normalisasi ──────────────────────────────────────────────────────────

_PUNCT_RE = re.compile(r"[^a-z0-9]+")
# Kata yang tidak membedakan aplikasi satu dengan lainnya.
_NOISE = {"app", "aplikasi", "program", "aplikasinya", "the", "buka", "open"}


def normalize(text: str) -> str:
    cleaned = _PUNCT_RE.sub(" ", str(text or "").lower()).strip()
    tokens = [t for t in cleaned.split() if t and t not in _NOISE]
    return " ".join(tokens)


# ── penyimpanan alias & preferensi ───────────────────────────────────────

def _store_path() -> Path:
    return Path(config.resolve_path("data/app_aliases.json"))


def _load_store() -> dict:
    try:
        raw = json.loads(_store_path().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw.setdefault("aliases", {})
            raw.setdefault("preferences", {})
            return raw
    except (OSError, ValueError):
        pass
    return {"aliases": {}, "preferences": {}}


def _save_store(data: dict) -> bool:
    try:
        path = _store_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(path)                      # atomic — tidak pernah separuh
        return True
    except OSError as exc:
        _logger.warning("app_registry.save_failed", error=str(exc)[:120])
        return False


def learn_alias(alias: str, app_name: str) -> bool:
    """Ingat bahwa ``alias`` berarti ``app_name``."""
    key, target = normalize(alias), normalize(app_name)
    if not key or not target or key == target:
        return False
    with _lock:
        data = _load_store()
        data["aliases"][key] = target
        return _save_store(data)


def preference_for(name: str) -> str | None:
    """``"app"`` | ``"web"`` | ``None`` — jawaban user sebelumnya untuk nama
    ambigu ini. Inilah yang membuat Jarvis bertanya sekali saja."""
    key = normalize(name)
    if not key:
        return None
    value = _load_store()["preferences"].get(key)
    return value if value in ("app", "web") else None


def remember_preference(name: str, kind: str) -> bool:
    key = normalize(name)
    if not key or kind not in ("app", "web"):
        return False
    with _lock:
        data = _load_store()
        data["preferences"][key] = kind
        return _save_store(data)


def forget_preference(name: str) -> bool:
    key = normalize(name)
    with _lock:
        data = _load_store()
        if data["preferences"].pop(key, None) is None:
            return False
        return _save_store(data)


# ── penemuan per platform ────────────────────────────────────────────────

def _scan_windows() -> dict[str, AppMatch]:
    found: dict[str, AppMatch] = {}
    roots = [
        Path(os.environ.get("ProgramData", r"C:\ProgramData"))
        / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("APPDATA", ""))
        / "Microsoft/Windows/Start Menu/Programs",
    ]
    for root in roots:
        try:
            if not root.is_dir():
                continue
            for lnk in root.rglob("*.lnk"):
                key = normalize(lnk.stem)
                if key and key not in found:
                    found[key] = AppMatch(key, lnk.stem, str(lnk), "start_menu")
        except OSError:
            continue

    # Microsoft Store/UWP apps do not necessarily create a filesystem .lnk.
    # Get-StartApps is read-only and gives us an exact AppUserModelID that can
    # be launched through shell:AppsFolder, avoiding blind Start-menu typing.
    try:
        startup = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-StartApps | Select-Object Name,AppID | "
                "ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=6,
            creationflags=startup,
        )
        payload = json.loads(result.stdout or "[]")
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("Name", "") or "").strip()
            app_id = str(row.get("AppID", "") or "").strip()
            key = normalize(name)
            if key and app_id and key not in found:
                found[key] = AppMatch(
                    key,
                    name,
                    rf"shell:AppsFolder\{app_id}",
                    "start_apps",
                )
    except (OSError, ValueError, subprocess.SubprocessError):
        pass

    try:
        import winreg

        hives = [
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER,
             r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for hive, path in hives:
            try:
                with winreg.OpenKey(hive, path) as root_key:
                    count = winreg.QueryInfoKey(root_key)[0]
                    for i in range(count):
                        try:
                            sub = winreg.EnumKey(root_key, i)
                            with winreg.OpenKey(root_key, sub) as k:
                                name = str(winreg.QueryValueEx(
                                    k, "DisplayName")[0]).strip()
                                try:
                                    icon = str(winreg.QueryValueEx(
                                        k, "DisplayIcon")[0]).strip()
                                except OSError:
                                    icon = ""
                        except OSError:
                            continue
                        key = normalize(name)
                        if key and key not in found:
                            raw_icon = icon.strip()
                            if raw_icon.startswith('"') and '"' in raw_icon[1:]:
                                target = raw_icon.split('"', 2)[1]
                            else:
                                target = re.sub(
                                    r",\s*-?\d+$", "", raw_icon).strip('" ')
                            target = os.path.expandvars(target)
                            if target and Path(target).is_file():
                                found[key] = AppMatch(
                                    key, name, target, "registry")
                            else:
                                # Keep the install evidence for routing. The
                                # launcher will reject this non-file target and
                                # let the compatibility launcher try aliases.
                                found[key] = AppMatch(
                                    key, name, name, "registry")
            except OSError:
                continue
    except ImportError:
        pass
    return found


def _scan_macos() -> dict[str, AppMatch]:
    found: dict[str, AppMatch] = {}
    for root in (Path("/Applications"), Path.home() / "Applications"):
        try:
            if not root.is_dir():
                continue
            for bundle in root.glob("*.app"):
                key = normalize(bundle.stem)
                if key and key not in found:
                    found[key] = AppMatch(key, bundle.stem, bundle.stem,
                                          "applications")
        except OSError:
            continue
    try:
        out = subprocess.run(
            ["mdfind", "kMDItemContentType == 'com.apple.application-bundle'"],
            capture_output=True, text=True, timeout=8)
        for line in (out.stdout or "").splitlines():
            stem = Path(line.strip()).stem
            key = normalize(stem)
            if key and key not in found:
                found[key] = AppMatch(key, stem, stem, "mdfind")
    except (OSError, subprocess.SubprocessError):
        pass
    return found


_DESKTOP_NAME_RE = re.compile(r"^Name\s*=\s*(.+)$", re.M)
_DESKTOP_EXEC_RE = re.compile(r"^Exec\s*=\s*(.+)$", re.M)


def _scan_linux() -> dict[str, AppMatch]:
    found: dict[str, AppMatch] = {}
    roots = [Path("/usr/share/applications"),
             Path("/var/lib/flatpak/exports/share/applications"),
             Path.home() / ".local/share/applications"]
    for root in roots:
        try:
            if not root.is_dir():
                continue
            for entry in root.glob("*.desktop"):
                try:
                    text = entry.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                nm = _DESKTOP_NAME_RE.search(text)
                ex = _DESKTOP_EXEC_RE.search(text)
                if not nm:
                    continue
                name = nm.group(1).strip()
                target = (ex.group(1).split()[0] if ex else name)
                key = normalize(name)
                if key and key not in found:
                    found[key] = AppMatch(key, name, target, "desktop")
        except OSError:
            continue
    return found


def refresh(force: bool = False) -> int:
    """Bangun ulang indeks tanpa menahan lookup selama pemindaian OS."""

    global _index, _index_built_at, _refreshing
    with _lock:
        fresh = (time.monotonic() - _index_built_at) < _CACHE_TTL_S
        if _index and fresh and not force:
            return len(_index)
        if _refreshing:
            # Boot already scans in a worker. A command arriving meanwhile
            # must not wait several seconds for PowerShell/registry I/O.
            return len(_index)
        _refreshing = True
    try:
        if _SYSTEM == "Windows":
            found = _scan_windows()
        elif _SYSTEM == "Darwin":
            found = _scan_macos()
        else:
            found = _scan_linux()
    except Exception as exc:                                # noqa: BLE001
        _logger.warning("app_registry.scan_failed", error=str(exc)[:120])
        found = {}
    with _lock:
        _index = found
        _index_built_at = time.monotonic()
        _refreshing = False
        _logger.info("app_registry.indexed", count=len(found), system=_SYSTEM)
        return len(found)


def index() -> dict[str, AppMatch]:
    with _lock:
        if not _index:
            refresh()
        return dict(_index)


def refresh_async() -> None:
    """Dipanggil saat boot — pemindaian tidak boleh menahan startup."""
    threading.Thread(target=refresh, kwargs={"force": True}, daemon=True,
                     name="app-registry-scan").start()


# ── pencocokan fuzzy ─────────────────────────────────────────────────────

def _is_subsequence(short: str, long: str) -> bool:
    it = iter(long)
    return all(ch in it for ch in short)


def _score(query: str, key: str) -> float:
    """0.0–1.0. Tiap cabang punya alasan, bukan angka ajaib."""
    if query == key:
        return 1.0
    q_tokens, k_tokens = set(query.split()), set(key.split())
    if q_tokens and q_tokens <= k_tokens:
        return 0.90                      # "visual studio" ⊂ "visual studio code"
    if key.startswith(query):
        return 0.85                      # "insta" → "instagram"
    if query in key:
        return 0.70
    initials = "".join(t[0] for t in key.split() if t)
    if len(query) >= 2 and query == initials:
        return 0.80                      # "vsc" → "visual studio code"
    ratio = SequenceMatcher(None, query, key).ratio()
    if ratio >= 0.82:
        return ratio * 0.80
    # Subsequence hanya dipercaya untuk query pendek; tanpa batas ini
    # hampir semua string cocok dengan semuanya.
    if 2 <= len(query) <= 4 and _is_subsequence(query, key):
        return 0.62
    return 0.0


def resolve(name: str) -> AppMatch | None:
    """Aplikasi terpasang yang paling cocok, atau ``None``.

    Alias yang dipelajari diterapkan LEBIH DULU, sehingga koreksi user selalu
    mengalahkan tebakan heuristik.
    """
    query = normalize(name)
    if not query:
        return None

    apps = index()
    aliases = dict(_SEED_ALIASES)
    aliases.update(_load_store()["aliases"])
    if query in aliases:
        query = normalize(aliases[query]) or query

    if query in apps:
        return apps[query]

    best: AppMatch | None = None
    for key, match in apps.items():
        score = _score(query, key)
        if score >= _MIN_SCORE and (best is None or score > best.score):
            best = AppMatch(match.key, match.name, match.target,
                            match.source, score)
    if best is not None:
        return best

    with _lock:
        scan_in_progress = _refreshing
    if scan_in_progress:
        # Keep the command path instant while the richer OS index is warming.
        # The caller still has its explicit compatibility/web fallback.
        return None

    # Jalur terakhir: benar-benar ada di PATH (bukan tebakan Start Menu).
    exe = shutil.which(query) or shutil.which(query.replace(" ", ""))
    if exe:
        return AppMatch(query, query, exe, "path", 0.75)
    return None


def is_installed(name: str) -> bool:
    return resolve(name) is not None


def launch_match(match: AppMatch) -> bool:
    """Launch one *resolved* application without shell command strings.

    ``False`` means the match proves installation but does not expose a usable
    launch target (some Uninstall registry entries only contain a display
    name). Callers may then use a known compatibility fallback.
    """

    if not isinstance(match, AppMatch) or not str(match.target or "").strip():
        return False
    target = str(match.target).strip()
    try:
        if _SYSTEM == "Windows":
            if match.source == "registry" and not Path(target).is_file():
                return False
            startfile = getattr(os, "startfile", None)
            if match.source == "start_apps":
                if startfile is not None:
                    try:
                        startfile(target)
                    except OSError:
                        subprocess.Popen(
                            ["explorer.exe", target],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                else:
                    subprocess.Popen(
                        ["explorer.exe", target],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            elif startfile is not None and match.source in {
                "start_menu", "registry", "path"
            }:
                startfile(target)
            else:
                subprocess.Popen(
                    [target],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        elif _SYSTEM == "Darwin":
            subprocess.Popen(
                ["open", "-a", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            executable = shutil.which(target) or target
            subprocess.Popen(
                [executable],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        _logger.info(
            "app_registry.launched",
            app=match.name,
            source=match.source,
        )
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        _logger.warning(
            "app_registry.launch_failed",
            app=match.name,
            source=match.source,
            error=str(exc)[:120],
        )
        return False


# ── proses berjalan ──────────────────────────────────────────────────────

def list_running() -> list[RunningApp]:
    """Aplikasi yang punya jendela terlihat. Kosong bila dependensinya absen."""
    out: list[RunningApp] = []
    try:
        import psutil
    except ImportError:
        return out

    titles: dict[int, str] = {}
    try:
        import pygetwindow as gw

        for win in gw.getAllWindows():
            title = (getattr(win, "title", "") or "").strip()
            if not title:
                continue
            try:
                import win32process
                _tid, pid = win32process.GetWindowThreadProcessId(win._hWnd)
                if pid:
                    titles.setdefault(int(pid), title)
            except Exception as exc:                          # noqa: BLE001
                quiet.swallowed("core.app_registry.window_pid_failed", exc)
                continue
    except Exception:                                        # noqa: BLE001
        titles = {}

    try:
        for proc in psutil.process_iter(["pid", "name"]):
            info = proc.info
            pid = int(info.get("pid") or 0)
            nm = str(info.get("name") or "").strip()
            if not nm:
                continue
            if titles and pid not in titles:
                continue                     # tanpa jendela → bukan "aplikasi"
            out.append(RunningApp(nm, pid, titles.get(pid, "")))
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("app_registry.process_scan_failed",
                        error=str(exc)[:120])
    return out


def is_running(name: str) -> bool:
    query = normalize(name)
    if not query:
        return False
    match = resolve(name)
    targets = {query}
    if match is not None:
        targets.add(match.key)
        targets.add(normalize(Path(match.target).stem))
    for app in list_running():
        candidate = normalize(Path(app.name).stem)
        if candidate in targets or any(_score(t, candidate) >= 0.85
                                       for t in targets):
            return True
    return False


__all__ = [
    "AppMatch", "RunningApp", "normalize", "refresh", "refresh_async",
    "index", "resolve", "launch_match", "is_installed", "is_running",
    "list_running",
    "learn_alias", "preference_for", "remember_preference",
    "forget_preference",
]
