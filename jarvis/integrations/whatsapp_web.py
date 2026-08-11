"""Dedicated, consent-gated WhatsApp Web automation.

This adapter intentionally owns a separate persistent Playwright context.
Long-lived calls must not share the general agent browser page, which may be
navigated by another task.  Personal contacts live in the ignored runtime
``data/`` directory; only an example file is tracked.

WhatsApp Web has no stable public DOM automation contract.  Selectors below
prefer accessibility labels in Indonesian and English, fail closed when the
page shape is unknown, and never guess a contact.
"""
from __future__ import annotations

import atexit
from difflib import SequenceMatcher
import json
import os
import queue
import re
import threading
import time
import unicodedata
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from jarvis.core import config, log

_logger = log.get("whatsapp.web")
_PHONE_RE = re.compile(r"^\d{8,15}$")
_PROFILE_BUSY_MARKERS = (
    "processsingleton",
    "profile is already in use",
    "user data directory is already in use",
    "profile directory is already in use",
    "avoid profile corruption",
)
_MISSING_BROWSER_MARKERS = (
    "executable doesn't exist",
    "executable does not exist",
    "browser executable is not found",
    "distribution 'chrome' is not found",
    "chrome distribution is not found",
    "playwright install",
)


class WhatsAppError(RuntimeError):
    """Safe, user-facing WhatsApp automation failure."""


@dataclass(frozen=True)
class Contact:
    name: str
    phone: str = ""
    allowed: bool = False
    aliases: tuple[str, ...] = ()

    def safe_dict(self) -> dict[str, object]:
        suffix = self.phone[-4:] if self.phone else ""
        return {
            "name": self.name,
            "phone_hint": f"••••{suffix}" if suffix else "",
            "allowed": self.allowed,
            "aliases": list(self.aliases),
        }


def _normalize(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", str(value or "")).casefold().split()
    )


def _digits(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _profile_dir() -> str:
    configured = str(
        config.get("whatsapp_web.user_data_dir", "") or ""
    ).strip()
    if configured:
        return os.path.expandvars(os.path.expanduser(configured))
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "JARVIS", "WhatsAppWebProfile")


def _contacts_path() -> Path:
    configured = str(
        config.get(
            "whatsapp_web.contacts_file",
            "data/whatsapp_contacts.json",
        )
        or "data/whatsapp_contacts.json"
    )
    return config.resolve_path(configured)


def load_contacts() -> list[Contact]:
    """Load allowlisted contacts without leaking their numbers to logs."""

    try:
        raw = json.loads(_contacts_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _logger.warning(
            "whatsapp.contacts_invalid", error_type=type(exc).__name__
        )
        return []
    values = raw.get("contacts", []) if isinstance(raw, dict) else raw
    if not isinstance(values, list):
        return []
    out: list[Contact] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split())
        phone = _digits(item.get("phone", ""))
        raw_aliases = item.get("aliases", [])
        if isinstance(raw_aliases, str):
            raw_aliases = [raw_aliases]
        aliases = tuple(dict.fromkeys(
            " ".join(str(alias or "").split())
            for alias in (raw_aliases if isinstance(raw_aliases, list) else [])
            if _normalize(alias) and _normalize(alias) != _normalize(name)
        ))[:12]
        key = _normalize(name)
        if not name or not key or key in seen:
            continue
        if phone and not _PHONE_RE.fullmatch(phone):
            continue
        seen.add(key)
        out.append(
            Contact(
                name=name,
                phone=phone,
                allowed=item.get("allowed") is True,
                aliases=aliases,
            )
        )
    return out


