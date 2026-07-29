"""Konfirmasi tugas yang menyebut TUGASNYA (DIAGNOSIS_2 MASALAH 4b).

Sekarang ACK diambil acak dari tiga kalimat tetap
(``interaction.render_ack`` → ``random.choice``, ``interaction.py:233``).
Setelah lima kali terdengar seperti mesin penjawab telepon:

    "Baik, sedang saya kerjakan."   ×5

Modul ini meminta model menyusun satu kalimat yang menyinggung isi tugasnya:

    "Oke, saya cari perbandingan lima laptop itu — sebentar ya."
    "Sedang saya rapikan folder Unduhan. Lumayan banyak isinya."

Kontraknya sama ketatnya dengan ``response_composer``: **deadline lokal, dan
template lama sebagai fallback**. ACK yang terlambat lebih buruk daripada ACK
yang membosankan — user sedang menunggu tanda bahwa perintahnya diterima.
"""
from __future__ import annotations

import re
import threading
from collections.abc import Callable

from jarvis.agent import auxiliary
from jarvis.agent.interaction import (ACK_LIMIT, detect_language,
                                      persona_address, render_ack,
                                      sanitize_for_speech)
from jarvis.core import config, log

_logger = log.get("agent.ack_composer")
_IN_FLIGHT = threading.BoundedSemaphore(value=1)

_SYSTEM_PROMPT_ID = """[KONFIRMASI PERINTAH]
Kamu menyusun SATU kalimat konfirmasi lisan untuk JARVIS. Tugas baru saja
mulai dikerjakan di latar belakang.

Aturan:
- Sebut apa yang dikerjakan secara spesifik; jangan cuma "baik sedang saya kerjakan".
- Perintah cepat (buka app, putar musik): singkat dan langsung.
- cari/riset: sebut topiknya.
- tugas panjang: sebut tugas + isyarat ringan seperti "sebentar ya, nanti saya kabari".
- Ambigu: jangan konfirmasi; minta klarifikasi singkat.
- Variasikan pembuka. Jangan buka tiga perintah berturut-turut dengan kata sama.
- Cocokkan energi user: santai tetap santai; "cepat"/"sekarang" langsung tanpa basa-basi.
- Jangan mengulang perintah user kata per kata.
- Satu kalimat, maksimal 14 kata, natural seperti orang bicara.
- Jangan berjanji hasil atau mengaku tugas sudah selesai.
- Tanpa markdown, tanpa tanda kutip, tanpa emoji.
Balas hanya kalimatnya."""

_SYSTEM_PROMPT_EN = """[COMMAND CONFIRMATION]
Write ONE spoken confirmation for JARVIS. The task just started in background.

Rules:
- Name the specific work; never say only "I am on it".
- Fast commands: direct and short. Search/research: name the topic.
- Long tasks: name work + light expectation such as "I will report back shortly".
- Ambiguous request: ask a short clarification instead.
- Vary openings; match urgency; do not echo the command verbatim.
- One sentence, max 14 words. Do not claim completion or promise results.
- No markdown, quotes, or emoji. Reply only with the sentence."""

# ACK yang mengandung ini berarti model mengarang hasil, bukan konfirmasi.
_FORBIDDEN_RE = re.compile(
    r"\b(?:selesai|sudah\s+saya|berhasil|hasilnya|ditemukan|done|finished|"
    r"completed|here\s+are|i\s+found)\b", re.IGNORECASE)


def enabled() -> bool:
    """Ikut saklar composer yang sama — satu tombol untuk 'naturalisasi'."""
    return bool(config.get("auxiliary.response_composer.enabled", False))


def _timeout() -> float:
    """Anggaran SANGAT ketat — ACK ada di jalur kritis latensi.

    ``dispatch_async`` menjanjikan ACK instan; user baru selesai bicara dan
    sedang menunggu tanda perintahnya diterima. 250 ms menjaga biaya
    TERUKUR (termasuk overhead thread) tetap di bawah 300 ms. Model yang tidak sanggup menjawab
    secepat itu tidak kehilangan apa pun — template lama dipakai.
    """
    raw = config.get("agent.interaction.ack_timeout_s", 0.25)
    try:
        return max(0.001, min(float(raw), 1.0))
    except (TypeError, ValueError):
        return 0.25


def _run_bounded(fn: Callable[[], str], timeout_s: float) -> str:
    """Jalankan dengan deadline. Hasil telat DIBUANG, bukan ditunggu."""
    box: dict[str, str] = {}

    def _work() -> None:
        try:
            box["value"] = fn()
        except Exception as exc:                             # noqa: BLE001
            _logger.info("ack_composer.failed", error_type=type(exc).__name__)

    worker = threading.Thread(target=_work, daemon=True, name="ack-composer")
    worker.start()
    worker.join(timeout_s)
    return box.get("value", "")


def _chat(client: object, task: str, lang: str, address: str) -> str:
    system = _SYSTEM_PROMPT_EN if lang == "en" else _SYSTEM_PROMPT_ID
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": (
            f"Panggil user: {address}\n"
            f"Tugas yang diterima: {str(task or '')[:400]}"
        )},
    ]
    try:
        response = client.chat(messages, temperature=0.7, max_tokens=60)
    except Exception as exc:                                 # noqa: BLE001
        _logger.info("ack_composer.call_failed", error_type=type(exc).__name__)
        return ""
    if not getattr(response, "ok", False):
        return ""
    return str(getattr(response, "content", "") or "")


def _validated(candidate: str, lang: str) -> str:
    text = sanitize_for_speech(candidate, ACK_LIMIT)
    if not text:
        return ""
    if len(text.split()) > 18:
        return ""                       # bukan konfirmasi, itu paragraf
    if _FORBIDDEN_RE.search(text):
        return ""                       # mengarang hasil — tolak
    if detect_language(text) != lang:
        return ""                       # bahasa melenceng
    return text


def compose_ack(task: str, *, language: str | None = None,
                address: str | None = None,
                client_factory: Callable[[], object] | None = None,
                force: bool | None = None) -> str:
    """Konfirmasi kontekstual, atau template lama bila gagal/timeout.

    TIDAK PERNAH melempar dan tidak pernah mengembalikan string kosong.
    """
    fallback = render_ack(task, language=language, address=address)
    active = enabled() if force is None else bool(force)
    if not active or not str(task or "").strip():
        return fallback

    # Satu ACK dalam penerbangan — dua tugas beruntun tidak boleh saling
    # menunggu provider.
    if not _IN_FLIGHT.acquire(blocking=False):
        return fallback
    try:
        lang = detect_language(task) if language is None else language
        addr = address or persona_address()
        factory = client_factory or (
            lambda: auxiliary.client_for("response_composer"))
        client = factory()
        # Cek ketersediaan lebih dulu: murah, lokal, dan mencegah kita
        # membakar seluruh anggaran hanya untuk menemukan provider mati.
        available = getattr(client, "available", None)
        if callable(available):
            try:
                if not available():
                    return fallback
            except Exception:                                # noqa: BLE001
                return fallback
        candidate = _run_bounded(
            lambda: _chat(client, task, lang, addr), _timeout())
    finally:
        _IN_FLIGHT.release()

    natural = _validated(candidate, lang)
    if not natural:
        return fallback
    return natural


__all__ = ["compose_ack", "enabled"]
