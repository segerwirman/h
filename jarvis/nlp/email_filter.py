"""EmailFiltering — IMAP connect, classify, summarize the urgent bucket.

Read-only by default (config nlp.email.read_only). Any send/delete requires
explicit confirmation and is refused otherwise; with read_only=true they are
refused outright. No credentials → module reports itself offline (0.0
confidence) and the rest of the system is unaffected.
"""
from __future__ import annotations

import asyncio
import email
import email.header
import imaplib
import re

from jarvis.core import config, llm, log
from jarvis.nlp.base import Context, Response

_logger = log.get("nlp.email")

_URGENT_HINTS = re.compile(
    r"\b(urgent|penting|segera|asap|deadline|invoice|overdue|password|"
    r"security alert|verifikasi|action required|immediately)\b", re.I)
_PROMO_HINTS = re.compile(
    r"\b(sale|diskon|promo|unsubscribe|newsletter|off\b|deal|gratis|"
    r"limited time|voucher)\b", re.I)
_SPAM_HINTS = re.compile(
    r"\b(lottery|winner|prince|bitcoin doubler|hadiah jutaan|klik di ?sini|"
    r"100% free|viagra)\b", re.I)

_DESTRUCTIVE = re.compile(r"\b(hapus|delete|kirim|send|balas|reply)\b", re.I)


def _decode(value: str) -> str:
    parts = email.header.decode_header(value or "")
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(text)
    return " ".join(out)


def classify_headers(subject: str, sender: str) -> str:
    text = f"{subject} {sender}"
    if _SPAM_HINTS.search(text):
        return "spam"
    if _URGENT_HINTS.search(text):
        return "urgent"
    if _PROMO_HINTS.search(text):
        return "promo"
    return "normal"


class EmailFiltering:
    name = "EmailFiltering"

    def __init__(self) -> None:
        e = config.section("nlp.email")
        # Kredensial hanya dari environment; config.yaml ter-track git.
        self._host = config.secret("JARVIS_IMAP_HOST", "nlp.email.imap_host")
        self._user = config.secret("JARVIS_IMAP_USER")
        self._password = config.secret("JARVIS_IMAP_PASSWORD")
        self._read_only = bool(e.get("read_only", True))

    @property
    def configured(self) -> bool:
        return bool(self._host and self._user and self._password)

    def can_handle(self, text: str, ctx: Context) -> float:
        t = text.lower()
        if not any(k in t for k in ("email", "e-mail", "surel", "inbox",
                                    "kotak masuk")):
            return 0.0
        return 0.85 if self.configured else 0.65   # unconfigured → explain

    async def handle(self, text: str, ctx: Context) -> Response:
        if _DESTRUCTIVE.search(text):
            return Response(
                "Akses email saya bersifat hanya-baca. Untuk mengirim atau "
                "menghapus, nonaktifkan read_only di config.yaml dan berikan "
                "konfirmasi eksplisit per tindakan.", source=self.name)
        if not self.configured:
            return Response(
                "Modul email belum dikonfigurasi — isi nlp.email.imap_host, "
                "imap_user dan imap_password di config.yaml.", source=self.name)
        try:
            buckets = await asyncio.to_thread(self._fetch_and_classify, 30)
        except Exception as e:
            _logger.error("email.fetch_failed", error=str(e)[:150])
            return Response(f"Gagal terhubung ke IMAP: {str(e)[:100]}",
                            source=self.name)

        counts = {k: len(v) for k, v in buckets.items()}
        summary = ""
        if buckets["urgent"] and any(k in text.lower()
                                     for k in ("ringkas", "urgent", "penting",
                                               "summarize")):
            listing = "\n".join(f"- {s} (dari {f})"
                                for s, f in buckets["urgent"][:10])
            summary = await asyncio.to_thread(
                llm.generate,
                "Ringkas email-email penting berikut dalam Bahasa Indonesia, "
                f"satu kalimat per email:\n{listing}")
        body = (f"Kotak masuk: {counts['urgent']} penting, "
                f"{counts['normal']} normal, {counts['promo']} promosi, "
                f"{counts['spam']} spam.")
        if summary:
            body += f"\n\nRingkasan email penting:\n{summary}"
        return Response(body, show_on_stage=bool(summary), source=self.name)

    def _fetch_and_classify(self, limit: int) -> dict[str, list]:
        buckets: dict[str, list] = {"urgent": [], "normal": [],
                                    "promo": [], "spam": []}
        conn = imaplib.IMAP4_SSL(self._host)
        try:
            conn.login(self._user, self._password)
            conn.select("INBOX", readonly=True)          # enforced read-only
            _typ, data = conn.search(None, "ALL")
            ids = data[0].split()[-limit:]
            for mid in reversed(ids):
                _typ, msg_data = conn.fetch(
                    mid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])")
                if not msg_data or msg_data[0] is None:
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                subject = _decode(msg.get("Subject", ""))
                sender = _decode(msg.get("From", ""))
                buckets[classify_headers(subject, sender)].append(
                    (subject, sender))
        finally:
            try:
                conn.logout()
            except Exception:
                pass
        return buckets
