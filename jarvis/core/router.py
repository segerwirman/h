"""IntentRouter (Part 3.1) — classifies commands before the LLM answers.

Fast path: keyword + regex, well under the 100 ms budget. The LLM fallback is
used only when the rules layer flags ambiguity, and only if enabled in config.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import Enum

from jarvis.core import config, llm, log

_logger = log.get("router")


class Intent(str, Enum):
    SEARCH_WEB = "SEARCH_WEB"
    OPEN_APP   = "OPEN_APP"
    OPEN_URL   = "OPEN_URL"
    OPEN_BROWSER_AGENT = "OPEN_BROWSER_AGENT"   # compatibility: system browser
    SYSTEM     = "SYSTEM"
    CHAT       = "CHAT"
    NATIVE_AGENT_TASK = "NATIVE_AGENT_TASK"
    HERMES_TASK = "NATIVE_AGENT_TASK"            # deprecated enum alias
    CLARIFY    = "CLARIFY"                      # ambigu — bertanya, bukan menebak


@dataclass
class Classified:
    intent: Intent
    confidence: float
    slots: dict = field(default_factory=dict)
    source: str = "rules"          # rules | llm
    elapsed_ms: float = 0.0


_URL_RE = re.compile(
    r"(https?://\S+|www\.\S+|\b[\w-]+\.(?:com|org|net|io|dev|id|co|tv|gg|ai)\b\S*)",
    re.IGNORECASE)

# Natural voice commands commonly include an address and a polite filler.
# Normalize those locally so "Jarvis, coba buka WhatsApp" reaches the exact
# same fast path as "buka WhatsApp"; ordinary conversation remains CHAT.
_COMMAND_PREFIX_RE = re.compile(
    r"^(?:(?:(?:hey|hai|halo)\s+)?jarvis\s*[,;:—-]?\s*|"
    r"(?:tolong|please|coba)\s+)",
    re.IGNORECASE)

_SEARCH_RE = re.compile(
    r"^(?:tolong\s+)?(?:cari(?:kan)?|search(?:\s+for)?|googling|google|"
    r"apa\s+itu|siapa(?:\s+itu)?|what\s+is|what'?s|who\s+is|"
    r"berita\s+(?:tentang|soal)|find\s+(?:info|information)\s+(?:on|about)|"
    r"look\s+up)\s+(?P<q>.+)$",
    re.IGNORECASE)

# Berita adalah data live, bukan chat/browser URL biasa. Tangkap bentuk natural
# seperti "berita hari ini" dan "berita teknologi terbaru" sebelum fallback.
_NEWS_RE = re.compile(
    r"^(?:tolong\s+)?(?:cari(?:kan)?\s+)?(?P<q>"
    r"(?:berita|news)(?:\s+.+)?|"
    r"(?:tampilkan|berikan)\s+(?:aku\s+)?(?:berita|news)(?:\s+.+)?)\s*[?!.,]*$",
    re.IGNORECASE)

_OPEN_RE = re.compile(
    r"^(?:tolong\s+)?(?:buka(?:kan)?|jalankan|launch|open|start|run|ke)\s+(?P<t>.+)$",
    re.IGNORECASE)

# Compatibility intent for opening the user's system browser. MK50 §7 keeps
# browser surfaces out of ContentStage; purposeful web work routes to T2.
# This rule MUST run before _OPEN_RE, which would otherwise misroute
# "buka browser" / "buka browser agent" to OPEN_APP.
_BROWSER_AGENT_RE = re.compile(
    r"^(?:tolong\s+)?(?:buka(?:kan)?|jalankan|tampilkan|open|launch|start|show)\s+"
    r"(?:the\s+)?(?:browser(?:\s*agent)?|agen\s+browser|default\s+browser|"
    r"browser\s+default|browser\s+bawaan|peramban)"
    r"\b(?P<rest>.*)$",
    re.IGNORECASE)

# Explicit external-browser escape hatch ("open in external/system browser").
_EXTERNAL_BROWSER_RE = re.compile(
    r"\b(?:external|system|eksternal|sistem)\s+browser\b"
    r"|\bbrowser\s+(?:eksternal|sistem)\b",
    re.IGNORECASE)

# Mark L Change 6: play/tonton → YouTube results page rendered in-stage
_PLAY_RE = re.compile(
    r"^(?:tolong\s+)?(?:putar|puterin|play|tonton)\s+(?:video\s+)?(?P<q>.+)$",
    re.IGNORECASE)

# ── Native messaging/agent detection (fast-path regex, NO LLM) ───────────────
_NATIVE_SEND_RE = re.compile(
    r"^(?:tolong\s+)?(?:kirim(?:kan)?|send)\s+(?:pesan|message|msg)\s+"
    r"(?:ke|to)\s+(?P<platform>telegram|discord|slack|whatsapp|signal|"
    r"email|sms|teams|matrix|line)\b"
    r"(?:\s+(?:channel|grup|group|ke))?\s*[:,]?\s*(?P<text>.*)$",
    re.IGNORECASE)

# Compatibility phrase: a user saying "suruh Hermes" is transparently routed
# to Jarvis' native agent, never to an external executable.
_LEGACY_AGENT_EXPLICIT_RE = re.compile(
    r"^(?:tolong\s+)?(?:suruh|minta|perintahkan|delegasikan\s+ke)\s+hermes\s+"
    r"(?P<task>.+)$",
    re.IGNORECASE)

_NATIVE_AGENT_TASK_RE = re.compile(
    r"\b(?:"
    r"review\s+(?:code|kode)|"
    r"buat(?:kan)?\s+(?:project|proyek|aplikasi|api|script|program)|"
    r"riset(?:kan)?\s+|research\s+|deep\s*research|"
    r"jadwalkan|schedule|buat(?:kan)?\s+(?:cron|jadwal\s+otomatis)|"
    r"analisis\s+(?:repo|repository|codebase|folder\s+project)|"
    r"deploy(?:kan)?\s+|"
    r"generate\s+(?:image|gambar)|buat(?:kan)?\s+gambar"
    r")",
    re.IGNORECASE)

# SYSTEM: (pattern, action) — value groups optional
_SYSTEM_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:atur\s+|set\s+)?volume\s*(?:ke\s*|to\s*)?(?P<value>\d{1,3})\b", re.I), "volume_set"),
    (re.compile(r"\b(?:naikkan|besarkan|turn\s*up|raise)\s+volume|volume\s+(?:naik|up)\b", re.I), "volume_up"),
    (re.compile(r"\b(?:turunkan|kecilkan|turn\s*down|lower)\s+volume|volume\s+(?:turun|down)\b", re.I), "volume_down"),
    (re.compile(r"\b(?:matikan|senyapkan|mute)\s+(?:suara|audio|volume|sound)\b", re.I), "volume_mute"),
    (re.compile(r"\b(?:matikan|turn\s*off|disable)\s+(?:wifi|wi-fi)\b", re.I), "wifi_off"),
    (re.compile(r"\b(?:nyalakan|hidupkan|turn\s*on|enable)\s+(?:wifi|wi-fi)\b", re.I), "wifi_on"),
    (re.compile(r"\b(?:atur\s+|set\s+)?(?:kecerahan|brightness)\s*(?:ke\s*|to\s*)?(?P<value>\d{1,3})?\b", re.I), "brightness"),
    (re.compile(r"\b(?:screenshot|tangkap\s+layar|capture\s+screen)\b", re.I), "screenshot"),
    (re.compile(r"\b(?:kunci\s+(?:layar|komputer)|lock\s+(?:screen|pc|computer))\b", re.I), "lock"),
    (re.compile(r"\b(?:matikan|shutdown)\s+(?:komputer|pc|laptop|computer)\b", re.I), "shutdown"),
    (re.compile(r"\b(?:restart|mulai\s+ulang)\s+(?:komputer|pc|laptop|computer)\b", re.I), "restart"),
    (re.compile(r"\b(?:mode\s+gelap|dark\s+mode)\b", re.I), "dark_mode"),
    (re.compile(r"\b(?:aktifkan|nyalakan|arm)\s+(?:kontrol\s+)?gestur|gesture\s+control\s+on\b", re.I), "gesture_arm"),
    (re.compile(r"\b(?:matikan|nonaktifkan|disarm)\s+(?:kontrol\s+)?gestur|gesture\s+control\s+off\b", re.I), "gesture_disarm"),
    # Mark L: voice vision panel (Change 5), back-to-home (Change 7), reply (Change 1)
    (re.compile(r"\b(?:buka|tampilkan|show|open)\s+(?:kamera(?:\s+utama)?|(?:main\s+)?camera)\b", re.I), "vision_open"),
    (re.compile(r"\b(?:tutup|close)\s+(?:kamera|camera)\b", re.I), "vision_close"),
    # MK50 — analisis kalori makanan via kamera (hasil pop-up di frame)
    (re.compile(r"\b(?:berapa\s+kalori|analisis\s+(?:kalori|makanan|gizi)|"
                r"hitung\s+kalori|cek\s+(?:kalori|gizi)|"
                r"kalori\s+makanan(?:\s+ini|nya)?|scan\s+(?:makanan|kalori)|"
                r"how\s+many\s+calories|analyze\s+(?:food|calorie|calories)|"
                r"calorie\s+(?:check|scan)|food\s+calories?)\b", re.I),
     "calorie_analyze"),
    (re.compile(r"^(?:back\s+to\s+home|home|kembali\s+ke\s+(?:menu|tampilan)\s+utama|kembali)$", re.I), "home"),
    (re.compile(r"^balas[:,]?\s+(?P<value>.+)$", re.I | re.S), "reply"),
    # redesign §13 — destructive-action target resolver: a NAMED close
    # target routes through jarvis.core.target_resolver instead of the
    # blind alt+F4 close_app fallback (vision/tab close above still win —
    # this pattern is listed after them so those specific cases match first).
    # DIAGNOSIS_2 MASALAH 3 — "matikan dirimu" adalah permintaan BERHENTI,
    # bukan menutup aplikasi. Ditaruh SEBELUM close_target, tapi setelah
    # pola matikan-wifi/suara/komputer di atas sehingga tidak menyerobotnya.
    (re.compile(r"^(?:tolong\s+)?(?:matikan|shutdown|stop|hentikan|keluar|"
                r"exit|quit|tutup|close)\s+(?:dirimu|dirinya|diri\s*mu|kamu|"
                r"jarvis|asisten|yourself|the\s+assistant)\b", re.I),
     "shutdown_jarvis_request"),
    (re.compile(r"^(?:tolong\s+)?(?:tutup|close)\s+(?P<value>.+)$", re.I), "close_target"),
    (re.compile(r"^(?:buka\s+lagi|reopen)\s+(?:tab\s+)?(?:terakhir|last)\b", re.I), "reopen_last_tab"),
]

# DIAGNOSIS_2 MASALAH 1 — penanda niat EKSPLISIT. Bila salah satu muncul,
# router tidak perlu menimbang apa pun: user sudah mengatakan maksudnya.
_APP_KEYWORD_RE = re.compile(
    r"\b(?:app|apps|aplikasi|aplikasinya|program|software|desktop)\b",
    re.IGNORECASE)
_SITE_KEYWORD_RE = re.compile(
    r"\b(?:situs|website|web|webnya|url|link|laman|browser|online)\b",
    re.IGNORECASE)
_ALL_WINDOWS_RE = re.compile(r"\b(?:semua|seluruh|all)\b", re.IGNORECASE)

_APP_HINTS = {
    "spotify", "vscode", "vs code", "visual studio code", "chrome", "edge",
    "firefox", "notepad", "word", "excel", "powerpoint", "discord", "steam",
    "whatsapp", "telegram", "obs", "terminal", "cmd", "explorer", "calculator",
    "kalkulator", "paint", "photoshop",
}


class IntentRouter:
    def __init__(self) -> None:
        self._known_sites: dict = {
            k.lower(): v for k, v in config.section("router.known_sites").items()
        }
        self._llm_fallback = bool(config.get("router.llm_fallback", False))

    # ── public API ───────────────────────────────────────────────────────────

    def classify(self, text: str) -> Classified:
        t0 = time.perf_counter()
        command = self._strip_command_prefix(text.strip())
        result = self._rules(command)
        if result is None and self._llm_fallback:
            result = self._llm_classify(command)
        if result is None:
            result = Classified(Intent.CHAT, 0.5)
        result.elapsed_ms = (time.perf_counter() - t0) * 1000
        _logger.info("intent.classified", intent=result.intent.value,
                     confidence=result.confidence, source=result.source,
                     elapsed_ms=round(result.elapsed_ms, 1),
                     slots=result.slots, text=text[:120])
        return result

    @staticmethod
    def _strip_command_prefix(text: str) -> str:
        value = str(text or "").strip()
        for _ in range(2):
            stripped = _COMMAND_PREFIX_RE.sub("", value, count=1).strip()
            if stripped == value:
                break
            value = stripped
        return value

    # ── rules layer ──────────────────────────────────────────────────────────

    def _rules(self, text: str) -> Classified | None:
        if not text:
            return Classified(Intent.CHAT, 1.0)

        # Legacy wording is accepted, but execution is always native.
        m = _LEGACY_AGENT_EXPLICIT_RE.match(text)
        if m:
            return Classified(Intent.NATIVE_AGENT_TASK, 0.98,
                              {"tier": 3, "task": m.group("task").strip()})

        for pattern, action in _SYSTEM_PATTERNS:
            m = pattern.search(text)
            if m:
                slots = {"action": action}
                if "value" in m.groupdict() and m.group("value"):
                    slots["value"] = m.group("value")
                if action == "close_target":
                    resolved = self._resolve_close(slots.get("value", ""))
                    if resolved is not None:
                        return resolved
                return Classified(Intent.SYSTEM, 0.95, slots)

        m = _NATIVE_SEND_RE.match(text)
        if m:
            return Classified(Intent.NATIVE_AGENT_TASK, 0.92, {
                "tier": 2, "action": "send",
                "platform": m.group("platform").lower(),
                "text": (m.group("text") or "").strip(),
            })

        m = _BROWSER_AGENT_RE.match(text)
        if m:
            slots: dict = {"external": bool(_EXTERNAL_BROWSER_RE.search(text))}
            um = _URL_RE.search(m.group("rest") or "")
            if um:
                slots["url"] = self._normalize_url(um.group(0))
            return Classified(Intent.OPEN_BROWSER_AGENT, 0.95, slots)

        m = _PLAY_RE.match(text)
        if m:
            from urllib.parse import quote_plus
            template = str(config.get(
                "browser.video.yt_results_template",
                "https://www.youtube.com/results?search_query={query}"))
            q = m.group("q").strip()
            return Classified(Intent.OPEN_URL, 0.9,
                              {"url": template.format(query=quote_plus(q)),
                               "site": "youtube", "video": True})

        m = _NEWS_RE.match(text)
        if m:
            return Classified(Intent.SEARCH_WEB, 0.97, {
                "query": m.group("q").strip(), "mode": "news"})

        m = _SEARCH_RE.match(text)
        if m:
            return Classified(Intent.SEARCH_WEB, 0.95, {
                "query": m.group("q").strip(), "mode": "search"})

        um = _URL_RE.search(text)
        m = _OPEN_RE.match(text)
        if m:
            target = m.group("t").strip().rstrip("?.!")
            return self._resolve_open(target, um)

        if um and len(text.split()) <= 4:
            return Classified(Intent.OPEN_URL, 0.85,
                              {"url": self._normalize_url(um.group(0))})

        # Tugas berat multi-step → agent native (async + ACK instan).
        # Diperiksa SETELAH semua fast-path native di atas sehingga perintah
        # ringan tidak pernah salah masuk ke jalur async.
        if _NATIVE_AGENT_TASK_RE.search(text):
            return Classified(Intent.NATIVE_AGENT_TASK, 0.85,
                              {"tier": 3, "task": text})

        # interrogatives with search-ish shape stay CHAT (LLM has web tools);
        # everything else is CHAT by definition.
        return Classified(Intent.CHAT, 0.8)

    # ── "tutup X" — jangan pernah menebak targetnya (DIAGNOSIS_2 MASALAH 3) ──

    # Kata yang TIDAK menyebut target apa pun. "tutup aplikasi" bukan perintah
    # menutup aplikasi bernama — itu kalimat setengah jadi.
    _VAGUE_CLOSE = {
        "aplikasi", "app", "apps", "program", "software",
        "jendela", "jendela ini", "window", "this window", "ini", "itu",
        "semua", "semuanya", "everything",
    }

    def _resolve_close(self, value: str) -> "Classified | None":
        from jarvis.core import app_registry, process_guard

        raw = " ".join(str(value or "").split())
        low = raw.lower().strip(" .!?")

        # "tutup jarvis" / "tutup dirimu" bukan close_app — itu permintaan
        # berhenti, dan wajib lewat konfirmasi.
        if process_guard.refers_to_jarvis(low):
            return Classified(Intent.SYSTEM, 0.97, {
                "action": "shutdown_jarvis_request",
                "value": raw,
            })

        # Nama proses yang dilindungi ("tutup python") ditolak dengan
        # penjelasan, bukan dicoba lalu gagal di tengah jalan.
        if process_guard.is_protected_name(low):
            return Classified(Intent.SYSTEM, 0.97, {
                "action": "close_blocked",
                "value": raw,
            })

        if not low or low in self._VAGUE_CLOSE:
            return Classified(Intent.CLARIFY, 0.95, {
                "topic": "",
                "question": "Aplikasi mana yang harus saya tutup?",
                "options": [],
                "kind": "close_target",
            })

        # "tutup semua chrome" → target "chrome", semua jendelanya sekaligus,
        # tanpa bertanya lagi. Kata "semua" adalah jawaban, bukan nama.
        all_windows = bool(_ALL_WINDOWS_RE.search(low))
        without_all = _ALL_WINDOWS_RE.sub(" ", raw)

        # Nama yang tersisa setelah membuang penanda ("aplikasi instagram"
        # → "instagram") supaya close_app menerima target yang bersih.
        cleaned = app_registry.normalize(
            _APP_KEYWORD_RE.sub(" ", without_all)) or low
        if not cleaned or cleaned in self._VAGUE_CLOSE:
            return Classified(Intent.CLARIFY, 0.95, {
                "topic": "",
                "question": "Aplikasi mana yang harus saya tutup?",
                "options": [],
                "kind": "close_target",
            })
        return Classified(Intent.SYSTEM, 0.95, {
            "action": "close_app", "value": cleaned, "raw": raw,
            "all_windows": all_windows,
        })

    # ── "buka X" — aplikasi, situs, atau bertanya (DIAGNOSIS_2 MASALAH 1) ───

    def _resolve_open(self, target: str, url_match) -> Classified | None:
        """Urutan barunya penting: ``known_sites`` TIDAK LAGI menang otomatis.

        Itu akar masalahnya — "buka instagram" selalu jadi URL walau aplikasi
        Instagram terpasang, dan user tidak pernah ditanya.
        """
        from jarvis.core import app_registry

        raw = target.strip()
        wants_app = bool(_APP_KEYWORD_RE.search(raw))
        wants_site = bool(_SITE_KEYWORD_RE.search(raw))
        # Penanda niat dibuang dari NAMA-nya: "website instagram" harus dicari
        # sebagai "instagram", bukan sebagai frasa utuh yang tak akan pernah
        # cocok dengan known_sites maupun indeks aplikasi.
        stripped = _SITE_KEYWORD_RE.sub(" ", _APP_KEYWORD_RE.sub(" ", raw))
        clean = app_registry.normalize(stripped)
        # Normalisasi hanya untuk MENCOCOKKAN. Yang diluncurkan tetap memakai
        # kapitalisasi asli — "Spotify" bukan "spotify" — karena beberapa
        # peluncur (macOS, .desktop) peka huruf besar-kecil.
        display = " ".join(stripped.split()) or raw

        # (a) niat EKSPLISIT — selesai, jangan menimbang apa pun lagi.
        if wants_site and not wants_app:
            if url_match:
                return Classified(Intent.OPEN_URL, 0.97,
                                  {"url": self._normalize_url(url_match.group(0))})
            site = self._known_sites.get(clean)
            return Classified(Intent.OPEN_URL, 0.95,
                              {"url": site or search_url(clean or raw),
                               "site": clean})
        if wants_app and not wants_site:
            return Classified(Intent.OPEN_APP, 0.95, {"app": display})

        # URL/domain harfiah selalu berarti web — "buka instagram.com".
        if url_match:
            return Classified(Intent.OPEN_URL, 0.95,
                              {"url": self._normalize_url(url_match.group(0))})

        if not clean:
            return None

        # (b) preferensi yang sudah dipelajari mengalahkan tebakan apa pun —
        # inilah yang membuat Jarvis bertanya SEKALI saja.
        learned = app_registry.preference_for(clean)
        if learned == "app":
            return Classified(Intent.OPEN_APP, 0.93,
                              {"app": display, "source": "learned"})
        if learned == "web":
            site = self._known_sites.get(clean)
            return Classified(Intent.OPEN_URL, 0.93,
                              {"url": site or search_url(clean),
                               "site": clean, "source": "learned"})

        # (c) tidak ada penanda — timbang KEDUANYA.
        match = app_registry.resolve(clean)
        app_hit = match is not None or clean in _APP_HINTS
        site_hit = clean in self._known_sites

        if app_hit and site_hit:
            # Ambigu sungguhan. Menebak di sini persis bug yang dilaporkan.
            app_label = match.name if match is not None else clean
            return Classified(Intent.CLARIFY, 0.9, {
                "topic": clean,
                "question": f"Aplikasi {app_label} atau buka di browser?",
                "options": ["aplikasi", "browser"],
                "app": display,
                "url": self._known_sites[clean],
            })
        if app_hit:
            # Nama dari indeks lebih tepat daripada ketikan user bila ada.
            name = match.name if (match is not None
                                  and match.source != "path") else display
            return Classified(Intent.OPEN_APP, 0.9, {"app": name})
        if site_hit:
            return Classified(Intent.OPEN_URL, 0.9,
                              {"url": self._known_sites[clean], "site": clean})

        # (d) tidak cocok apa pun — serahkan ke LLM, jangan mengarang.
        return None

    @staticmethod
    def _normalize_url(url: str) -> str:
        return url if url.lower().startswith("http") else f"https://{url}"

    # ── LLM fallback (ambiguity only) ────────────────────────────────────────

    def _llm_classify(self, text: str) -> Classified | None:
        prompt = (
            "Classify this assistant command into exactly one label:\n"
            "SEARCH_WEB, OPEN_APP, OPEN_URL, SYSTEM, CHAT.\n"
            f"Command: {text!r}\n"
            "Answer with only the label."
        )
        answer = llm.generate(
            prompt, model=config.get("llm.classify_model")).strip().upper()
        for intent in Intent:
            if intent.value in answer:
                slots = {}
                if intent is Intent.OPEN_APP:
                    m = _OPEN_RE.match(text)
                    slots["app"] = m.group("t").strip() if m else text
                elif intent is Intent.SEARCH_WEB:
                    slots["query"] = text
                return Classified(intent, 0.7, slots, source="llm")
        return None


def search_url(query: str) -> str:
    from urllib.parse import quote_plus
    template = config.get("router.search_engine_url",
                          "https://duckduckgo.com/?q={query}")
    return template.format(query=quote_plus(query))
