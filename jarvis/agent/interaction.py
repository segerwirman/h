"""Language-aware feedback text for interactive native-agent tasks.

This module only renders lifecycle text. It deliberately knows nothing about
Qt, Gemini Live, Telegram, or the agent loop, so every existing transport can
keep using its current (and, for voice/UI, frozen) delivery mechanism.
"""
from __future__ import annotations

import random
import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from jarvis.core import config


def _int_config(key: str, default: int, *, lo: int, hi: int) -> int:
    """Bounded int from config; never raises, always within [lo, hi]."""
    try:
        value = int(config.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(value, hi))


def speech_limit() -> int:
    """Anggaran karakter ucapan. Default besar agar kalimat JARVIS tidak
    terpotong di tengah; bisa diperkecil untuk kanal remote lewat config."""
    return _int_config("agent.interaction.speech_limit", 900, lo=120, hi=4000)


def speech_sentence_limit() -> int:
    """Maks kalimat brief ucapan; default cukup untuk jawaban natural."""
    return _int_config("agent.interaction.speech_sentence_limit", 6, lo=1, hi=40)


# Kompatibilitas: konstanta lama tetap ada sebagai nilai awal/default, tetapi
# jalur runtime memakai speech_limit()/speech_sentence_limit() yang honor config.
SPEECH_LIMIT = 900
SPEECH_SENTENCE_LIMIT = 6
ACK_LIMIT = 180

_DEFAULT_ACKS = {
    "id": (
        "Baik, {address}. Saya kerjakan.",
        "Siap, {address}. Sedang saya kerjakan.",
        "Segera saya tangani, {address}.",
    ),
    "en": (
        "Right away, {address}. I'll handle it.",
        "Understood, {address}. I'm on it.",
        "Certainly, {address}. I'll take care of it.",
    ),
}

_ID_MARKERS = {
    "aku", "anda", "analisis", "bandingkan", "baik", "buka", "buat",
    "buatkan", "dan", "dengan", "di", "ini", "kerjakan", "kemudian",
    "laporan", "lalu", "paling", "perbaiki", "riset", "saya", "siap",
    "sedang", "setelah", "tolong", "terbaru", "untuk",
}
_EN_MARKERS = {
    "analyze", "and", "build", "compare", "create", "fix", "for",
    "handle", "hello", "i", "in", "latest", "open", "please", "report",
    "research", "right", "the", "then", "this", "with", "you",
}
_GENERIC_RESULT_RE = re.compile(
    r"^(?:(?:tugas\s+)?(?:selesai|beres|done|ok|okay)|"
    r"(?:task\s+)?(?:completed|finished))(?:\s+tanpa\s+keluaran|"
    r"\s+without\s+(?:an?\s+)?output)?[.!]?$",
    re.IGNORECASE,
)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_HTML_RE = re.compile(r"<[^>]+>")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^\)]+\)")
_SPACE_RE = re.compile(r"\s+")
_DISPLAY_CONTROL_RE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]+")
_URL_RE = re.compile(r"https?://[^\s<>()]+")
_WINDOWS_PATH_RE = re.compile(r"(?<!\w)[A-Za-z]:[\\/][^\s<>|?*\"]+")
_NUMBER_RE = re.compile(r"(?<!\w)\d[\d.,:%-]*(?!\w)")
_QUOTED_TEXT_RE = re.compile(r"[\"“]([^\"”\n]{1,160})[\"”]")


@dataclass(frozen=True)
class ConversationDelivery:
    """Dua representasi hasil terverifikasi untuk display dan suara."""

    display_text: str
    speech_text: str
    factual_anchors: tuple[str, ...]
    mode: str = "deterministic"


def detect_language(task: str) -> str:
    """Return id or en using a deterministic, no-network task cue."""

    text = unicodedata.normalize("NFKC", str(task or "")).casefold()
    tokens = re.findall(r"[a-z]+", text)
    id_score = sum(token in _ID_MARKERS for token in tokens)
    en_score = sum(token in _EN_MARKERS for token in tokens)
    if en_score > id_score:
        return "en"
    return "id"


def persona_address() -> str:
    """Read the configured existing persona and return its form of address."""

    try:
        path = config.resolve_path(
            str(config.get("agent.persona_file", "core/prompt.txt"))
        )
        prompt = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 - persona failure must not block a task
        return "sir"

    patterns = (
        r"""(?im)^\s*ADDRESS\s*:[^\n]*?["'“]([^"'”\n]{1,32})["'”]""",
        r"""(?i)(?:always\s+say|memanggil\s+user)\s+["'“]([^"'”\n]{1,32})["'”]""",
    )
    for pattern in patterns:
        match = re.search(pattern, prompt)
        if match:
            candidate = _clean_address(match.group(1))
            if candidate:
                return candidate
    return "sir"


