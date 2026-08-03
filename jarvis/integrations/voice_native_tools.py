"""Low-latency native browser/media tools for the Gemini Live voice lane.

Conversation still belongs to the existing Gemini Live session.  This seam
only exposes deterministic controls that should not require a full agent
round-trip: current media, browser tabs, and ending an active WhatsApp call.
Complex browser work and outbound calls continue through the native agent.
"""
from __future__ import annotations

from types import SimpleNamespace

_REPLACED_LEGACY_NAMES = frozenset({
    "browser_control",
    "youtube_video",
    "file_controller",
    "save_memory",
    "weather_report",
    "reminder",
    "computer_settings",
    "send_message",
    "close_camera",
})

_TOOL_NAMES = frozenset({
    "open_app",
    "close_app",
    "web_search",
    "browser_navigate",
    "browser_snapshot",
    "youtube_search",
    "file_read",
    "file_search",
    "file_list",
    "memory_search",
    "weather_lookup",
    "reminder_create",
    "system_reflex",
    "message_send",
    "camera_close",
    "capability_status",
    "browser_media",
    "browser_tabs",
    "browser_new_tab",
    "browser_switch_tab",
    "browser_close_tab",
    "whatsapp_hangup",
    "whatsapp_status",
    "voice_briefing",
})


def native_tool_names() -> frozenset[str]:
    """Names whose Live function calls are executed by native registry."""
    return _TOOL_NAMES


def rules() -> str:
    """Native-tool guidance appended to the Live system instruction."""
    return _RULES


def message_task(args: dict) -> str:
    """Format handoff native tanpa platform fallback atau side effect."""
    values = dict(args or {})
    platform = " ".join(str(values.get("platform", "") or "").split())
    recipient = " ".join(str(values.get("recipient", "") or "").split())
    message = " ".join(str(values.get("message", "") or "").split())
    label = {"whatsapp": "WhatsApp", "telegram": "Telegram"}.get(
        platform.casefold(), platform.title())
    return f"Kirim pesan {label} ke {recipient}: {message}".strip()

