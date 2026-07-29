"""Locale untuk web/berita (MK50 §6) — region & bahasa tanpa hardcode.

Prioritas sumber (§6.3):

  1. ``config.yaml: locale`` — pilihan eksplisit user.
  2. Bahasa terdeteksi dari perintah (detektor deterministik Fase 2) atau
     "Silent Language Memory" Mark XLVIII (``identity.language`` di
     ``memory/long_term.json``) bila config kosong.
  3. Fallback terakhir: ``id-ID`` (user berdomisili Indonesia).

Konsumen: tool agent ``web_search``/``web_extract`` dan action legacy
``actions/web_search.py`` (jalur suara Gemini Live). Semua fungsi di sini
best-effort dan tidak pernah raise.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from jarvis.core import config, log

_logger = log.get("core.locale")

FALLBACK_REGION = "ID"
FALLBACK_LANGUAGE = "id"
FALLBACK_TIMEZONE = "Asia/Jakarta"


@dataclass(frozen=True)
class Locale:
    region: str          # kode negara, mis. "ID"
    language: str        # kode bahasa, mis. "id"
    timezone: str        # mis. "Asia/Jakarta"
    news_market: str     # mis. "id-ID"
    source: str          # "config" | "text" | "memory" | "fallback"

    @property
    def indonesian(self) -> bool:
        return self.region.upper() == "ID" or self.language.lower() == "id"


# ── deteksi bahasa (lapisan 2) ────────────────────────────────────────────

def _detect_text_language(text: str) -> str:
    """'id' | 'en' | '' — reuse detektor Fase 2; fallback heuristik lokal."""
    if not (text or "").strip():
        return ""
    try:
        from jarvis.agent.interaction import detect_language
        return detect_language(text)
    except Exception:                                        # noqa: BLE001
        low = f" {text.casefold()} "
        markers = (" apa ", " berita ", " hari ", " ini ", " terbaru ",
                   " yang ", " dan ", " di ", " cari ", " tolong ")
        return "id" if any(m in low for m in markers) else ""


def _memory_language() -> str:
    """Silent Language Memory XLVIII: identity.language dari long_term.json."""
    try:
        from memory.memory_manager import load_memory
        entry = (load_memory().get("identity") or {}).get("language", {})
        value = entry.get("value", "") if isinstance(entry, dict) \
            else str(entry or "")
        return str(value).strip().casefold()
    except Exception as e:                                   # noqa: BLE001
        _logger.warning("locale.memory_read_failed", error=str(e)[:100])
        return ""


def _is_indonesian_label(label: str) -> bool:
    return bool(label) and ("indonesia" in label or label in ("id", "id-id"))


# ── resolusi utama ────────────────────────────────────────────────────────

def resolve(text: str | None = None) -> Locale:
    """Locale efektif untuk satu permintaan. Tidak pernah raise."""
    try:
        cfg_region = str(config.get("locale.region", "") or "").strip()
        cfg_language = str(config.get("locale.language", "") or "").strip()
        cfg_tz = str(config.get("locale.timezone", "") or "").strip()
        cfg_market = str(config.get("locale.news_market", "") or "").strip()
    except Exception:                                        # noqa: BLE001
        cfg_region = cfg_language = cfg_tz = cfg_market = ""

    region, language, source = "", "", ""
    if cfg_region:
        region = cfg_region
        language = cfg_language or FALLBACK_LANGUAGE
        source = "config"
    else:
        if _detect_text_language(str(text or "")) == "id":
            region, language, source = "ID", "id", "text"
        elif _is_indonesian_label(_memory_language()):
            region, language, source = "ID", "id", "memory"

    if not region:
        region, source = FALLBACK_REGION, "fallback"
        language = cfg_language or FALLBACK_LANGUAGE
    elif not language:
        language = FALLBACK_LANGUAGE

    market = cfg_market or f"{language.lower()}-{region.upper()}"
    return Locale(region=region.upper(), language=language.lower(),
                  timezone=cfg_tz or FALLBACK_TIMEZONE,
                  news_market=market, source=source)


def ddg_region(text: str | None = None, loc: Locale | None = None) -> str:
    """Region format ddgs (param ``kl``), mis. "id-id", "us-en"."""
    loc = loc or resolve(text)
    return f"{loc.region.lower()}-{loc.language.lower()}"


def accept_language(text: str | None = None,
                    loc: Locale | None = None) -> str:
    """Header Accept-Language untuk pengambilan halaman (web_extract)."""
    loc = loc or resolve(text)
    primary = f"{loc.language.lower()}-{loc.region.upper()}"
    if loc.language.lower() == "en":
        return f"{primary},en;q=0.9"
    return f"{primary},{loc.language.lower()};q=0.9,en;q=0.6"


# ── augmentasi query berita (§6.2) ────────────────────────────────────────

_GENERIC_TOKENS = frozenset({
    # id
    "apa", "berita", "kabar", "terbaru", "terkini", "utama", "hari", "ini",
    "dunia", "sekarang", "terhangat",
    # en
    "what", "whats", "the", "top", "world", "latest", "current", "news",
    "headline", "headlines", "today", "todays", "breaking", "recent",
})


def is_generic_news(query: str) -> bool:
    """True bila query berita tanpa subjek spesifik ("berita terbaru hari
    ini", "top world news today") — layak diganti konteks lokal penuh."""
    tokens = re.findall(r"[a-zA-Z]+", (query or "").casefold())
    if not tokens:
        return True
    return all(t in _GENERIC_TOKENS for t in tokens)


def news_query(query: str, loc: Locale | None = None) -> str:
    """Query akhir untuk pencarian berita (§6.2).

    Generik → diganti frasa lokal utuh; spesifik → dibiarkan (penargetan
    lewat param ``region``), agar subjek user tidak terdistorsi.
    """
    loc = loc or resolve(query)
    if not is_generic_news(query):
        return query
    if loc.indonesian:
        return "berita terbaru Indonesia hari ini"
    return "top news today"