def sanitize_for_speech(value: object, limit: int | None = None) -> str:
    """Collapse controls/markup and bound text without cutting a word."""

    text = unicodedata.normalize("NFKC", str(value or ""))
    text = _CONTROL_RE.sub(" ", text)
    text = _MARKDOWN_LINK_RE.sub(r"\1", text)
    text = _HTML_RE.sub(" ", text)
    text = text.replace(chr(96) * 3, " ").replace(chr(96), "")
    text = re.sub(r"(?<!\w)[#>*~]+|[#>*~]+(?!\w)", " ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    cap = max(16, int(limit if limit is not None else speech_limit()))
    if len(text) <= cap:
        return text
    clipped = text[: cap - 1].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0].rstrip()
    return (clipped or text[: cap - 1]).rstrip(" ,;:-") + "…"


def sanitize_for_display(value: object) -> str:
    """Bersihkan control/markup tanpa membuang detail report atau newline."""

    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _DISPLAY_CONTROL_RE.sub(" ", text)
    text = text.replace(chr(96) * 3, "").replace(chr(96), "")
    text = re.sub(r"(?<!\w)[#>*~]+|[#>*~]+(?!\w)", "", text)
    return "\n".join(line.strip() for line in text.split("\n") if line.strip())


def factual_anchors(value: object) -> tuple[str, ...]:
    """Extract immutable-looking facts in source order for delivery checks."""

    text = sanitize_for_display(value)
    matches: list[tuple[int, str]] = []
    for pattern in (_URL_RE, _WINDOWS_PATH_RE, _NUMBER_RE):
        matches.extend((match.start(), match.group(0)) for match in pattern.finditer(text))
    matches.extend((match.start(1), match.group(1).strip())
                   for match in _QUOTED_TEXT_RE.finditer(text))
    seen: set[str] = set()
    anchors = []
    for _, value in sorted(matches):
        if value and value not in seen:
            seen.add(value)
            anchors.append(value)
    return tuple(anchors)


def _speech_brief(value: str) -> str:
    """Keep at most N source sentences before applying the char budget."""

    sentences = [match.group(0).strip() for match in re.finditer(
        r"[^.!?]+[.!?]?(?=\s|$)", str(value or "")
    )]
    return " ".join(sentence for sentence in sentences[:speech_sentence_limit()]
                    if sentence)


def success_delivery(
    raw_result: object,
    task: str,
    *,
    language: str | None = None,
    address: str | None = None,
    speech_limit: int | None = None,
) -> ConversationDelivery:
    """Compose detailed display output plus a short deterministic spoken brief."""

    display = sanitize_for_display(raw_result)
    first_line = next((line for line in display.splitlines() if line), display)
    speech = render_success(_speech_brief(first_line), task, language=language,
                            address=address, limit=speech_limit)
    return ConversationDelivery(display_text=display, speech_text=speech,
                                factual_anchors=factual_anchors(display))


def failure_delivery(
    raw_error: object,
    task: str,
    *,
    language: str | None = None,
    address: str | None = None,
    speech_limit: int | None = None,
) -> ConversationDelivery:
    """Compose an honest detailed failure report plus a bounded spoken brief."""

    display = sanitize_for_display(raw_error)
    speech = render_failure(display, task, language=language,
                            address=address, limit=speech_limit)
    return ConversationDelivery(display_text=display, speech_text=speech,
                                factual_anchors=factual_anchors(display))


def render_ack(
    task: str,
    *,
    legacy_ack: str | None = None,
    language: str | None = None,
    address: str | None = None,
    chooser: Callable[[Sequence[str]], str] | None = None,
) -> str:
    """Render a varied ACK while retaining agent.ack_phrase as a choice."""

    lang = _language(language, task)
    address = _clean_address(address) or persona_address()
    configured = _template_list(
        config.get(f"agent.interaction.ack_templates.{lang}", None)
    )
    templates = configured or list(_DEFAULT_ACKS[lang])

    legacy = legacy_ack
    if legacy is None:
        legacy = str(config.get("agent.ack_phrase", "") or "")
    legacy = sanitize_for_speech(legacy, ACK_LIMIT)
    if legacy and detect_language(legacy) == lang:
        templates.insert(0, legacy)

    rendered: list[str] = []
    for template in templates:
        candidate = _with_address(template, address, ACK_LIMIT)
        if candidate and candidate not in rendered:
            rendered.append(candidate)
    if not rendered:
        rendered = [_with_address(_DEFAULT_ACKS[lang][0], address, ACK_LIMIT)]

    pick = chooser or random.choice
    try:
        chosen = pick(tuple(rendered))
    except Exception:  # noqa: BLE001 - custom chooser is optional
        chosen = rendered[0]
    return chosen if chosen in rendered else rendered[0]


