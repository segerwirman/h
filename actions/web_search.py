# web_search.py
import json
import traceback
import sys
from pathlib import Path

from jarvis.core import log

_logger = log.get("actions.web_search")


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


# ── Locale (MK50 §6) ───────────────────────────────────────────────────────────
# Region/bahasa dari jarvis.core.locale (config → bahasa/Silent Language
# Memory → fallback id-ID). Gagal import/resolve → perilaku lama (tanpa
# region), tidak pernah menggagalkan pencarian.

def _locale(query: str = ""):
    try:
        from jarvis.core import locale as jlocale
        return jlocale.resolve(query)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Locale unavailable ({e}) — no region injection")
        return None


def _ddg_region(query: str = "") -> str | None:
    loc = _locale(query)
    if loc is None:
        return None
    return f"{loc.region.lower()}-{loc.language.lower()}"


def _get_api_key() -> str:
    from jarvis.core import llm
    return llm.api_key() or ""


def _gemini_search(query: str) -> str:
    from google import genai

    client   = genai.Client(api_key=_get_api_key())
    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=query,
        config={"tools": [{"google_search": {}}]},
    )

    text = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            text += part.text

    text = text.strip()
    if not text:
        raise ValueError("Gemini returned an empty response.")
    return text


def _ddg_kwargs(query: str, max_results: int) -> dict:
    """kwargs ddgs dengan region locale (§6) — tanpa region bila resolver mati."""
    kwargs: dict = {"max_results": max_results}
    region = _ddg_region(query)
    if region:
        kwargs["region"] = region
    return kwargs


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, **_ddg_kwargs(query, max_results)):
            results.append({
                "title":   r.get("title",  ""),
                "snippet": r.get("body",   ""),
                "url":     r.get("href",   ""),
            })
    return results


