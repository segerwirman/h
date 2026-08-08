"""Deterministic capability shortlist for lower first-agent latency.

The selector is conservative: if a task is broad or no category is recognized,
it returns ``None`` and the caller exposes the full registry.  Clear tasks get
only the relevant modules plus clarification and memory lookup.
"""
from __future__ import annotations

import re

from jarvis.core import config


_CATEGORY_PATTERNS: dict[str, re.Pattern[str]] = {
    "whatsapp": re.compile(
        r"\b(?:whats?app|telepon|telpon|panggil|call|angkat|hang\s*up)\b",
        re.I,
    ),
    "browser_web": re.compile(
        r"\b(?:browser|web|website|situs|halaman|page|navigasi|klik|"
        r"search|cari|riset|research|internet|url|youtube|tab|video|"
        r"pause|resume|skip|iklan)\b",
        re.I,
    ),
    "files_code": re.compile(
        r"\b(?:file|berkas|folder|directory|repo|kode|code|script|"
        r"terminal|powershell|bash|debug|refactor|patch|program|"
        r"source|dirimu|jarvis)\b",
        re.I,
    ),
    "computer": re.compile(
        r"\b(?:desktop|layar|screen|mouse|keyboard|aplikasi|app|window|"
        r"jendela|screenshot|scroll|drag)\b",
        re.I,
    ),
    "google": re.compile(
        r"\b(?:gmail|email|calendar|kalender|agenda|google\s+drive|"
        r"youtube\s+(?:channel|subscription|stat))\b",
        re.I,
    ),
    "spotify": re.compile(
        r"\b(?:spotify|lagu|musik|song|playlist|album|artist)\b",
        re.I,
    ),
    "home": re.compile(
        r"\b(?:home\s+assistant|lampu|sensor|smart\s+home|saklar)\b",
        re.I,
    ),
    "memory": re.compile(
        r"\b(?:ingat|memory|memori|lupa|forget|preferensi|preference)\b",
        re.I,
    ),
    "schedule": re.compile(
        r"\b(?:cron|jadwal|schedule|pengingat|reminder|berkala)\b",
        re.I,
    ),
    "image": re.compile(
        r"\b(?:buat|generate|edit)\b.*\b(?:gambar|image|foto|photo)\b",
        re.I,
    ),
    "prompt": re.compile(
        r"\b(?:prompt|system\s+prompt|instruksi\s+model)\b", re.I
    ),
    "mcp": re.compile(
        r"\b(?:mcp|model\s+context\s+protocol)\b", re.I
    ),
}

_CATEGORY_MODULES: dict[str, frozenset[str]] = {
    "whatsapp": frozenset({"whatsapp_web", "app_control"}),
    # §26 — `user_browser` ikut di sini. Keluhan lapangan "pause youtube tapi
    # jarvis tidak tahu tab saya" sebagian berasal dari sini: kategori browser
    # hanya memetakan browser AGENT, sehingga tool yang benar-benar menyentuh
    # Chrome user tidak pernah masuk schema.
    "browser_web": frozenset(
        {"browser", "user_browser", "web", "google_youtube", "app_control"}
    ),
    "files_code": frozenset(
        {"file_ops", "terminal", "code_exec", "session_tools"}
    ),
    "computer": frozenset({"computer", "app_control", "local_ui"}),
    "google": frozenset(
        {"gmail", "google_calendar", "google_drive", "google_youtube"}
    ),
    "spotify": frozenset({"spotify", "app_control"}),
    "home": frozenset({"home_assistant"}),
    "memory": frozenset({"memory_tools", "session_tools"}),
    "schedule": frozenset({"cron_tools", "todo", "task_tools"}),
    "image": frozenset({"image_gen", "vision", "local_ui"}),
    "prompt": frozenset({"prompt_files", "file_ops"}),
    "mcp": frozenset({"mcp_tools"}),
}

_ALWAYS_NAMES = frozenset(
    {
        "clarify",
        "memory_search",
        "capability_status",
        "task_status",
        "task_cancel",
    }
)


def _learned_tool_names(task: str, tools: dict[str, object]) -> list[str] | None:
    """Saran dari perintah yang pernah terbukti berhasil (Fase 26).

    Saran yang menyebut tool tak dikenal DIABAIKAN sepenuhnya: tool bisa
    hilang antar versi, dan mempersempit schema ke nama yang tidak ada berarti
    membuat Jarvis kehilangan kemampuan gara-gara catatan basi.
    """
    try:
        from jarvis.agent import command_index

        names = command_index.suggest(task)
        if not names:
            return None
        if any(name not in tools for name in names):
            return None
        selected = set(names)
        selected.update(name for name in _ALWAYS_NAMES if name in tools)
        return sorted(selected)
    except Exception:                                        # noqa: BLE001
        return None


def select_tool_names(task: str, tools: dict[str, object]) -> list[str] | None:
    if not bool(config.get("agent.tool_selection.enabled", True)):
        return None
    text = str(task or "").strip()
    if not text:
        return None
    categories = [
        name for name, pattern in _CATEGORY_PATTERNS.items()
        if pattern.search(text)
    ]
    # Broad cross-domain work is safer with the complete registry.
    if not categories or len(categories) > 3:
        # §26 — celah inilah yang dulu jatuh ke registry penuh (90 tool) atau
        # ke LLM. Perintah yang SUDAH terbukti berhasil di mesin ini menjawabnya
        # tanpa jaringan. Kategori deterministik tetap menang di atas: yang
        # sudah pasti tidak boleh dikalahkan yang dipelajari.
        return _learned_tool_names(text, tools)
    modules: set[str] = set()
    for category in categories:
        modules.update(_CATEGORY_MODULES[category])
    selected = {
        name
        for name, tool in tools.items()
        if type(tool).__module__.rsplit(".", 1)[-1] in modules
    }
    selected.update(name for name in _ALWAYS_NAMES if name in tools)
    try:
        limit = max(
            6, min(40, int(config.get("agent.tool_selection.max_tools", 18)))
        )
    except (TypeError, ValueError):
        limit = 18
    if not selected or len(selected) > limit:
        return None
    return sorted(selected)


__all__ = ["select_tool_names"]
