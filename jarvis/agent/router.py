"""Automatic light/heavy tier routing for Jarvis MK50.

The router is intentionally independent from the existing intent router in
``jarvis.core.router``.  The latter answers *which* legacy action should run;
this module answers the earlier question of *which execution lane* may handle
the request.  Clear commands stay entirely deterministic.  The optional
network classifier is default-off so conversation routing never waits for a
provider merely to decide which provider should answer.
"""
from __future__ import annotations

import json
import re
import threading
import unicodedata
from dataclasses import dataclass, replace
from enum import IntEnum
from typing import Any

from jarvis.core import config


class Tier(IntEnum):
    """Execution tiers, ordered from the cheapest to the most capable."""

    REFLEX = 0
    SINGLE = 1
    AGENT = 2
    DELEGATE = 3
    AUTONOMOUS = 4


@dataclass(frozen=True)
class Route:
    """A routing decision consumed by the intent-to-action seam."""

    tier: Tier
    lane: str
    model_profile: str
    reason: str
    confidence: float


_RULE_THRESHOLD = 0.7
_MAX_REASON_CHARS = 240
_classifier_lock = threading.Lock()

_CLASSIFIER_SYSTEM = (
    "Klasifikasikan perintah user ke tier. "
    "T0=aksi sistem sepele, T1=satu tool/percakapan/pembacaan data, "
    "T2=butuh banyak langkah/tool/penilaian. "
    'Balas JSON: {"tier": 0|1|2, "reason": "..."} tanpa teks lain.'
)

# Wake/address words and polite fillers are not part of the command itself.
# Stripping them here keeps natural voice phrasing ("Jarvis, coba buka ...")
# on the same deterministic lane as the terse typed form ("buka ...").
_COMMAND_PREFIX_RE = re.compile(
    r"^(?:(?:(?:hey|hai|halo)\s+)?jarvis\s*[,;:—-]?\s*|"
    r"(?:tolong|please|coba)\s+)",
    re.IGNORECASE,
)

_MULTI_STEP_RE = re.compile(
    r"\b(?:buka|open)\s+(?:dan|&)\b"
    r"|\b(?:cari|search|find)\b.+\b(?:lalu|kemudian|then)\b"
    r"|\b(?:setelah\s+itu|after\s+that|and\s+then|lalu|kemudian|terus)\b",
    re.IGNORECASE,
)
_ASSESSMENT_RE = re.compile(
    r"\b(?:terbaru|latest|newest|bandingkan|compare|comparison|ringkas(?:kan)?|"
    r"summari[sz]e|pilih(?:kan)?|choose|select|paling\s+\w+)\b",
    re.IGNORECASE,
)
_NON_FRESHNESS_ASSESSMENT_RE = re.compile(
    r"\b(?:bandingkan|compare|comparison|ringkas(?:kan)?|summari[sz]e|"
    r"pilih(?:kan)?|choose|select|paling\s+(?!baru\b|new\b)\w+)\b",
    re.IGNORECASE,
)
_AGENTIC_RE = re.compile(
    r"\b(?:riset(?:kan)?|research|buatkan|analisis(?:kan)?|analy[sz]e|"
    r"perbaiki|fix|otomatis(?:kan)?|automate|kerjakan|implement(?:asikan)?|"
    r"debug|refactor|audit|review|tinjau|selidiki|investigate|diagnosa|"
    r"diagnose)\b|\b(?:cari|cek|temukan)\s+(?:akar\s+)?"
    r"(?:penyebab(?:nya)?|masalah(?:nya)?)\b",
    re.IGNORECASE,
)
_EXPLICIT_LEGACY_AGENT_RE = re.compile(
    r"^(?:tolong\s+)?(?:suruh|minta|perintahkan|delegasikan\s+ke)\s+"
    r"hermes\b",
    re.IGNORECASE,
)
_COMPUTER_WORK_RE = re.compile(
    r"(?:\b(?:edit|ubah|hapus|delete|rename|pindah(?:kan)?|move|salin|copy|"
    r"jalankan|run|eksekusi|execute|cari|find|search)\b.+"
    r"\b(?:file|berkas|folder|direktori|directory|kode|code|repo(?:sitory)?|"
    r"terminal|powershell|bash|command\s+prompt)\b)"
    r"|(?:\b(?:klik|click|navigasi|navigate|login|unggah|upload|unduh|download|"
    r"isi\s+form(?:ulir)?)\b.+\b(?:browser|web|website|situs|page|halaman)\b)",
    re.IGNORECASE,
)