def resolve_contact(value: str) -> Contact:
    """Resolve one allowlisted contact, tolerating bounded STT name errors.

    Exact name/alias/phone matches always win. Fuzzy matching is restricted to
    already-allowed contacts, requires a unique winner above the configured
    threshold, and is never used for a numeric request.
    """

    requested = " ".join(str(value or "").split())
    normalized = _normalize(requested)
    phone = _digits(requested)
    contacts = load_contacts()
    matches = [
        item
        for item in contacts
        if normalized in {
            _normalize(item.name),
            *(_normalize(alias) for alias in item.aliases),
        }
        or (phone and item.phone == phone)
    ]
    if len(matches) == 1 and matches[0].allowed:
        return matches[0]
    if len(matches) == 1:
        raise WhatsAppError(
            f"Kontak {matches[0].name} belum diizinkan untuk otomasi."
        )
    if len(matches) > 1:
        raise WhatsAppError(
            "Nama kontak ambigu. Gunakan nama unik dalam contacts_file."
        )
    if (
        phone
        and _PHONE_RE.fullmatch(phone)
        and bool(config.get("whatsapp_web.allow_direct_numbers", False))
    ):
        return Contact(name=requested, phone=phone, allowed=True)
    if normalized and not phone and len(normalized) >= 4:
        try:
            threshold = float(
                config.get("whatsapp_web.contact_fuzzy_threshold", 0.68)
            )
        except (TypeError, ValueError):
            threshold = 0.68
        threshold = max(0.60, min(0.95, threshold))
        ranked: list[tuple[float, Contact]] = []
        for item in contacts:
            if not item.allowed:
                continue
            candidates = (item.name, *item.aliases)
            score = max(
                SequenceMatcher(
                    None, normalized, _normalize(candidate)
                ).ratio()
                for candidate in candidates
            )
            ranked.append((score, item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        if ranked and ranked[0][0] >= threshold:
            second = ranked[1][0] if len(ranked) > 1 else 0.0
            if ranked[0][0] - second >= 0.08:
                _logger.info(
                    "whatsapp.contact_fuzzy_resolved",
                    contact=ranked[0][1].name,
                    score=round(ranked[0][0], 2),
                )
                return ranked[0][1]
    raise WhatsAppError(
        "Kontak tidak ditemukan dalam allowlist WhatsApp Jarvis."
    )


def available() -> bool:
    if not bool(config.get("whatsapp_web.enabled", False)):
        return False
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:
        return False
    return True


def _launch_error_kind(exc: BaseException) -> str:
    text = str(exc).casefold()
    if any(marker in text for marker in _PROFILE_BUSY_MARKERS):
        return "profile_busy"
    if any(marker in text for marker in _MISSING_BROWSER_MARKERS):
        return "browser_missing"
    return "unknown"


def _first_visible(page, selectors: tuple[str, ...]):
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = min(locator.count(), 8)
            for index in range(count):
                candidate = locator.nth(index)
                if candidate.is_visible():
                    return candidate
        except Exception:
            continue
    return None


def _wait_visible(page, selectors: tuple[str, ...], timeout_ms: int = 8_000):
    deadline = time.monotonic() + max(0.1, timeout_ms / 1000)
    while time.monotonic() < deadline:
        found = _first_visible(page, selectors)
        if found is not None:
            return found
        page.wait_for_timeout(100)
    return None


# Percakapan yang benar-benar terbuka. Tanpa ini, "tidak ada tombol panggilan"
# dan "tidak ada chat sama sekali" terlihat sama — dan yang kedua salah
# dituduhkan ke rollout akun (S-29).
_CONVERSATION_SELECTORS = ("#main",)
_READY_SELECTORS = (
    "#pane-side",
    '[aria-label*="chat list" i]',
    '[aria-label*="daftar chat" i]',
)
_SEARCH_SELECTORS = (
    '[contenteditable="true"][aria-label*="search" i]',
    '[contenteditable="true"][aria-label*="cari" i]',
    '#side [contenteditable="true"][role="textbox"]',
)
_COMPOSER_SELECTORS = (
    'footer [contenteditable="true"][role="textbox"]',
    '[contenteditable="true"][aria-label*="type a message" i]',
    '[contenteditable="true"][aria-label*="ketik pesan" i]',
)
# S-18 — "Telepon" adalah PEMBUKA MENU, bukan tombol yang menelepon.
# Probe DOM sungguhan (2026-08-05) saat tombol itu diklik menampilkan:
#     {"aria_label": "Telepon"}        <- pembuka menu
#     {"aria_label": "Telepon video"}
#     {"aria_label": "Telepon suara"}  <- aksi panggilan suara
# S-16 mencocokkan "Telepon" persis, jadi start_call mengklik pembuka menu
# lalu menunggu bukti panggilan yang tidak akan pernah datang. Terbukti di
# lapangan: HP lawan bicara tidak berdering sama sekali.
# S-28 — SEMUA kontrol panggilan diikat ke percakapan yang terbuka (`#main`).
# Log `whatsapp.voice_option_missing` menunjukkan label yang terlihat saat
# gagal seluruhnya milik rail navigasi kiri: "Chat, Telepon, Status, Saluran,
# Komunitas, Meta AI, ... Daftar chat". Artinya `button[aria-label="Telepon"]`
# yang dicocokkan S-16 adalah TAB TELEPON DI SIDEBAR, bukan tombol panggilan
# di dalam chat — mengkliknya berpindah ke daftar panggilan, tempat "Telepon
# suara" memang tidak pernah ada.
_CALL_MENU_SELECTORS = (
    '#main button[aria-label="Telepon" i]',
    '#main button[aria-label="Call" i]',
)
# Aksi yang BENAR-BENAR menelepon. Tidak pernah memuat "video": salah pilih di
# sini berarti memulai panggilan video tanpa diminta.
_VOICE_CALL_SELECTORS = (
    '#main button[aria-label="Telepon suara" i]',
    '#main button[aria-label="Voice call" i]',
    '#main button[aria-label*="panggilan suara" i]',
    '#main button[title*="panggilan suara" i]',
    '#main button[title*="voice call" i]',
    '#main [data-icon="audio-call"]',
)
# Nama lama dipertahankan sebagai gabungan keduanya untuk pemanggil yang hanya
# ingin tahu "adakah kontrol panggilan di halaman ini" (mis. harness WA0).
_CALL_SELECTORS = _VOICE_CALL_SELECTORS + _CALL_MENU_SELECTORS
_ANSWER_SELECTORS = (
    'button[aria-label*="answer" i]',
    'button[aria-label*="jawab" i]',
    'button[aria-label*="angkat" i]',
    '[data-icon="call-accept"]',
)
_HANGUP_SELECTORS = (
    # S-19 — label DOM sungguhan saat panggilan Takeda BERDERING (probe
    # linimasa 2026-08-05, detik ke-16, pages=1 — overlay ada di halaman yang
    # sama, bukan jendela terpisah):
    #     "Akhiri telepon", "Kontrol telepon", "Pindahkan ke jendela baru"
    # WhatsApp Indonesia konsisten memakai "telepon", BUKAN "panggilan".
    # Selector lama mencari "akhiri panggilan" dan tidak pernah cocok, sehingga
    # panggilan yang benar-benar berdering dilaporkan tidak terbukti, status
    # tak pernah `in_call`, dan whatsapp_hangup tak pernah menemukan tombolnya.
    'button[aria-label="Akhiri telepon" i]',
    'button[aria-label*="akhiri telepon" i]',
    'button[aria-label*="end call" i]',
    'button[aria-label*="akhiri panggilan" i]',
    'button[aria-label*="hang up" i]',
    '[data-icon="call-end"]',
)
# Panggilan keluar yang masih berdering sudah menampilkan overlay-nya sendiri
# sebelum tersambung. Salah satu dari dua kelompok ini adalah bukti sah bahwa
# panggilan benar-benar dimulai; klik tombol saja BUKAN bukti (S-1).
_RINGING_SELECTORS = (
    # S-19 — "Kontrol telepon" muncul bersama overlay panggilan dan TIDAK ada
    # di chat diam, jadi ia membedakan. Label menu ("Telepon", "Telepon suara")
    # sengaja tidak dipakai: keduanya selalu ada, dan bukti yang selalu benar
    # bukan bukti — itu kegagalan arah sebaliknya dari S-1.
    '[aria-label="Kontrol telepon" i]',
    '[aria-label*="kontrol telepon" i]',
    '[aria-label*="calling" i]',
    '[aria-label*="memanggil" i]',
    '[aria-label*="ringing" i]',
    '[data-testid*="call" i][role="dialog"]',
)


_CONTROL_PROBE_JS = """
() => {
  const out = [];
  for (const el of document.querySelectorAll('button,[role="button"],[aria-label]')) {
    const label = (el.getAttribute('aria-label') || '').trim();
    if (!label) continue;
    const r = el.getBoundingClientRect();
    out.push(label + (r.width && r.height ? '' : ' (tersembunyi)'));
    if (out.length >= 20) break;
  }
  return out;
}
"""


def _visible_call_controls(page) -> str:
    """Label kontrol yang terlihat — untuk log kegagalan, bukan keputusan."""
    try:
        return ", ".join(str(x) for x in (page.evaluate(_CONTROL_PROBE_JS) or []))
    except Exception:                                        # noqa: BLE001
        return "(tidak terbaca)"


class WhatsAppWebService:
    """Single-thread owner for one persistent WhatsApp Web context."""

    _instance: "WhatsAppWebService | None" = None
    _instance_lock = threading.Lock()

    @classmethod
    def get(cls) -> "WhatsAppWebService":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def _reset_for_tests(cls) -> None:
        with cls._instance_lock:
            current = cls._instance
            cls._instance = None
        if current is not None:
            current.stop()

    def __init__(self):
        self._jobs: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._started = threading.Event()
        self._generation = 0
        self._stop_enqueued = False
        self._state = "stopped"
        self._failure = ""
        self._last_status: dict = {"state": "stopped"}

    def _launch(self, playwright):
        profile = _profile_dir()
        os.makedirs(profile, exist_ok=True)
        channel = str(
            config.get("whatsapp_web.channel", "chrome") or "chrome"
        ).strip()
        headless = bool(config.get("whatsapp_web.headless", False))
        kwargs = {
            "user_data_dir": profile,
            "headless": headless,
            "no_viewport": True,
            "permissions": ["microphone", "notifications"],
            "args": [
                "--no-first-run",
                "--no-default-browser-check",
                "--autoplay-policy=no-user-gesture-required",
            ],
        }
        try:
            return playwright.chromium.launch_persistent_context(
                channel=channel or None, **kwargs
            )
        except Exception as first:
            kind = _launch_error_kind(first)
            _logger.warning(
                "whatsapp.launch_failed",
                kind=kind,
                error_type=type(first).__name__,
            )
            if kind == "profile_busy":
                raise WhatsAppError(
                    "Profil Chrome WhatsApp Jarvis sedang dipakai proses lain. "
                    "Tutup pemilik profil itu, lalu coba lagi."
                ) from first
            if kind != "browser_missing" or not channel:
                raise WhatsAppError(
                    "Chrome WhatsApp Jarvis gagal dibuka. Periksa instalasi "
                    "browser dan izin profil."
                ) from first
            _logger.info(
                "whatsapp.launch_fallback",
                reason="browser_missing",
                fallback="bundled-chromium",
            )
            try:
                return playwright.chromium.launch_persistent_context(**kwargs)
            except Exception as fallback:
                fallback_kind = _launch_error_kind(fallback)
                if fallback_kind == "profile_busy":
                    raise WhatsAppError(
                        "Profil Chrome WhatsApp Jarvis sedang dipakai proses lain. "
                        "Tutup pemilik profil itu, lalu coba lagi."
                    ) from fallback
                raise WhatsAppError(
                    "Chrome WhatsApp Jarvis gagal dibuka. Periksa instalasi "
                    "browser dan izin profil."
                ) from fallback

    def _main(self, generation: int) -> None:
        context = None
        owner = threading.current_thread()
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                context = self._launch(playwright)
                url = str(
                    config.get(
                        "whatsapp_web.url", "https://web.whatsapp.com"
                    )
                    or "https://web.whatsapp.com"
                )
                try:
                    context.grant_permissions(
                        ["microphone", "notifications"],
                        origin="https://web.whatsapp.com",
                    )
                except Exception:
                    pass
                page = next(
                    (
                        item
                        for item in context.pages
                        if "web.whatsapp.com" in str(item.url)
                    ),
                    None,
                )
                page = page or (
                    context.pages[0] if context.pages else context.new_page()
                )
                nav_ms = int(
                    float(
                        config.get(
                            "whatsapp_web.navigation_timeout_s", 45
                        )
                    )
                    * 1000
                )
                action_ms = int(
                    float(
                        config.get("whatsapp_web.action_timeout_s", 20)
                    )
                    * 1000
                )
                page.set_default_navigation_timeout(max(5_000, nav_ms))
                page.set_default_timeout(max(2_000, action_ms))
                if "web.whatsapp.com" not in str(page.url):
                    page.goto(url, wait_until="domcontentloaded")
                with self._lifecycle_lock:
                    if (
                        self._thread is not owner
                        or self._generation != generation
                        or self._state == "closing"
                    ):
                        return
                    self._state = "accepting"
                self._started.set()
                while True:
                    job = self._jobs.get()
                    if job is None:
                        break
                    function, future = job
                    with self._lifecycle_lock:
                        accepting = (
                            self._thread is owner
                            and self._generation == generation
                            and self._state == "accepting"
                        )
                    if not accepting:
                        if not future.done():
                            future.set_exception(
                                WhatsAppError("WhatsApp Web sedang ditutup.")
                            )
                        continue
                    try:
                        future.set_result(function(page))
                    except Exception as exc:  # noqa: BLE001
                        future.set_exception(exc)
        except Exception as exc:  # noqa: BLE001
            with self._lifecycle_lock:
                startup_failed = (
                    self._thread is owner
                    and self._generation == generation
                    and self._state == "starting"
                )
                if startup_failed:
                    self._failure = (
                        str(exc)[:180]
                        if isinstance(exc, WhatsAppError)
                        else "WhatsApp Web gagal dimulai. Periksa browser dan coba lagi."
                    )
            _logger.error(
                "whatsapp.start_failed" if startup_failed
                else "whatsapp.worker_failed",
                error_type=type(exc).__name__,
            )
            self._started.set()
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            self._started.set()
            with self._lifecycle_lock:
                if (
                    self._thread is owner
                    and self._generation == generation
                ):
                    self._fail_queued_locked()
                    self._state = "stopped"
                    self._thread = None
                    self._stop_enqueued = False
                    self._last_status = {"state": "stopped"}

    def _recover_dead_closing_locked(self) -> None:
        thread = self._thread
        if self._state != "closing" or (
            thread is not None and thread.is_alive()
        ):
            return
        self._fail_queued_locked()
        self._jobs = queue.Queue()
        self._thread = None
        self._state = "stopped"
        self._stop_enqueued = False
        self._failure = ""
        self._last_status = {"state": "stopped"}

    def _ensure(self) -> None:
        if not available():
            raise WhatsAppError(
                "WhatsApp Web belum diaktifkan atau Playwright tidak tersedia."
            )
        with self._lifecycle_lock:
            self._recover_dead_closing_locked()
            thread = self._thread
            owner_alive = bool(thread is not None and thread.is_alive())
            if self._state == "closing":
                raise WhatsAppError("WhatsApp Web sedang ditutup.")
            if owner_alive and self._state not in {"starting", "accepting"}:
                raise WhatsAppError("WhatsApp Web sedang ditutup.")
            if (
                self._state == "accepting"
                and thread is not None
                and thread.is_alive()
            ):
                return
            if self._state != "starting":
                self._state = "starting"
                self._failure = ""
                self._started.clear()
                self._stop_enqueued = False
                self._generation += 1
                generation = self._generation
                self._thread = threading.Thread(
                    target=self._main,
                    args=(generation,),
                    daemon=True,
                    name="jarvis-whatsapp-web",
                )
                self._thread.start()
            generation = self._generation
        if not self._started.wait(timeout=65):
            raise WhatsAppError("WhatsApp Web tidak siap dalam 65 detik.")
        with self._lifecycle_lock:
            if generation != self._generation:
                raise WhatsAppError("WhatsApp Web sedang ditutup.")
            failure = self._failure
            accepting = bool(
                self._state == "accepting"
                and self._thread is not None
                and self._thread.is_alive()
            )
        if failure:
            raise WhatsAppError(failure)
        if not accepting:
            raise WhatsAppError("WhatsApp Web gagal dimulai.")

    def _call(self, function, timeout: float = 60):
        self._ensure()
        future: Future = Future()
        with self._lifecycle_lock:
            if (
                self._state != "accepting"
                or self._thread is None
                or not self._thread.is_alive()
            ):
                raise WhatsAppError("WhatsApp Web sedang ditutup.")
            self._jobs.put((function, future))
        try:
            return future.result(timeout=max(1.0, float(timeout)))
        except TimeoutError as exc:
            raise WhatsAppError("Operasi WhatsApp Web timeout.") from exc

    @staticmethod
    def _status_on_page(page) -> dict:
        if _first_visible(page, _HANGUP_SELECTORS):
            return {"state": "in_call", "url": str(page.url)}
        if _first_visible(page, _ANSWER_SELECTORS):
            return {"state": "incoming_call", "url": str(page.url)}
        if _first_visible(page, _READY_SELECTORS):
            return {"state": "ready", "url": str(page.url)}
        qr = _first_visible(
            page,
            (
                'canvas[aria-label*="scan" i]',
                '[data-ref] canvas',
                "canvas",
            ),
        )
        if qr:
            return {"state": "login_required", "url": str(page.url)}
        return {"state": "loading", "url": str(page.url)}

    def open(self) -> dict:
        def operation(page):
            url = str(
                config.get(
                    "whatsapp_web.url", "https://web.whatsapp.com"
                )
                or "https://web.whatsapp.com"
            )
            if "web.whatsapp.com" not in str(page.url):
                page.goto(url, wait_until="domcontentloaded")
            status = self._status_on_page(page)
            self._last_status = status
            return status

        return dict(self._call(operation))

    def status(self) -> dict:
        with self._lifecycle_lock:
            running = bool(
                self._thread
                and self._thread.is_alive()
                and self._state == "accepting"
            )
        if not running:
            return dict(self._last_status)

        def operation(page):
            status = self._status_on_page(page)
            self._last_status = status
            return status

        return dict(self._call(operation, timeout=10))

    @staticmethod
    def _await_ready(page, timeout_s: float | None = None) -> None:
        """Tunggu halaman siap, jangan menyerah pada detik pertama (S-26).

        Log sesi 2026-08-05 21:29: *"WhatsApp Web belum siap (status:
        loading)."* Bentuk lama membaca status SEKALI lalu gagal. WhatsApp Web
        butuh beberapa detik untuk siap, sehingga perintah pertama setelah
        Jarvis menyala hampir selalu jatuh di sini.

        ``login_required`` TIDAK ditunggu: memindai QR butuh tindakan user, dan
        menunggu hanya menunda pesan yang seharusnya ia terima sekarang.
        """
        if timeout_s is None:
            try:
                timeout_s = float(
                    config.get("whatsapp_web.ready_timeout_s", 20))
            except (TypeError, ValueError):
                timeout_s = 20.0
        deadline = time.monotonic() + max(0.1, float(timeout_s))
        state = "unknown"
        while time.monotonic() < deadline:
            state = WhatsAppWebService._status_on_page(page)["state"]
            if state == "login_required":
                raise WhatsAppError(
                    "WhatsApp Web belum login. Pindai QR pada jendela Chrome "
                    "Jarvis."
                )
            if state in {"ready", "in_call"}:
                return
            page.wait_for_timeout(500)
        raise WhatsAppError(
            f"WhatsApp Web belum siap setelah {timeout_s:.0f} detik "
            f"(status: {state})."
        )

    @staticmethod
    def _require_ready(page) -> None:
        WhatsAppWebService._await_ready(page)

    @staticmethod
    def _open_chat(page, contact: Contact) -> None:
        WhatsAppWebService._require_ready(page)
        if contact.phone:
            target = quote(contact.phone, safe="")
            page.goto(
                f"https://web.whatsapp.com/send?phone={target}",
                wait_until="domcontentloaded",
            )
            page.wait_for_timeout(1200)
        else:
            search = _first_visible(page, _SEARCH_SELECTORS)
            if search is None:
                raise WhatsAppError(
                    "Kotak pencarian WhatsApp tidak ditemukan."
                )
            search.click()
            search.fill(contact.name)
            page.wait_for_timeout(500)
            try:
                match = page.get_by_title(contact.name, exact=True).first
                match.wait_for(state="visible", timeout=5_000)
                match.click()
            except Exception as exc:
                raise WhatsAppError(
                    f"Kontak {contact.name} tidak muncul atau tidak dapat dibuka."
                ) from exc
        error = _first_visible(
            page,
            (
                'text=/phone number shared via url is invalid/i',
                'text=/nomor telepon.*tidak valid/i',
            ),
        )
        if error:
            raise WhatsAppError("Nomor WhatsApp kontak tidak valid.")

    def send_message(self, contact_value: str, message: str) -> dict:
        contact = resolve_contact(contact_value)
        body = str(message or "").strip()
        if not body:
            raise WhatsAppError("Pesan WhatsApp kosong.")

        def operation(page):
            self._open_chat(page, contact)
            composer = _wait_visible(page, _COMPOSER_SELECTORS)
            if composer is None:
                raise WhatsAppError(
                    "Kotak penulisan pesan WhatsApp tidak ditemukan."
                )
            composer.click()
            composer.fill(body)
            composer.press("Enter")
            return {"state": "sent", "contact": contact.name}

        return dict(self._call(operation))

    @staticmethod
    def _prove_call_started(page) -> str:
        """``'in_call'`` / ``'ringing'`` bila terbukti, ``''`` bila tidak.

        Klik tombol bukan bukti. Satu-satunya bukti yang diterima adalah
        keadaan panggilan yang benar-benar terlihat pada halaman.
        """
        try:
            timeout_s = float(
                config.get("whatsapp_web.call_confirm_timeout_s", 8)
            )
        except (TypeError, ValueError):
            timeout_s = 8.0
        timeout_ms = int(max(0.2, min(60.0, timeout_s)) * 1000)
        if _wait_visible(page, _HANGUP_SELECTORS, timeout_ms=timeout_ms):
            return "in_call"
        if _first_visible(page, _RINGING_SELECTORS):
            return "ringing"
        return ""

    def start_call(self, contact_value: str) -> dict:
        contact = resolve_contact(contact_value)

        def operation(page):
            self._open_chat(page, contact)
            # Aksi panggilan suara kadang langsung terlihat; kadang tersembunyi
            # di balik menu "Telepon". Coba yang langsung dulu supaya tidak
            # membuka menu tanpa perlu (S-18).
            # S-29 — pastikan percakapannya BENAR-BENAR terbuka sebelum
            # menyimpulkan apa pun tentang kontrol panggilan. Log 22:28
            # menyalahkan rollout akun, padahal label yang terlihat saat itu
            # seluruhnya keadaan kosong ("Obrolan baru", "Daftar chat"):
            # chatnya tidak pernah terbuka.
            if _wait_visible(page, _CONVERSATION_SELECTORS,
                             timeout_ms=8_000) is None:
                _logger.warning("whatsapp.chat_not_open",
                                contact=contact.name,
                                visible=_visible_call_controls(page)[:400])
                raise WhatsAppError(
                    f"Percakapan dengan {contact.name} tidak terbuka di "
                    "WhatsApp Web, jadi tidak ada tombol panggilan yang bisa "
                    "ditekan. Nomornya mungkin tidak terdaftar di WhatsApp, "
                    "atau halaman gagal membuka chat itu."
                )
            button = _wait_visible(page, _VOICE_CALL_SELECTORS, timeout_ms=2_000)
            if button is None:
                opener = _wait_visible(page, _CALL_MENU_SELECTORS)
                if opener is None:
                    _logger.warning("whatsapp.call_controls_missing",
                                    visible=_visible_call_controls(page)[:400])
                    raise WhatsAppError(
                        "Kontrol panggilan tidak ditemukan di dalam percakapan. "
                        "Fitur calling mungkin belum tersedia pada akun/rollout "
                        "WhatsApp Web ini."
                    )
                opener.click()
                page.wait_for_timeout(600)
                button = _wait_visible(page, _VOICE_CALL_SELECTORS,
                                       timeout_ms=5_000)
            if button is None:
                # Menu terbuka tetapi pilihan suara tidak ada. Berhenti di sini:
                # menebak elemen lain berisiko memulai panggilan VIDEO.
                #
                # S-26 — dan REKAM apa yang benar-benar terlihat. Probe sudah
                # membuktikan label "Telepon suara" ada di DOM sungguhan, jadi
                # kegagalan ini menyisakan pertanyaan yang hanya bisa dijawab
                # oleh keadaan halaman saat itu. Menebak sebabnya sudah dua kali
                # meleset di siklus ini.
                _logger.warning("whatsapp.voice_option_missing",
                                visible=_visible_call_controls(page)[:400])
                raise WhatsAppError(
                    "Menu panggilan terbuka tetapi pilihan panggilan suara "
                    "tidak ditemukan. Tidak ada panggilan yang dimulai."
                )
            button.click()
            state = self._prove_call_started(page)
            if not state:
                # Sengaja melempar, bukan mengembalikan status lunak: pemanggil
                # di atas kita mengubah hasil sukses apa pun menjadi kalimat
                # "sudah saya telepon" (S-1).
                #
                # Yang TIDAK boleh ditulis di sini: "tidak ada panggilan yang
                # sedang berjalan". Bukti gagal bisa berarti selector tidak
                # cocok dengan DOM WhatsApp, bukan panggilan tidak dimulai —
                # dan memutusnya otomatis mustahil, karena tombol akhiri
                # panggilan dicari dengan selector yang baru saja terbukti
                # tidak cocok. Menukar klaim palsu dengan klaim palsu arah
                # sebaliknya bukan perbaikan.
                raise WhatsAppError(
                    f"Panggilan ke {contact.name} tidak terbukti dimulai — "
                    "tombol diklik tetapi jendela panggilan tidak terdeteksi. "
                    "Keadaan panggilan TIDAK DIKETAHUI: periksa jendela "
                    "WhatsApp Jarvis, dan akhiri sendiri bila ternyata "
                    "sedang menelepon."
                )
            return {"state": state, "contact": contact.name, "proven": True}

        result = dict(self._call(operation))
        self._last_status = dict(result)
        return result

    def answer_call(self) -> dict:
        def operation(page):
            button = _wait_visible(page, _ANSWER_SELECTORS, timeout_ms=5_000)
            if button is None:
                raise WhatsAppError(
                    "Tidak ada panggilan WhatsApp masuk yang dapat dijawab."
                )
            button.click()
            if self._prove_call_started(page) != "in_call":
                raise WhatsAppError(
                    "Tombol jawab diklik tetapi panggilan aktif tidak "
                    "terdeteksi. Keadaan panggilan TIDAK DIKETAHUI: periksa "
                    "jendela WhatsApp Jarvis."
                )
            return {"state": "in_call", "proven": True}

        result = dict(self._call(operation))
        self._last_status = dict(result)
        return result

    def hangup(self) -> dict:
        def operation(page):
            button = _first_visible(page, _HANGUP_SELECTORS)
            if button is None:
                return {"state": "ready", "changed": False}
            button.click()
            return {"state": "ready", "changed": True}

        result = dict(self._call(operation))
        self._last_status = dict(result)
        return result

    def _fail_queued_locked(self) -> None:
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                return
            if job is None:
                continue
            _function, future = job
            if not future.done():
                future.set_exception(
                    WhatsAppError("WhatsApp Web sedang ditutup.")
                )

    def stop(self, timeout: float = 8) -> bool:
        with self._lifecycle_lock:
            thread = self._thread
            if not thread or not thread.is_alive():
                self._fail_queued_locked()
                self._thread = None
                self._state = "stopped"
                self._stop_enqueued = False
                self._last_status = {"state": "stopped"}
                return True
            self._state = "closing"
            self._last_status = {"state": "closing"}
            if not self._stop_enqueued:
                self._fail_queued_locked()
                self._jobs.put(None)
                self._stop_enqueued = True
        thread.join(max(0.0, float(timeout)))
        if thread.is_alive():
            _logger.warning("whatsapp.stop_timeout")
            return False
        with self._lifecycle_lock:
            if self._thread is thread:
                self._thread = None
                self._state = "stopped"
                self._stop_enqueued = False
                self._last_status = {"state": "stopped"}
        return True



def shutdown_existing() -> None:
    """Stop an existing owner without creating a browser/service instance."""
    with WhatsAppWebService._instance_lock:
        current = WhatsAppWebService._instance
    if current is not None:
        current.stop()


atexit.register(shutdown_existing)


__all__ = [
    "Contact",
    "WhatsAppError",
    "WhatsAppWebService",
    "available",
    "load_contacts",
    "resolve_contact",
    "shutdown_existing",
]
