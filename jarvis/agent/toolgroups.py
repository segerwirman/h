"""Grup tool (PARITY v2 §5.4-5.5, §5.8) — pemetaan modul nyata Jarvis.

Grup = unit toggle di tab Tools. Dua konsep TERPISAH (§5.5):

    available  — modul lolos import + gate ``available()`` registry.
                 False → render abu, toggle terkunci. BUKAN pilihan user.
    enabled    — user sengaja mematikan lewat config.yaml
                 ``tools.disabled_groups``. Toggle bisa diklik.

Penegakan (§5.8): ``disabled_tool_names()`` dipanggil loop.py saat
menyusun schema run baru — tool grup mati TIDAK masuk schema LLM.
Kontrak "Changes apply to new sessions": snapshot per run, tidak berubah
di tengah run.

Pemetaan dari 18 modul nyata di jarvis/agent/tools/ — BUKAN salinan buta
21 grup Hermes (Jarvis punya ``food``, Hermes tidak; penamaan/subtitle
mengikuti referensi img 4 bila padan).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.core import config, log
from jarvis.agent import registry

_logger = log.get("agent.toolgroups")


@dataclass(frozen=True)
class ToolGroup:
    id: str
    name: str
    subtitle: str
    modules: tuple[str, ...]


_DESKTOP_SAFE_MODULES = (
    "desktop_observe",
    "desktop_safe_click",
    "desktop_safe_scroll",
    "desktop_safe_set_content_title",
    "desktop_safe_reorder_scene",
    "desktop_safe_set_value",
    "desktop_safe_toggle",
)


TOOL_GROUPS: tuple[ToolGroup, ...] = (
    ToolGroup("file_operations", "File Operations",
              "read, write, patch, search", ("file_ops",)),
    ToolGroup("prompt_library", "Prompt Library",
              "generate, save, read prompts", ("prompt_files",)),
    ToolGroup("terminal_processes", "Terminal & Processes",
              "terminal, process", ("terminal",)),
    ToolGroup("browser_automation", "Browser Automation",
              "navigate, click, type, scroll", ("browser",)),
    ToolGroup("computer_use", "Computer Use",
              "desktop control", ("computer",)),
    ToolGroup("desktop_safe", "Desktop Safe",
              "semantic local desktop actions with verification",
              _DESKTOP_SAFE_MODULES),
    ToolGroup("app_control", "Application Control",
              "open/close apps and Jarvis camera",
              ("app_control", "local_ui")),
    ToolGroup("skills", "Skills",
              "list, view, manage", ("skill_tools",)),
    ToolGroup("web_search", "Web Search & Scraping",
              "web_search, web_extract", ("web",)),
    ToolGroup("task_planning", "Task Planning", "todo", ("todo",)),
    ToolGroup("background_tasks", "Background Tasks",
              "start, status, cancel, result", ("task_tools",)),
    ToolGroup("clarifying", "Clarifying Questions", "clarify", ("clarify",)),
    ToolGroup("session_search", "Session Search",
              "search past conversations", ("session_tools",)),
    ToolGroup("code_execution", "Code Execution",
              "execute_code", ("code_exec",)),
    ToolGroup("vision_analysis", "Vision / Image Analysis",
              "vision_analyze", ("vision",)),
    ToolGroup("memory", "Memory",
              "persistent memory across sessions", ("memory_tools",)),
    ToolGroup("delegation", "Task Delegation",
              "delegate_task", ("delegate",)),
    ToolGroup("cron_jobs", "Cron Jobs",
              "create/list/update/pause/resume/run", ("cron_tools",)),
    ToolGroup("home_assistant", "Home Assistant",
              "smart home device control", ("home_assistant",)),
    ToolGroup("image_generation", "Image Generation",
              "image_generate", ("image_gen",)),
    ToolGroup("spotify", "Spotify",
              "playback, search, playlists, library", ("spotify",)),
    ToolGroup("food", "Food & Calories",
              "food analysis (khas Jarvis)", ("food",)),
    ToolGroup("mcp", "MCP",
              "mcp_list, mcp_connect, mcp_call — server eksternal",
              ("mcp_tools",)),
    ToolGroup("google_cloud", "Google Cloud",
              "Calendar, YouTube Data, Gmail, Drive",
              ("google_calendar", "google_youtube", "gmail",
               "google_drive")),
    ToolGroup("whatsapp_web", "WhatsApp Web",
              "allowlisted messaging and voice calls", ("whatsapp_web",)),
    ToolGroup("content_studio", "Content Studio",
              "bounded local project prompt intake", ("content_studio",)),
    ToolGroup("capability_diagnostics", "Capability Diagnostics",
              "runtime tools, provider readiness, blocked integrations",
              ("capability_status",)),
)

_UNAVAILABLE_HINTS: dict[str, str] = {
    "google_cloud": "Hubungkan Google OAuth dan aktifkan API yang diperlukan.",
    "home_assistant": "Isi URL dan token Home Assistant.",
    "image_generation": "Pilih provider/model yang mendukung image generation.",
    "mcp": "Tambahkan server ke mcp.servers lalu gunakan mcp_connect.",
    "spotify": "Hubungkan kredensial Spotify.",
}

# modul terdaftar yang tidak terpetakan → grup fallback, tetap terlihat &
# bisa di-toggle; tidak ada tool yang diam-diam lolos dari panel
FALLBACK_GROUP = ToolGroup("other", "Other", "modul belum terpetakan", ())


def _module_of(tool) -> str:
    return type(tool).__module__.rsplit(".", 1)[-1]


def _tools_by_module() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, tool in registry.all_tools().items():
        out.setdefault(_module_of(tool), []).append(name)
    return out


def disabled_group_ids() -> set[str]:
    values = config.get("tools.disabled_groups", [])
    if values is None:
        return set()
    if isinstance(values, str):
        values = [values]
    try:
        return {str(v).strip() for v in values if str(v).strip()}
    except TypeError:
        return set()


def all_groups() -> list[dict]:
    """Status runtime tiap grup untuk UI/service.

    available = punya minimal satu tool terdaftar (modul yang gagal import
    atau gate ``available()``-nya False tidak menghasilkan tool).
    """
    by_module = _tools_by_module()
    disabled = disabled_group_ids()
    mapped: set[str] = set()
    out = []
    for g in TOOL_GROUPS:
        tools: list[str] = []
        for mod in g.modules:
            tools.extend(by_module.get(mod, []))
            mapped.add(mod)
        out.append({
            "id": g.id, "name": g.name, "subtitle": g.subtitle,
            "tools": sorted(tools),
            "available": bool(tools),
            "enabled": g.id not in disabled,
            "availability_reason": (
                "" if tools else _UNAVAILABLE_HINTS.get(
                    g.id, "Dependency atau konfigurasi belum tersedia.")
            ),
        })
    orphans = sorted(t for mod, names in by_module.items()
                     if mod not in mapped for t in names)
    if orphans:
        _logger.warning("toolgroups.unmapped_modules",
                        tools=",".join(orphans)[:200])
        out.append({
            "id": FALLBACK_GROUP.id, "name": FALLBACK_GROUP.name,
            "subtitle": FALLBACK_GROUP.subtitle, "tools": orphans,
            "available": True,
            "enabled": FALLBACK_GROUP.id not in disabled,
            "availability_reason": "",
        })
    return out


def disabled_tool_names() -> set[str]:
    """Nama tool dari grup yang user matikan — untuk exclude schema LLM."""
    disabled = disabled_group_ids()
    if not disabled:
        return set()
    out: set[str] = set()
    for g in all_groups():
        if g["id"] in disabled:
            out.update(g["tools"])
    return out


# ═══════════════════════════════════════════════════════════════════════════
# AUDIT_REPORT §8.2 — peta tool → sumber daya eksklusif
#
# Dua agent tidak boleh sama-sama menyetir mouse: yang satu menggerakkan
# kursor, yang lain mengklik di posisi yang sudah berubah. Nama di bawah
# diserialkan oleh TaskRegistry; tool yang tidak terdaftar jalan paralel.
#
# Dipetakan per MODUL supaya konsisten dengan TOOL_GROUPS di atas dan tidak
# perlu diperbarui tiap kali satu tool ditambahkan ke modul yang sama.
# ═══════════════════════════════════════════════════════════════════════════

MODULE_RESOURCES: dict[str, frozenset[str]] = {
    # pyautogui / input OS — computer_click, computer_type, computer_key,
    # computer_scroll, computer_drag. computer_screenshot ikut disertakan:
    # ia lewat lease DESKTOP yang sama (tools/computer.py:15), dan §8
    # memerintahkan tool ambigu dimasukkan ke eksklusif.
    "computer": frozenset({"desktop"}),
    **{module: frozenset({"desktop"}) for module in _DESKTOP_SAFE_MODULES},
    # Satu context Playwright persisten dipakai bersama seluruh browser_*
    # (13 tool). Dua agent yang menavigasi context yang sama akan saling
    # menimpa halaman.
    "browser": frozenset({"browser_context"}),
    # Dedicated persistent context, but only one WhatsApp call may own the
    # virtual audio pair at a time.
    "whatsapp_web": frozenset({"whatsapp_call"}),
    # analyze_food_calories dapat mengambil frame kamera live
    # (tools/food.py:47 → _live_camera_jpeg).
    "food": frozenset({"camera"}),
    "local_ui": frozenset({"camera"}),
    "vision": frozenset({"camera"}),
}

# Override per-tool bila satu modul bercampur. Kosong untuk sekarang —
# didokumentasikan supaya penambahan berikutnya punya tempat yang jelas.
TOOL_RESOURCES: dict[str, frozenset[str]] = {}

# Sengaja TANPA resource (jalan paralel penuh), dicatat agar keputusannya
# bisa ditinjau, bukan disimpulkan dari ketiadaan:
#   web_search / web_extract / file_* / memory_* / session_search / todo_*
#                   — murni I/O jaringan atau berkas
#   terminal / execute_code / process_spawn
#                   — subprocess sendiri-sendiri, tidak berebut perangkat.
#                     CATATAN: keduanya belum bisa di-hard-kill saat cancel;
#                     lihat CANCEL_LIMITATION di jarvis/agent/tasks.py.
#   delegate_task   — sub-agent memakai registry yang sama, sehingga
#                     resource-nya terkunci di level tool anak, bukan di sini.


def resources_for_tool(tool_name: str) -> frozenset[str]:
    """Sumber daya eksklusif yang dibutuhkan satu tool. Kosong = paralel."""
    name = str(tool_name or "")
    if name in TOOL_RESOURCES:
        return TOOL_RESOURCES[name]
    tool = registry.all_tools().get(name)
    if tool is None:
        return frozenset()
    return MODULE_RESOURCES.get(_module_of(tool), frozenset())


def resources_for_tools(tool_names) -> frozenset[str]:
    """Gabungan sumber daya untuk sekumpulan tool."""
    out: set[str] = set()
    for name in tool_names or ():
        out |= resources_for_tool(name)
    return frozenset(out)