def _ddg_news(query: str, max_results: int = 8) -> list[dict]:
    """DDG news search — returns actual articles, not website homepages."""
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.news(query, **_ddg_kwargs(query, max_results)):
                results.append({
                    "title":   r.get("title",  ""),
                    "snippet": r.get("body",   ""),
                    "url":     r.get("url",    ""),
                    "source":  r.get("source", ""),
                    "date":    r.get("date",   ""),
                })
    except Exception as e:
        print(f"[WebSearch] ⚠️ DDG news() failed ({e}) — falling back to text search")
        results = _ddg_search(query, max_results=max_results)
    return results


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   Source: {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _publish_info_card(query: str, results: list[dict],
                       kind: str = "news") -> None:
    """Kartu berita/search ke InfoPanel (§7.2), selalu best-effort."""
    try:
        from jarvis.core.bus import BUS
        if kind == "news":
            lines = [f"{r.get('title', '')}  "
                     f"[{r.get('source', '')} {r.get('date', '')}]".strip()
                     for r in results[:6] if r.get("title")]
            source = "DuckDuckGo News"
        else:
            lines = [f"{r.get('title', '')} — {r.get('url', '')}".strip(" —")
                     for r in results[:6] if r.get("title")]
            source = "DuckDuckGo Search"
        if lines:
            BUS.publish("info.card", kind=kind, title=query,
                        lines=lines, source=source, ts="")
    except Exception as e:
        print(f"[WebSearch] ⚠️ info card publish failed ({e})")


def _publish_text_card(query: str, text: str) -> None:
    try:
        from jarvis.core.bus import BUS
        BUS.publish("info.card", kind="search", title=query,
                    lines=[text[:1600]], source="Gemini Search", ts="")
    except Exception as e:
        print(f"[WebSearch] ⚠️ info card publish failed ({e})")


def _format_news(query: str, results: list[dict]) -> str:
    if not results:
        return "Tidak menemukan berita untuk itu, sir."

    lines = [f"Latest news: {query}\n"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        if not title:
            continue
        # §6.2 — judul + sumber + waktu
        src_bits = [b for b in (r.get("source"), r.get("date")) if b]
        src = f"  [{' — '.join(src_bits)}]" if src_bits else ""
        lines.append(f"{i}. {title}{src}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:140]}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


# ── Briefing helper ────────────────────────────────────────────────────────────

def _gemini_headlines(n: int = 5) -> tuple[list[str], str]:
    """
    Fetches current headlines via Gemini grounded search.
    Optimised for speed: minimal prompt + strict token cap.
    Returns (headline_list, raw_text_for_display).
    """
    import re
    from google import genai

    client = genai.Client(api_key=_get_api_key())
    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=f"Current world news: {n} headlines. Numbered list, titles only.",
        config={"tools": [{"google_search": {}}]},
    )

    raw = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            raw += part.text

    headlines = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Only accept lines that begin with a number — skips preamble/closing sentences
        if not re.match(r'^[\d]+[.\)\-]', line):
            continue
        clean = re.sub(r'^[\d]+[.\)\-]\s*', '', line)
        clean = re.sub(r'^\*+\s*',          '', clean).strip()
        if clean and len(clean) > 10:
            headlines.append(clean)

    return headlines[:n], raw.strip()


# ── Modes ──────────────────────────────────────────────────────────────────────

def _search(query: str) -> str:
    """Default search — Gemini grounded, DDG fallback."""
    try:
        result = _gemini_search(query)
        _publish_text_card(query, result)
        return result
    except Exception as e:
        print(f"[WebSearch] ⚠️ Gemini failed ({e}) — trying DDG...")
        results = _ddg_search(query)
        _publish_info_card(query, results, kind="search")
        return _format_ddg(query, results)


def _news_failure_message(errors: list[BaseException]) -> str:
    """Pesan user-facing jujur; exception asli disimpan pada DEBUG log."""
    detail = " ".join(f"{type(e).__name__}: {e}" for e in errors).lower()
    if any(marker in detail for marker in (
        "429", "resource_exhausted", "quota", "rate limit", "rate_limit")):
        return "Kuota API berita habis, sir. Perlu perpanjangan."
    if any(marker in detail for marker in (
        "timeout", "timed out", "connection", "network", "dns", "unreachable",
        "name resolution", "proxy", "ssl")):
        return "Tidak bisa menjangkau sumber berita. Koneksi bermasalah."
    return "Sumber berita sedang bermasalah, sir. Coba lagi beberapa saat."


def _news(query: str) -> str:
    """
    Runs Gemini grounded search AND DDG news in parallel.
    Returns whichever delivers a valid result first; cancels the other.

    MK50 §6: query dilokalkan — generik ("berita terbaru hari ini",
    "top world news today" dari briefing) menjadi frasa lokal penuh; subjek
    spesifik dipertahankan dan hanya dibungkus sesuai bahasa locale.
    """
    import threading

    loc = _locale(query)
    ddg_query = None
    if loc is not None:
        try:
            from jarvis.core import locale as jlocale
            ddg_query = jlocale.news_query(query or "", loc)
        except Exception as e:
            print(f"[WebSearch] ⚠️ news_query localization failed ({e})")
            ddg_query = None

    if ddg_query is None:                     # resolver mati → perilaku lama
        gemini_query = f"latest news today: {query}" if query else "top world news today"
        ddg_query    = query if query else "world news today"
    elif ddg_query == (query or ""):          # subjek spesifik dari user
        gemini_query = (f"berita terbaru hari ini: {query}"
                        if loc.indonesian else f"latest news today: {query}")
    else:                                     # generik → frasa lokal penuh
        gemini_query = ddg_query

    result_box  = [None]   # first valid result lands here
    lock        = threading.Lock()
    done_evt    = threading.Event()
    outcomes: list[tuple[str, str | BaseException]] = []

    def _store(source: str, result: str) -> None:
        if result and len(result) > 60:
            with lock:
                if result_box[0] is None:
                    result_box[0] = result
            done_evt.set()
            return
        with lock:
            outcomes.append((source, result))
            if len(outcomes) >= 2:
                done_evt.set()

    def _failed(source: str, exc: BaseException) -> None:
        # Traceback asli masuk log file, tidak pernah diteruskan ke user/UI.
        _logger.error("news.backend_failed", backend=source,
                      exc_type=type(exc).__name__, error=str(exc)[:300],
                      traceback=traceback.format_exc())
        with lock:
            outcomes.append((source, exc))
            if len(outcomes) >= 2:
                done_evt.set()

    def _try_gemini():
        try:
            _store("gemini", _gemini_search(gemini_query))
        except Exception as e:
            print(f"[WebSearch] ⚠️ Gemini news failed ({e})")
            _failed("gemini", e)

    def _try_ddg():
        try:
            results = _ddg_news(ddg_query, max_results=8)
            _publish_info_card(ddg_query, results)
            _store("ddg", _format_news(ddg_query, results))
        except Exception as e:
            print(f"[WebSearch] ⚠️ DDG news failed ({e})")
            _failed("ddg", e)

    threading.Thread(target=_try_gemini, daemon=True).start()
    threading.Thread(target=_try_ddg,    daemon=True).start()

    if not done_evt.wait(timeout=10.0):
        timeout = TimeoutError("news backends exceeded 10 second deadline")
        _logger.debug("news backends timed out", exc_info=(
            type(timeout), timeout, timeout.__traceback__))
        return _news_failure_message([timeout])
    if result_box[0]:
        return result_box[0]
    errors = [value for _source, value in outcomes
              if isinstance(value, BaseException)]
    if errors:
        return _news_failure_message(errors)
    return "Tidak menemukan berita untuk itu, sir."


def _research(query: str) -> str:
    """
    Deep dive — asks Gemini for a comprehensive answer with context.
    Falls back to a wider DDG fetch.
    """
    research_query = (
        f"Comprehensive, detailed explanation of: {query}. "
        "Include background context, key facts, current state, and important nuances."
    )
    try:
        return _gemini_search(research_query)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Research Gemini failed ({e}) — DDG fallback...")
        results = _ddg_search(query, max_results=10)
        return _format_ddg(query, results)


def _price(query: str) -> str:
    """Product price lookup — searches for current market prices."""
    price_query = f"current price of {query} — how much does it cost today"
    try:
        return _gemini_search(price_query)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Price Gemini failed ({e}) — DDG fallback...")
        results = _ddg_search(f"{query} price buy", max_results=6)
        return _format_ddg(query, results)


def _compare(items: list[str], aspect: str) -> str:
    query = (
        f"Compare {', '.join(items)} in terms of {aspect}. "
        "Give specific facts and data."
    )
    try:
        return _gemini_search(query)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Gemini compare failed: {e} — falling back to DDG")

    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Comparison — {aspect.upper()}", "─" * 40]
    for item in items:
        lines.append(f"\n▸ {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  • {r['snippet']}")
            if r.get("url"):
                lines.append(f"    {r['url']}")
    return "\n".join(lines)


# ── Public entry point ─────────────────────────────────────────────────────────

def web_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query  = params.get("query", "").strip()
    mode   = params.get("mode",  "search").lower().strip()
    items  = params.get("items", [])
    aspect = params.get("aspect", "general").strip() or "general"

    if not query and not items:
        return "Please provide a search query."

    if items and mode not in ("compare",):
        mode = "compare"

    if player:
        player.write_log(f"[Search:{mode}] {query or ', '.join(items)}")

    print(f"[WebSearch] 🔍 mode={mode!r}  query={query!r}")

    try:
        if mode == "compare" and items:
            return _compare(items, aspect)
        if mode == "news":
            return _news(query)
        if mode == "research":
            return _research(query)
        if mode == "price":
            return _price(query)
        return _search(query)

    except Exception as e:
        print(f"[WebSearch] ❌ All backends failed: {e}")
        return f"Search failed: {e}"
