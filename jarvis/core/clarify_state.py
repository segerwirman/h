"""Pertanyaan klarifikasi yang tertunda + pembelajaran preferensi.

DIAGNOSIS_2 MASALAH 2: Jarvis tidak pernah bertanya saat ambigu. Modul ini
menyimpan SATU pertanyaan tertunda dan menafsirkan jawaban berikutnya.

Yang membuatnya terasa cerdas dan bukan cerewet: jawaban user disimpan lewat
``app_registry.remember_preference``, sehingga pertanyaan yang sama **tidak
pernah diajukan dua kali**.

Sengaja hanya satu slot, bukan tumpukan: dua pertanyaan menggantung sekaligus
membuat user tidak tahu sedang menjawab yang mana.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field

from jarvis.core import app_registry, log

_logger = log.get("core.clarify")
_lock = threading.RLock()
_pending: "Pending | None" = None

# Jawaban tertunda kedaluwarsa — user yang sudah pindah topik tidak boleh
# tiba-tiba dianggap menjawab pertanyaan lama.
TTL_S = 180.0

_APP_ANSWER_RE = re.compile(
    r"\b(?:app|apps|aplikasi|aplikasinya|program|software|desktop|"
    r"yang\s+pertama|pertama|satu|1)\b", re.IGNORECASE)
_WEB_ANSWER_RE = re.compile(
    r"\b(?:web|website|situs|browser|online|url|link|laman|"
    r"yang\s+kedua|kedua|dua|2)\b", re.IGNORECASE)
_DECLINE_RE = re.compile(
    r"\b(?:batal|cancel|lupakan|nggak|ga|gak|tidak|nevermind|never\s*mind)\b",
    re.IGNORECASE)


@dataclass
class Pending:
    topic: str
    question: str
    options: list[str] = field(default_factory=list)
    app: str = ""
    url: str = ""
    created_at: float = field(default_factory=time.monotonic)

    @property
    def expired(self) -> bool:
        return (time.monotonic() - self.created_at) > TTL_S


def set_pending(topic: str, question: str, options=None,
                app: str = "", url: str = "") -> Pending:
    global _pending
    with _lock:
        _pending = Pending(topic=str(topic or ""), question=str(question or ""),
                           options=list(options or []), app=str(app or ""),
                           url=str(url or ""))
        return _pending


def pending() -> Pending | None:
    global _pending
    with _lock:
        if _pending is not None and _pending.expired:
            _pending = None
        return _pending


def clear() -> None:
    global _pending
    with _lock:
        _pending = None


def interpret(text: str) -> str | None:
    """``"app"`` | ``"web"`` | ``"declined"`` | ``None`` (bukan jawaban).

    ``None`` penting: kalimat yang jelas-jelas perintah baru tidak boleh
    ditelan sebagai jawaban.
    """
    if pending() is None:
        return None
    raw = str(text or "").strip()
    if not raw or len(raw.split()) > 6:
        return None                       # kalimat panjang = perintah baru
    if _DECLINE_RE.search(raw):
        return "declined"
    app_hit = bool(_APP_ANSWER_RE.search(raw))
    web_hit = bool(_WEB_ANSWER_RE.search(raw))
    if app_hit and not web_hit:
        return "app"
    if web_hit and not app_hit:
        return "web"
    return None


def resolve(text: str) -> tuple[str, Pending] | None:
    """Tafsirkan jawaban, simpan preferensinya, bersihkan state.

    Return ``(kind, pending)`` bila benar-benar terjawab.
    """
    current = pending()
    if current is None:
        return None
    kind = interpret(text)
    if kind is None:
        return None
    clear()
    if kind == "declined":
        return ("declined", current)
    if current.topic:
        # Inilah janji "tidak bertanya dua kali".
        if app_registry.remember_preference(current.topic, kind):
            _logger.info("clarify.preference_saved",
                         topic=current.topic, kind=kind)
    return (kind, current)


__all__ = ["Pending", "TTL_S", "set_pending", "pending", "clear",
           "interpret", "resolve"]