_READ_ONLY_DATA_RE = re.compile(
    r"\b(?:berita|news|kalender|calendar|agenda|acara|email|surel)\b"
    r"|\b(?:video)\s+(?:terbaru|latest|paling\s+baru)\b.+"
    r"\b(?:langganan(?:ku)?|subscriptions?|channel)\b",
    re.IGNORECASE,
)
_MUTATING_DATA_RE = re.compile(
    r"\b(?:kirim|send|hapus|delete|buat|create|ubah|edit|balas|reply|putar|"
    r"play|tonton|open|buka)\b",
    re.IGNORECASE,
)

_REFLEX_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^(?:tolong\s+)?(?:"
        r"(?:atur|set)\s+(?:volume|brightness|kecerahan)(?:\s+(?:ke|to))?\s*\d{1,3}"
        r"|(?:naikkan|besarkan|turunkan|kecilkan|raise|lower|increase|decrease)"
        r"\s+(?:volume|brightness|kecerahan)"
        r"|(?:volume|brightness|kecerahan)\s+(?:naik|turun|up|down|\d{1,3})"
        r")\s*[.!]?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:tolong\s+)?(?:"
        r"(?:mute|unmute)(?:\s+(?:audio|suara|sound|volume))?"
        r"|(?:matikan|senyapkan|bunyikan)\s+(?:audio|suara|sound|volume)"
        r")\s*[.!]?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:tolong\s+)?(?:"
        r"(?:(?:aktifkan|masuk|jadikan|keluar\s+dari|exit)\s+)?"
        r"(?:mode\s+)?(?:fullscreen|full\s+screen|layar\s+penuh)"
        r"|(?:tekan|press)\s+esc(?:ape)?"
        r")\s*[.!]?$",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:aktifkan|nyalakan|hidupkan|matikan|nonaktifkan|toggle|turn\s+on|"
        r"turn\s+off)\b.+\b(?:mic|mikrofon|microphone|gesture|gestur)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:nyalakan|hidupkan|matikan|toggle|turn\s+on|turn\s+off)\b.+"
        r"\b(?:lampu|light)\b",
        re.IGNORECASE,
    ),
)

