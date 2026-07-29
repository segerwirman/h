"""Low-latency native browser/media tools for the Gemini Live voice lane.

Conversation still belongs to the existing Gemini Live session.  This seam
only exposes deterministic controls that should not require a full agent
round-trip: current media, browser tabs, and ending an active WhatsApp call.
Complex browser work and outbound calls continue through the native agent.
"""
from __future__ import annotations

from types import SimpleNamespace

_TOOL_NAMES = frozenset({
    "browser_media",
    "browser_tabs",
    "browser_new_tab",
    "browser_switch_tab",
    "browser_close_tab",
    "whatsapp_hangup",
    "whatsapp_status",
})

_DECLARATIONS = [
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
]

_RULES = """

[KONTROL NATIVE CEPAT]
- Pause/play/volume/skip iklan pada video aktif -> browser_media.
- Tutup/pindah/daftar tab browser agent -> browser_close_tab,
  browser_switch_tab, atau browser_tabs.
- Akhiri panggilan WhatsApp aktif -> whatsapp_hangup.
- Panggilan keluar, kirim pesan, riset, scraping, dan pekerjaan multi-langkah
  tetap dialihkan ke agent native; jangan menggantinya dengan web_search.
"""


def declarations() -> list[dict]:
    return [dict(item) for item in _DECLARATIONS]


def install(legacy_module) -> None:
    current = [
        item for item in legacy_module.TOOL_DECLARATIONS
        if item.get("name") not in _TOOL_NAMES
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
        try:
            try:
                result = await registry.execute(name, args, session=session)
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