_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Buka aplikasi desktop dengan launcher native Jarvis. Gunakan saat "
            "user meminta membuka aplikasi. Jangan mengaku berhasil sebelum "
            "hasil tool menyatakan sukses."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING", "description": "Nama aplikasi"}
            },
            "required": ["name"],
        },
    },
    {
        "name": "close_app",
        "description": (
            "Tutup aplikasi desktop bernama secara anggun. Jangan gunakan untuk "
            "mematikan Jarvis. Jangan mengaku berhasil sebelum hasil tool "
            "menyatakan sukses."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "name": {"type": "STRING", "description": "Nama aplikasi"},
                "force": {"type": "BOOLEAN", "description": "Paksa tutup; butuh konfirmasi"},
                "all_windows": {"type": "BOOLEAN", "description": "Tutup semua jendela aplikasi"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "web_search",
        "description": (
            "Cari web native Jarvis dan kembalikan hasil terbaru. Gunakan mode "
            "news untuk berita. Jangan mengaku sudah membuka situs atau "
            "menjalankan aksi browser."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Kueri pencarian"},
                "max_results": {"type": "INTEGER", "description": "1-15, default 6"},
                "mode": {"type": "STRING", "description": "text | news"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "browser_navigate",
        "description": (
            "Buka URL di browser agent native. Setelah ini gunakan "
            "browser_snapshot sebelum click/type atau klaim isi halaman."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "URL tujuan"}
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_snapshot",
        "description": (
            "Baca halaman browser agent: URL, judul, teks, dan ref elemen. "
            "Panggil setelah browser_navigate dan sebelum browser_click/type."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "youtube_search",
        "description": (
            "Cari video YouTube di browser agent native. Setelahnya panggil "
            "browser_snapshot dan pilih ref video; jangan mengaku video diputar "
            "sebelum browser_media memberi hasil sukses."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Kueri YouTube"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "file_read",
        "description": (
            "Baca file teks native dalam workspace Jarvis. File biner tidak dibaca. "
            "Jangan menulis, menghapus, atau memindahkan file."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Path file"},
                "offset": {"type": "INTEGER", "description": "Baris awal 0-based"},
                "limit": {"type": "INTEGER", "description": "Maksimum baris, 0 semua"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "file_search",
        "description": "Cari regex dalam file workspace Jarvis; read-only.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "pattern": {"type": "STRING", "description": "Regex"},
                "path": {"type": "STRING", "description": "Folder awal opsional"},
                "glob": {"type": "STRING", "description": "Filter nama file opsional"},
                "max_results": {"type": "INTEGER", "description": "Batas hasil"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "file_list",
        "description": "Daftar isi folder workspace Jarvis; read-only.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "Folder opsional"},
                "depth": {"type": "INTEGER", "description": "Kedalaman tree"},
            },
        },
    },
    {
        "name": "memory_search",
        "description": (
            "Cari memori persisten native dalam scope percakapan lokal. "
            "Read-only; jangan gunakan untuk menyimpan fakta baru."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Apa yang dicari"},
                "type": {"type": "STRING", "description": "Filter jenis opsional"},
                "limit": {"type": "INTEGER", "description": "Batas hasil"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "weather_lookup",
        "description": "Cari cuaca terbaru secara native, tanpa membuka browser sistem.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "Kota"},
                "when": {"type": "STRING", "description": "today atau tomorrow"},
            },
            "required": ["city"],
        },
    },
    {
        "name": "reminder_create",
        "description": "Buat reminder lokal. Selalu butuh konfirmasi sebelum dijadwalkan.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date": {"type": "STRING", "description": "YYYY-MM-DD"},
                "time": {"type": "STRING", "description": "HH:MM"},
                "message": {"type": "STRING", "description": "Isi reminder"},
            },
            "required": ["date", "time", "message"],
        },
    },
    {
        "name": "system_reflex",
        "description": "Aksi cepat native untuk volume atau Wi-Fi. Aksi Wi-Fi selalu butuh konfirmasi.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "volume_up | volume_down | volume_mute | wifi_on | wifi_off"}
            },
            "required": ["action"],
        },
    },
    {
        "name": "message_send",
        "description": (
            "Kirim satu pesan native melalui WhatsApp allowlist atau Telegram chat "
            "ID allowlist. Selalu tunggu konfirmasi user sebelum mengirim."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "platform": {"type": "STRING", "description": "whatsapp | telegram"},
                "recipient": {"type": "STRING", "description": "Kontak allowlist atau chat ID"},
                "message": {"type": "STRING", "description": "Isi pesan"},
            },
            "required": ["platform", "recipient", "message"],
        },
    },
    {
        "name": "camera_close",
        "description": (
            "Tutup panel kamera live Jarvis. Ini hanya lifecycle UI: tidak "
            "mengambil frame, tidak mengunggah gambar, dan tidak menganalisis visual."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "capability_status",
        "description": (
            "Baca status kemampuan native Jarvis, provider, dan integrasi. "
            "Read-only; tidak membuka kamera atau mengendalikan desktop."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "browser_media",
        "description": (
            "Kontrol video/media yang sedang aktif di browser agent. Gunakan "
            "langsung untuk pause/play/toggle, mute/unmute, volume, atau "
            "melewati iklan YouTube. Jangan mengaku berhasil sebelum hasil "
            "tool menyatakan sukses."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": (
                        "status | play | pause | toggle | mute | unmute | "
                        "volume_up | volume_down | set_volume | skip_ad"
                    ),
                },
                "volume": {
                    "type": "NUMBER",
                    "description": "0.0-1.0, hanya untuk set_volume",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "browser_tabs",
        "description": "Daftar tab browser agent dan index-nya.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "browser_new_tab",
        "description": "Buat tab baru di browser agent.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {"type": "STRING", "description": "URL atau about:blank"}
            },
        },
    },
    {
        "name": "browser_switch_tab",
        "description": "Pindah ke tab browser agent berdasarkan index.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "index": {"type": "INTEGER", "description": "Index 0-based"}
            },
            "required": ["index"],
        },
    },
    {
        "name": "browser_close_tab",
        "description": (
            "Tutup tab browser agent. Pakai index -1 untuk tab aktif."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "index": {
                    "type": "INTEGER",
                    "description": "-1 tab aktif, atau index dari browser_tabs",
                }
            },
        },
    },
    {
        "name": "whatsapp_hangup",
        "description": "Akhiri panggilan WhatsApp yang sedang aktif.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "whatsapp_status",
        "description": "Baca status WhatsApp Web dan audio panggilan.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "voice_briefing",
        "description": (
            "Bacakan briefing read-only yang sudah dibatasi: agenda Calendar, "
            "jumlah email aman, dan ringkasan monitor bila tersedia."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
]

_RULES = """

[KONTROL NATIVE CEPAT]
- Buka aplikasi desktop -> open_app. Tutup aplikasi desktop bernama -> close_app.
- Cari fakta/berita web -> web_search; jangan membuka browser hanya untuk pencarian.
- Buka URL -> browser_navigate, lalu browser_snapshot sebelum menilai isi halaman.
- Cari video YouTube -> youtube_search, lalu browser_snapshot; play hanya setelah bukti target dan browser_media sukses.
- Baca/cari/daftar file -> file_read/file_search/file_list. Jangan panggil file_processor untuk operasi umum.
- Cari memori -> memory_search. file_write dan memory_write tidak tersedia di voice native cepat; pekerjaan tulis harus lewat agent native dan policy/konfirmasi.
- Cuaca -> weather_lookup. Reminder -> reminder_create dan selalu minta konfirmasi.
- Volume -> system_reflex. Wi-Fi -> system_reflex dan selalu minta konfirmasi.
- Kirim pesan -> message_send. WhatsApp memakai kontak allowlist; Telegram memakai chat ID allowlist. Selalu minta konfirmasi sebelum delivery.
- Menutup panel kamera -> camera_close; cek kesiapan native -> capability_status. Keduanya tidak capture/upload frame.
- Jangan panggil camera_open, vision_analyze, send_message legacy, computer_control, atau screen_process dari jalur cepat sampai safety gate terkait selesai.
- Jangan mengaku berhasil sebelum hasil tool menyatakan sukses.
- Pause/play/volume/skip iklan pada video aktif -> browser_media.
- Tutup/pindah/daftar tab browser agent -> browser_close_tab,
  browser_switch_tab, atau browser_tabs.
- Akhiri panggilan WhatsApp aktif -> whatsapp_hangup.
- Hanya saat user eksplisit meminta “bacakan briefing” atau “briefing pagi” -> voice_briefing. Jangan membacakan raw tool dump atau isi email sensitif.
- Panggilan keluar, kirim pesan, riset, scraping, dan pekerjaan multi-langkah
  tetap dialihkan ke agent native; jangan menggantinya dengan web_search.
"""


def declarations() -> list[dict]:
    return [dict(item) for item in _DECLARATIONS]


def install(legacy_module) -> None:
    current = [
        item for item in legacy_module.TOOL_DECLARATIONS
        if item.get("name") not in (_TOOL_NAMES | _REPLACED_LEGACY_NAMES)
    ]
    legacy_module.TOOL_DECLARATIONS[:] = [*current, *declarations()]

    original_prompt = getattr(legacy_module, "_load_system_prompt", None)
    if original_prompt is not None and not getattr(
            original_prompt, "_jarvis_native_tools", False):
        def _with_rules() -> str:
            base = original_prompt()
            return base if "[KONTROL NATIVE CEPAT]" in base else base + _RULES

        _with_rules._jarvis_native_tools = True
        legacy_module._load_system_prompt = _with_rules

    cls = legacy_module.JarvisLive
    original_exec = cls._execute_tool
    if getattr(original_exec, "_jarvis_native_tools", False):
        return

    async def wrapped_exec(self, fc):
        name = str(getattr(fc, "name", ""))
        if name not in _TOOL_NAMES:
            return await original_exec(self, fc)

        from jarvis.agent import registry
        from jarvis.agent.base import ToolResult

        args = dict(getattr(fc, "args", None) or {})
        session = SimpleNamespace(id="voice-native-direct")
        adapter = None
        if name == "message_send":
            # Outbound messaging uses exact native tool execution.  The UI
            # adapter supplies the mandatory confirmation; no LLM re-planning
            # can substitute or bypass its selected platform/recipient.
            from jarvis.agent.adapters.ui import UIAdapter
            adapter = UIAdapter(getattr(self.ui, "_win", self.ui))
        try:
            try:
                result = await registry.execute(
                    name, args, adapter=adapter, session=session
                )
            except Exception as exc:  # registry contract is fail-closed
                result = ToolResult.fail(
                    f"{name} gagal: {type(exc).__name__}"
                )
        finally:
            if name.startswith("browser_"):
                try:
                    from jarvis.agent.tools.browser import release_browser_session
                    release_browser_session(session.id)
                except Exception:
                    pass
        return legacy_module.types.FunctionResponse(
            id=fc.id,
            name=name,
            response={
                "result": result.for_llm(),
                "ok": result.ok,
                "error": result.error or "",
            },
        )

    wrapped_exec._jarvis_native_tools = True
    cls._execute_tool = wrapped_exec


__all__ = ["declarations", "install"]