_KNOWN_APPS = (
    "spotify",
    "notepad",
    "calculator",
    "kalkulator",
    "vscode",
    "vs code",
    "visual studio code",
    "chrome",
    "edge",
    "firefox",
    "word",
    "excel",
    "powerpoint",
    "discord",
    "telegram",
    "whatsapp",
    "terminal",
    "explorer",
    "paint",
    "browser",
)
_OPEN_APP_RE = re.compile(
    r"^(?:tolong\s+)?(?:buka(?:kan)?|jalankan|launch|open|start|run)\s+"
    r"(?:aplikasi|app)?\s*(?P<app>[\w .-]+?)\s*[.!]?$",
    re.IGNORECASE,
)
_CLOSE_APP_RE = re.compile(
    r"^(?:tolong\s+)?(?:tutup|close|exit|quit)\s+"
    r"(?:aplikasi|app)?\s*(?P<app>[\w .-]+?)\s*[.!]?$",
    re.IGNORECASE,
)
_OPEN_SINGLE_SITE_RE = re.compile(
    r"^(?:tolong\s+)?(?:buka(?:kan)?|open|kunjungi|visit|go\s+to)\s+"
    r"(?:https?://\S+|(?:www\.)?[a-z0-9][a-z0-9.-]*\.[a-z]{2,}(?:/\S*)?|"
    r"youtube|github|google|gmail|instagram|facebook|twitter|x)\s*[.!]?$",
    re.IGNORECASE,
)
_LEGACY_UI_REFLEX_RE = re.compile(
    r"^(?:tolong\s+)?(?:"
    r"kembali|back|go\s+home|home|"
    r"(?:buka(?:kan)?|open|show|launch|start|tampilkan|tutup|close|hide)\s+"
    r"(?:browser\s+agent|agen\s+browser|browser|peramban|"
    r"kamera(?:\s+utama)?|(?:main\s+)?camera)"
    r"(?:\s+(?:di|in)\s+(?:external|eksternal|default|bawaan)\s+browser)?"
    r")\s*[.!]?$",
    re.IGNORECASE,
)
_SINGLE_FRAME_ACTION_RE = re.compile(
    r"^(?:tolong\s+)?(?:klik|click|tekan|press|gulir|scroll|"
    r"ketik|type|isi)\b(?!.*\b(?:lalu|kemudian|terus|then)\b).+$",
    re.IGNORECASE,
)
_GREETING_RE = re.compile(
    r"^(?:halo|hai|hey|hi|selamat\s+(?:pagi|siang|sore|malam)|"
    r"apa\s+kabar|terima\s+kasih|makasih|thanks?|good\s+"
    r"(?:morning|afternoon|evening))\b[\s!,.?]*$",
    re.IGNORECASE,
)
_TIME_WEATHER_RE = re.compile(
    r"\b(?:jam\s+berapa|what\s+time|tanggal\s+berapa|hari\s+apa|"
    r"cuaca|weather|prakiraan)\b",
    re.IGNORECASE,
)
_SINGLE_SONG_RE = re.compile(
    r"^(?:tolong\s+)?(?:putar|puterin|play)\s+(?:lagu|musik|song)\s+.+$",
    re.IGNORECASE,
)
_SINGLE_MESSAGE_RE = re.compile(
    r"^(?:tolong\s+)?(?:kirim(?:kan)?|send)\s+"
    r"(?:pesan|message|msg)\s+(?:ke|to)\s+"
    r"(?:telegram|discord|slack|whatsapp|signal|email|sms|teams|matrix|line)"
    r"\b.+$",
    re.IGNORECASE,
)
_FACTUAL_QUESTION_RE = re.compile(
    r"^(?:apa|apakah|bisakah|dapatkah|siapa|kapan|di\s+mana|dimana|berapa|"
    r"mengapa|kenapa|bagaimana|what|who|when|where|why|how|is|are|can|could)\b"
    r"|\b(?:apa|siapa|kapan|berapa)\s*\?$",
    re.IGNORECASE,
)
_EXPLAIN_RE = re.compile(
    r"^(?:tolong\s+)?(?:jelaskan|terangkan|explain|define)\b", re.IGNORECASE
)
_SINGLE_SEARCH_RE = re.compile(
    r"^(?:tolong\s+)?(?:cari(?:kan)?|search(?:\s+for)?|find|look\s+up)\b",
    re.IGNORECASE,
)
_SINGLE_IMAGE_RE = re.compile(
    r"^(?:tolong\s+)?(?:"
    r"(?:buat(?:kan)?|bikin|ciptakan|generate)\s+(?:sebuah\s+|an?\s+)?"
    r"(?:gambar|image|foto)\s+|(?:gambar(?:kan)?|image)\s+)"
    r"(?P<prompt>.+)$",
    re.IGNORECASE,
)
_CONVERSATION_RE = re.compile(
    r"^(?:aku|saya|gue|i\s+am|i'm|i\s+feel|menurutmu|what\s+do\s+you\s+think)\b",
    re.IGNORECASE,
)
_ACTION_HINT_RE = re.compile(
    r"\b(?:"
    r"atur|set|ubah|edit|hapus|delete|buat|create|generate|buka|open|"
    r"tutup|close|jalankan|run|eksekusi|execute|kirim|send|balas|reply|"
    r"putar|play|klik|click|ketik|type|unggah|upload|unduh|download|"
    r"pindah|move|salin|copy|jadwal(?:kan)?|schedule|telepon|telpon|"
    r"panggil|call|jawab|answer|akhiri|hang\s*up|matikan|nyalakan|"
    r"aktifkan|nonaktifkan|perbaiki|fix|implement|otomatis"
    r")\b",
    re.IGNORECASE,
)
_WHATSAPP_ACTION_RE = re.compile(
    r"(?:\b(?:telepon|telpon|panggil|call|hubungi|jawab|answer|angkat|"
    r"akhiri|tutup|hang\s*up|kirim|send|balas|reply)\b.*\bwhats?app\b)"
    r"|(?:\bwhats?app\b.*\b(?:telepon|telpon|panggil|call|jawab|answer|"
    r"angkat|akhiri|hang\s*up|kirim|send|balas|reply)\b)"
    # Jarvis hanya memiliki satu transport panggilan native: WhatsApp.
    # Karena tool selalu meminta konfirmasi dan resolver hanya menerima
    # allowlist, "telepon Honbrew" aman diarahkan ke agent WhatsApp tanpa
    # mewajibkan user menyebut nama platform setiap kali.
    r"|(?:^(?:jarvis[,\s]+)?(?:tolong\s+)?(?:telepon|telpon|panggil|call)"
    r"\s+[\w .'-]{2,80}(?:\s+dan\b.*)?$)",
    re.IGNORECASE,
)
# Subset MEMULAI panggilan saja — dipakai juga oleh ExternalCallContract
# (§Fase 14). Sengaja dipisah dari _WHATSAPP_ACTION_RE di atas: pola itu ikut
# mencakup kirim/balas/jawab/akhiri, dan memaksakan kontrak panggilan pada
# pengiriman pesan akan melaporkan setiap pesan yang berhasil sebagai gagal.
WHATSAPP_START_CALL_RE = re.compile(
    r"(?:\b(?:telepon|telpon|panggil|call|hubungi)\b"
    r"(?!\s*(?:masuk|yang\s+masuk))[^.?!]*\bwhats?app\b)"
    r"|(?:\bwhats?app\b[^.?!]*\b(?:telepon|telpon|panggil|call|hubungi)\b)",
    re.IGNORECASE,
)
# Bentuk telanjang "telepon <sesuatu>" tanpa menyebut platform. Targetnya
# ditangkap agar pemanggil dapat memutuskan apakah itu benar-benar kontak.
# Tanpa pemeriksaan itu, "panggil taksi online lewat aplikasi Grab" ikut
# terbaca sebagai panggilan WhatsApp.
BARE_START_CALL_RE = re.compile(
    r"^(?:jarvis[,\s]+)?(?:tolong\s+)?(?:telepon|telpon|panggil|call|"
    r"hubungi)\s+(?P<target>[\w .'-]{2,80}?)(?:\s+(?:dan|lalu|kemudian)\b.*)?"
    r"\s*[.!]?$",
    re.IGNORECASE,
)
_WHATSAPP_HANGUP_RE = re.compile(
    r"\b(?:akhiri|tutup|hang\s*up)\b.*\b(?:panggilan|telepon|call)\b"
    r"(?:.*\bwhats?app\b)?|\bwhats?app\b.*\b(?:akhiri|hang\s*up)\b",
    re.IGNORECASE,
)
_BROWSER_MEDIA_RE = re.compile(
    r"^(?:jarvis[,\s]+)?(?:tolong\s+)?(?:"
    r"pause|jeda|lanjutkan|resume|play|putar|mute|unmute|"
    r"besarkan|kecilkan|naikkan|turunkan|atur|set|skip|lewati"
    r")\b.*\b(?:video|youtube|iklan|media|player)\b"
    r"|^(?:jarvis[,\s]+)?(?:tolong\s+)?(?:skip|lewati)\s+iklan\b",
    re.IGNORECASE,
)
_BROWSER_TAB_RE = re.compile(
    r"^(?:jarvis[,\s]+)?(?:tolong\s+)?(?:tutup|close|buat|buka|"
    r"pindah|switch|daftar|list)\b.*\btab\b",
    re.IGNORECASE,
)


