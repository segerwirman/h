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
_CALL_SELECTORS = (
    'button[aria-label*="voice call" i]',
    'button[aria-label*="panggilan suara" i]',
    'button[title*="voice call" i]',
    'button[title*="panggilan suara" i]',
    '[data-icon="audio-call"]',
)
_ANSWER_SELECTORS = (
    'button[aria-label*="answer" i]',
    'button[aria-label*="jawab" i]',
    'button[aria-label*="angkat" i]',
    '[data-icon="call-accept"]',
)
_HANGUP_SELECTORS = (
    'button[aria-label*="end call" i]',
    'button[aria-label*="akhiri panggilan" i]',
    'button[aria-label*="hang up" i]',
    '[data-icon="call-end"]',
)


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
            _logger.warning(
                "whatsapp.chrome_unavailable",
                error=str(first)[:160],
                fallback="bundled-chromium",
            )
            return playwright.chromium.launch_persistent_context(**kwargs)

    def _main(self) -> None:
        context = None
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
                    self._state = "accepting"
                self._started.set()
                while True:
                    job = self._jobs.get()
                    if job is None:
                        break
                    function, future = job
                    try:
                        future.set_result(function(page))
                    except Exception as exc:  # noqa: BLE001
                        future.set_exception(exc)
        except Exception as exc:  # noqa: BLE001
            self._failure = f"WhatsApp Web gagal dimulai: {str(exc)[:180]}"
            _logger.error("whatsapp.start_failed", error=self._failure)
            self._started.set()
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            with self._lifecycle_lock:
                self._state = "stopped"
                self._thread = None
            self._last_status = {"state": "stopped"}

    def _ensure(self) -> None:
        if not available():
            raise WhatsAppError(
                "WhatsApp Web belum diaktifkan atau Playwright tidak tersedia."
            )
        with self._lifecycle_lock:
            if (
                self._state == "accepting"
                and self._thread
                and self._thread.is_alive()
            ):
                return
            if self._state != "starting":
                self._state = "starting"
                self._failure = ""
                self._started.clear()
                self._thread = threading.Thread(
                    target=self._main,
                    daemon=True,
                    name="jarvis-whatsapp-web",
                )
                self._thread.start()
        if not self._started.wait(timeout=65):
            raise WhatsAppError("WhatsApp Web tidak siap dalam 65 detik.")
        if self._failure:
            raise WhatsAppError(self._failure)

    def _call(self, function, timeout: float = 60):
        self._ensure()
        future: Future = Future()
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
    def _require_ready(page) -> None:
        state = WhatsAppWebService._status_on_page(page)["state"]
        if state == "login_required":
            raise WhatsAppError(
                "WhatsApp Web belum login. Pindai QR pada jendela Chrome Jarvis."
            )
        if state not in {"ready", "in_call"}:
            raise WhatsAppError(
                f"WhatsApp Web belum siap (status: {state})."
            )

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

    def start_call(self, contact_value: str) -> dict:
        contact = resolve_contact(contact_value)

        def operation(page):
            self._open_chat(page, contact)
            button = _wait_visible(page, _CALL_SELECTORS)
            if button is None:
                raise WhatsAppError(
                    "Tombol panggilan suara tidak ditemukan. Fitur calling "
                    "mungkin belum tersedia pada akun/rollout WhatsApp Web ini."
                )
            button.click()
            page.wait_for_timeout(500)
            return {"state": "calling", "contact": contact.name}

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
            return {"state": "in_call"}

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

    def stop(self) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            if not thread or not thread.is_alive():
                self._state = "stopped"
                return
            self._state = "closing"
            self._jobs.put(None)
        thread.join(timeout=8)


def _shutdown_existing() -> None:
    with WhatsAppWebService._instance_lock:
        current = WhatsAppWebService._instance
    if current is not None:
        current.stop()


atexit.register(_shutdown_existing)


__all__ = [
    "Contact",
    "WhatsAppError",
    "WhatsAppWebService",
    "available",
    "load_contacts",
    "resolve_contact",
]