def render_success(
    raw_result: object,
    task: str,
    *,
    language: str | None = None,
    address: str | None = None,
    limit: int | None = None,
) -> str:
    """Render a concrete success report directly from the verified result."""

    lang = _language(language, task)
    limit = int(limit if limit is not None else speech_limit())
    address = _clean_address(address) or persona_address()
    reserve = len(address) + 4
    result = sanitize_for_speech(raw_result, max(32, limit - reserve))
    if not result or _GENERIC_RESULT_RE.fullmatch(result):
        if lang == "en":
            return _with_address(
                "The task ended without a verifiable result.", address, limit
            )
        return _with_address(
            "Tugas berakhir tanpa hasil yang dapat diverifikasi.",
            address,
            limit,
        )
    return _with_address(result, address, limit)


def render_failure(
    raw_error: object,
    task: str,
    *,
    language: str | None = None,
    address: str | None = None,
    limit: int | None = None,
) -> str:
    """Render an honest failure report that retains the concrete reason."""

    lang = _language(language, task)
    limit = int(limit if limit is not None else speech_limit())
    address = _clean_address(address) or persona_address()
    if lang == "en":
        prefix = f"Sorry, {address}. The task failed"
        empty = "No error detail was provided"
    else:
        prefix = f"Maaf, {address}. Tugas gagal"
        empty = "Tidak ada detail kesalahan"
    reason = sanitize_for_speech(
        raw_error, max(32, limit - len(prefix) - 3)
    ) or empty
    return sanitize_for_speech(f"{prefix}: {reason}.", limit)


def _refusal_cause(task: str) -> str:
    """Kenapa dispatch menolak start? Deteksi best-effort, tidak pernah raise.

    Nilai: ``disabled`` | ``heavy_unconfigured`` | ``busy`` | ``""``.
    """
    try:
        from jarvis.core import config as _config
        if not bool(_config.get("agent.enabled", True)):
            return "disabled"
        from jarvis.agent import dispatch as _dispatch
        from jarvis.agent import model_routing as _model_routing
        if not _model_routing.heavy_ready():
            return "heavy_unconfigured"
        if _dispatch.is_active(task):
            return "busy"
    except Exception:  # noqa: BLE001 - reason text must never break refusal
        pass
    return ""


def unavailable_reason(task: str, language: str | None = None) -> str:
    """Return a localized reason when the primitive refuses to start."""

    english = _language(language, task) == "en"
    cause = _refusal_cause(task)
    if cause == "disabled":
        if english:
            return "The native agent is disabled in the configuration"
        return "Agent native sedang dinonaktifkan di konfigurasi"
    if cause == "heavy_unconfigured":
        # §3.2 — degrade jujur: model berat belum diatur, arahkan ke Settings.
        if english:
            return ("The model for heavy tasks is not set up yet — please "
                    "connect a heavy provider in Settings (gear icon)")
        return ("Model untuk tugas berat belum diatur — silakan hubungkan "
                "provider berat di Settings (ikon gear)")
    if cause == "busy":
        if english:
            return "The same task is still running"
        return "Tugas yang sama masih berjalan"
    if english:
        return (
            "The agent is not ready because its provider is not configured "
            "or the same task is already running"
        )
    return (
        "Agent belum siap karena provider belum dikonfigurasi atau tugas "
        "yang sama masih berjalan"
    )


def _language(language: str | None, task: str) -> str:
    hint = str(language or "").strip().casefold()
    if hint.startswith("en"):
        return "en"
    if hint.startswith("id"):
        return "id"
    return detect_language(task)


def _template_list(value: object) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = list(value)
    else:
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def _clean_address(value: object) -> str:
    candidate = _SPACE_RE.sub(" ", str(value or "")).strip(" .,!?:;\"'")
    if (
        not candidate
        or len(candidate) > 32
        or not any(char.isalpha() for char in candidate)
    ):
        return ""
    if not all(char.isalpha() or char in " .'-" for char in candidate):
        return ""
    return candidate


def _with_address(text: object, address: str, limit: int) -> str:
    rendered = str(text or "").replace("{address}", address)
    rendered = sanitize_for_speech(
        rendered, max(16, limit - len(address) - 3)
    )
    if not rendered:
        return ""
    if not re.search(
        rf"(?i)(?<!\w){re.escape(address)}(?!\w)", rendered
    ):
        rendered = rendered.rstrip(" .!?;,") + f", {address}."
    return sanitize_for_speech(rendered, limit)