def extract_image_prompt(text: str) -> str:
    """Return a single image prompt, or empty when the request is not bounded."""
    match = _SINGLE_IMAGE_RE.match(str(text or "").strip())
    return match.group("prompt").strip() if match else ""


def classify(text: str, context: dict | None = None) -> Route:
    """Classify one command without ever raising to its caller.

    ``context`` is deliberately small and optional.  A scheduler can mark a
    request ``autonomous=True`` (T4), while a native sub-agent can mark it
    ``delegated=True`` (T3).  Ordinary voice/text/Telegram requests need no
    special fields.
    """

    try:
        raw = text if isinstance(text, str) else str(text or "")
        normalized = _strip_command_prefix(_normalize(raw))
        ctx = context if isinstance(context, dict) else {}

        rule = _classify_rules(normalized, ctx)
        if rule is not None and rule.confidence >= _RULE_THRESHOLD:
            return rule

        if bool(config.get("router.llm_fallback", False)):
            parsed = _parse_llm_route(_call_classifier_with_budget(raw))
            if parsed is not None:
                return parsed

        return _safe_default(
            normalized, "deterministic ambiguity fallback")
    except Exception:  # noqa: BLE001 - the public contract is never-raise
        return _route(Tier.AGENT, "router failure; safe heavy default", 0.0)


