"""Low-latency native browser/media tools for the Gemini Live voice lane.

Conversation still belongs to the existing Gemini Live session.  This seam
only exposes deterministic controls that should not require a full agent
round-trip: current media, browser tabs, and ending an active WhatsApp call.
Complex browser work and outbound calls continue through the native agent.
"""
from __future__ import annotations

from types import SimpleNamespace

from jarvis.integrations import (
    google_voice,
    voice_clarify,
    voice_safety,
    voice_tasks,
)

_legacy = None

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
    "user_browser_tabs",
    "user_browser_media",
    "user_browser_status",
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
        "name": "user_browser_tabs",
        "description": (
            "Daftar tab yang sedang terbuka di Chrome MILIK USER. Pakai ini "
            "untuk tahu apa yang sedang user buka; browser_tabs hanya melihat "
            "browser agent yang terpisah."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "user_browser_media",
        "description": (
            "Pause/play/mute video atau audio yang sedang diputar di Chrome "
            "MILIK USER. Inilah yang dipakai untuk 'pause youtube'. Jarvis "
            "mencari sendiri tab yang memutar."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING",
                           "description": "status | play | pause | toggle | "
                                          "mute | unmute"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "user_browser_status",
        "description": (
            "Periksa apakah Jarvis bisa melihat Chrome milik user, berikut "
            "sebabnya bila tidak. Read-only."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
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
- Cari fakta/berita web -> web_search. Bila user meminta sumber/bukti
  ("sumbernya", "buktikan", "tunjukkan", "referensi"), web_search sendiri
  yang membuka satu tab sumber teratas di panel browser agent — jangan
  memanggil browser_navigate terpisah untuk itu. (§18: larangan lama
  "jangan membuka browser untuk pencarian" DICABUT atas permintaan
  eksplisit Takeda; jangan dikembalikan tanpa keputusan baru.)
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
- Video/musik yang sedang diputar USER di browsernya sendiri (mis. "pause
  youtube") -> user_browser_media. Tab yang sedang user buka -> user_browser_tabs.
  DUA BROWSER BERBEDA: browser_media/browser_tabs hanya melihat browser agent
  yang terisolasi, jadi memakainya untuk video user akan melaporkan "tidak ada
  media" padahal videonya jalan (§21).
- Pause/play/volume/skip iklan pada video di BROWSER AGENT -> browser_media.
- Tutup/pindah/daftar tab browser agent -> browser_close_tab,
  browser_switch_tab, atau browser_tabs.
- Akhiri panggilan WhatsApp aktif -> whatsapp_hangup.
- Hanya saat user eksplisit meminta “bacakan briefing” atau “briefing pagi” -> voice_briefing. Jangan membacakan raw tool dump atau isi email sensitif.
- Panggilan keluar, kirim pesan, riset, scraping, dan pekerjaan multi-langkah
  tetap dialihkan ke agent native; jangan menggantinya dengan web_search.
"""


def declarations() -> list[dict]:
    return [dict(item) for item in _DECLARATIONS]


def sync_google_declarations(legacy_module=None) -> None:
    """Refresh scope-gated Google declarations without installing a wrapper."""
    global _legacy
    if legacy_module is not None:
        _legacy = legacy_module
    if _legacy is None:
        return
    current = [
        item for item in _legacy.TOOL_DECLARATIONS
        if item.get("name") not in google_voice.GOOGLE_TOOL_NAMES
    ]
    _legacy.TOOL_DECLARATIONS[:] = [*current, *google_voice.declarations()]


def install(legacy_module) -> None:
    global _legacy
    _legacy = legacy_module
    replaced_names = (
        _TOOL_NAMES
        | _REPLACED_LEGACY_NAMES
        | voice_tasks.TASK_TOOL_NAMES
        | voice_clarify.CLARIFY_TOOL_NAMES
        | voice_safety.SAFETY_TOOL_NAMES
    )
    current = [
        item for item in legacy_module.TOOL_DECLARATIONS
        if item.get("name") not in replaced_names
    ]
    native_declarations = [
        item for item in declarations()
        if item.get("name") not in voice_safety.SAFETY_TOOL_NAMES
    ]
    legacy_module.TOOL_DECLARATIONS[:] = [
        *current,
        *voice_tasks.declarations(),
        *native_declarations,
        *voice_clarify.declarations(),
        *voice_safety.declarations(),
    ]

    voice_tasks.ensure_subscribed()

    original_prompt = getattr(legacy_module, "_load_system_prompt", None)
    if original_prompt is not None and not getattr(
            original_prompt, "_jarvis_native_tools", False):
        def _with_rules() -> str:
            base = voice_tasks.apply_to_prompt(original_prompt())
            if "[KONTROL NATIVE CEPAT]" not in base:
                base += _RULES
            base = voice_clarify.apply_to_prompt(base)
            return voice_safety.apply_to_prompt(base)

        _with_rules._jarvis_native_tools = True
        legacy_module._load_system_prompt = _with_rules

    cls = legacy_module.JarvisLive
    original_exec = cls._execute_tool
    if getattr(original_exec, "_jarvis_native_tools", False):
        return

    original_run = getattr(cls, "run", None)
    if original_run is not None:
        cls.run = voice_tasks.compose_run(original_run)

    async def wrapped_exec(self, fc):
        name = str(getattr(fc, "name", ""))
        handled_names = (
            voice_tasks.TASK_TOOL_NAMES
            | _TOOL_NAMES
            | google_voice.GOOGLE_TOOL_NAMES
            | voice_clarify.CLARIFY_TOOL_NAMES
            | voice_safety.SAFETY_TOOL_NAMES
        )
        if name not in handled_names:
            return await original_exec(self, fc)

        args = dict(getattr(fc, "args", None) or {})
        if name in voice_safety.SAFETY_TOOL_NAMES:
            if name == "shutdown_jarvis":
                message, ok = voice_safety.handle_shutdown(args, live=self)
            else:
                import asyncio
                message, ok = await asyncio.to_thread(
                    voice_safety.handle_close_app, args)
            return legacy_module.types.FunctionResponse(
                id=fc.id,
                name=name,
                response={"result": message, "ok": ok, "error": ""},
            )

        if name in voice_tasks.TASK_TOOL_NAMES:
            from jarvis.agent import registry

            result = await registry.execute(name, args)
            return legacy_module.types.FunctionResponse(
                id=fc.id,
                name=name,
                response={
                    "result": result.for_llm(),
                    "ok": result.ok,
                    "error": result.error or "",
                },
            )

        if name in voice_clarify.CLARIFY_TOOL_NAMES:
            return legacy_module.types.FunctionResponse(
                id=fc.id,
                name=name,
                response={
                    "result": voice_clarify.handle(args),
                    "ok": True,
                    "error": "",
                },
            )

        from jarvis.agent import registry

        if name in google_voice.GOOGLE_TOOL_NAMES:
            self.ui.set_state("THINKING")
            result = await registry.execute(name, args)
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return legacy_module.types.FunctionResponse(
                id=fc.id,
                name=name,
                response={
                    "result": result.for_llm(),
                    "ok": result.ok,
                    "error": result.error or "",
                },
            )

        from jarvis.agent.base import ToolResult

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


__all__ = [
    "declarations",
    "install",
    "sync_google_declarations",
]