def _classify_rules(text: str, context: dict[str, Any]) -> Route | None:
    source = _normalize(str(context.get("source", "")))
    if context.get("autonomous") is True or source in {
        "cron",
        "schedule",
        "scheduled",
        "scheduler",
    }:
        return _route(Tier.AUTONOMOUS, "scheduled autonomous execution", 0.99)
    if context.get("delegated") is True or source in {"delegate", "subagent"}:
        return _route(Tier.DELEGATE, "explicit delegated execution", 0.99)

    if not text:
        return None

    # A read-only data lookup remains a single tool call even when the user
    # asks for the "latest" item.  This preserves the explicit Calendar,
    # Gmail, news, and YouTube Data API examples in the master spec.
    if (
        _READ_ONLY_DATA_RE.search(text)
        and not _MUTATING_DATA_RE.search(text)
        and not _MULTI_STEP_RE.search(text)
        and not _AGENTIC_RE.search(text)
        and not _NON_FRESHNESS_ASSESSMENT_RE.search(text)
    ):
        return _route(Tier.SINGLE, "single read-only data request", 0.92)

    if _MULTI_STEP_RE.search(text):
        return _route(Tier.AGENT, "multi-step sequence", 0.97)
    if _WHATSAPP_HANGUP_RE.search(text):
        return _route(Tier.SINGLE, "single WhatsApp hangup action", 0.97)
    if _WHATSAPP_ACTION_RE.search(text):
        return _route(
            Tier.AGENT,
            "WhatsApp action requires an approved external-action tool",
            0.98,
        )
    if _BROWSER_MEDIA_RE.search(text):
        return _route(Tier.SINGLE, "single browser media action", 0.96)
    if _BROWSER_TAB_RE.search(text):
        return _route(Tier.SINGLE, "single browser tab action", 0.96)
    if _EXPLICIT_LEGACY_AGENT_RE.match(text):
        return _route(Tier.AGENT, "deprecated explicit agent request", 0.98)
    if _ASSESSMENT_RE.search(text):
        return _route(Tier.AGENT, "result assessment or selection", 0.94)
    if extract_image_prompt(text):
        return _route(Tier.SINGLE, "single image generation", 0.96)
    if _AGENTIC_RE.search(text):
        return _route(Tier.AGENT, "agentic work verb", 0.94)
    if _COMPUTER_WORK_RE.search(text):
        return _route(Tier.AGENT, "file, code, terminal, or browser workflow", 0.93)

    for pattern in _REFLEX_PATTERNS:
        if pattern.search(text):
            return _route(Tier.REFLEX, "deterministic reflex action", 0.96)

    if _LEGACY_UI_REFLEX_RE.match(text):
        return _route(Tier.REFLEX, "single local UI reflex", 0.94)

    if _SINGLE_FRAME_ACTION_RE.match(text):
        return _route(Tier.SINGLE, "single in-frame UI action", 0.90)

    if _OPEN_SINGLE_SITE_RE.match(text):
        return _route(Tier.SINGLE, "open one URL or known site", 0.91)

    app_match = _OPEN_APP_RE.match(text)
    if app_match:
        app = _normalize(app_match.group("app"))
        explicit_app = bool(re.search(r"\b(?:aplikasi|app)\b", text, re.I))
        if explicit_app or app in _KNOWN_APPS:
            return _route(Tier.REFLEX, "open one application", 0.91)

    close_match = _CLOSE_APP_RE.match(text)
    if close_match:
        app = _normalize(close_match.group("app"))
        explicit_app = bool(re.search(r"\b(?:aplikasi|app)\b", text, re.I))
        if explicit_app or app in _KNOWN_APPS:
            return _route(Tier.REFLEX, "close one application", 0.91)

    if _GREETING_RE.match(text):
        return _route(Tier.SINGLE, "greeting or conversational reflex", 0.96)
    if _TIME_WEATHER_RE.search(text):
        return _route(Tier.SINGLE, "single time or weather query", 0.93)
    if _SINGLE_SONG_RE.match(text):
        return _route(Tier.SINGLE, "play one song", 0.91)
    if _SINGLE_MESSAGE_RE.match(text):
        return _route(Tier.SINGLE, "single messaging action", 0.93)
    if _FACTUAL_QUESTION_RE.search(text) or _EXPLAIN_RE.match(text):
        return _route(Tier.SINGLE, "single factual or explanatory question", 0.87)
    if _SINGLE_SEARCH_RE.match(text):
        return _route(Tier.SINGLE, "single search query", 0.84)
    if _CONVERSATION_RE.match(text):
        return _route(Tier.SINGLE, "single conversational turn", 0.82)
    return None


def _call_gemini_classifier(text: str) -> str:
    """Call the existing agent LLM client, pinned to the Gemini provider."""

    from jarvis.agent import llm_client
    from jarvis.agent.providers import get_provider

    provider = get_provider("gemini")
    if provider.kind != "gemini" or not provider.configured():
        return ""
    model = str(config.get("llm.classify_model", provider.model) or provider.model)
    if model != provider.model:
        provider = replace(provider, model=model)
    client = llm_client.LLMClient(provider)
    return client.generate(text, system=_CLASSIFIER_SYSTEM, json_mode=True)


def _call_classifier_with_budget(text: str) -> str:
    """Bound the optional network fallback so synchronous seams stay usable.

    The existing ``router.classify_budget_ms`` setting is authoritative.  A
    timed-out request continues only in one daemon worker; while it is still
    running, further ambiguous commands immediately take the safe T2 default
    instead of accumulating provider calls.
    """

    try:
        budget_ms = int(config.get("router.classify_budget_ms", 100))
    except (TypeError, ValueError, OverflowError):
        budget_ms = 100
    budget_s = max(0.001, min(5.0, budget_ms / 1000.0))

    if not _classifier_lock.acquire(blocking=False):
        return ""

    done = threading.Event()
    result: dict[str, str] = {}

    def _worker() -> None:
        try:
            result["value"] = _call_gemini_classifier(text)
        except Exception:  # noqa: BLE001 - classify owns the safe fallback
            result["value"] = ""
        finally:
            _classifier_lock.release()
            done.set()

    threading.Thread(
        target=_worker,
        daemon=True,
        name="jarvis-tier-classifier",
    ).start()
    if not done.wait(budget_s):
        return ""
    return result.get("value", "")


def _parse_llm_route(raw: Any) -> Route | None:
    """Parse the first valid JSON object and reject every unsupported tier."""

    if isinstance(raw, dict):
        payload = raw
    elif isinstance(raw, str):
        payload = _first_json_object(raw)
    else:
        return None
    if not isinstance(payload, dict):
        return None

    value = payload.get("tier")
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number not in (Tier.REFLEX, Tier.SINGLE, Tier.AGENT):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    if isinstance(value, str) and value.strip() not in {"0", "1", "2"}:
        return None

    reason_value = payload.get("reason", "Gemini ambiguity classifier")
    reason = str(reason_value or "Gemini ambiguity classifier")
    reason = " ".join(reason.split())[:_MAX_REASON_CHARS]
    return _route(Tier(number), f"Gemini fallback: {reason}", 0.75)


def _first_json_object(raw: str) -> dict | None:
    # An array is a structurally different response, even if it happens to
    # contain one object.  Do not silently reinterpret it as the contract.
    if raw.lstrip().startswith("["):
        return None
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(raw[index:])
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _strip_command_prefix(value: str) -> str:
    """Remove at most one address and one polite filler, without network I/O."""

    text = str(value or "").strip()
    for _ in range(2):
        stripped = _COMMAND_PREFIX_RE.sub("", text, count=1).strip()
        if stripped == text:
            break
        text = stripped
    return text


def _route(tier: Tier, reason: str, confidence: float) -> Route:
    heavy = tier >= Tier.AGENT
    return Route(
        tier=tier,
        lane="heavy" if heavy else "light",
        model_profile="heavy" if heavy else "light",
        reason=reason[:_MAX_REASON_CHARS],
        confidence=max(0.0, min(1.0, float(confidence))),
    )


def _safe_default(text: str, reason: str) -> Route:
    """Keep ordinary ambiguity conversational without weakening action safety.

    Unknown text used to start a network classifier and then default to T2
    when the 100 ms budget elapsed.  That made natural conversation feel slow
    and could start an expensive agent for harmless small talk.  An unknown
    action still defaults to T2; text without an action verb stays in T1.
    """

    if _ACTION_HINT_RE.search(str(text or "")):
        return _route(Tier.AGENT, f"{reason}: actionable text", 0.45)
    return _route(Tier.SINGLE, f"{reason}: conversational text", 0.55)


__all__ = ["Route", "Tier", "classify"]
