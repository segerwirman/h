"""Wrapper schema/dispatch Google untuk Gemini Live tanpa mengubah main.py.

Schema diambil dari registry nyata, sehingga toggle API dan scope benar-benar
menentukan tool yang terlihat pada sesi Live berikutnya.
"""
from __future__ import annotations

from typing import Any

_GOOGLE_NAMES = {
    "gcal_events", "gcal_create", "gcal_next",
    "yt_subscriptions", "yt_latest", "yt_search_data", "yt_my_stats",
    "gmail_list", "gmail_read", "gmail_send",
    "gdrive_search", "gdrive_read",
}
_legacy = None


def _gemini_schema(value: Any):
    if isinstance(value, list):
        return [_gemini_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    node = dict(value)
    variants = node.pop("anyOf", None)
    if variants:
        concrete = next((item for item in variants
                         if item.get("type") != "null"), variants[0])
        node.update(concrete)
    type_name = node.get("type")
    if isinstance(type_name, str):
        node["type"] = type_name.upper()
    node.pop("default", None)
    node.pop("$defs", None)
    return {key: _gemini_schema(item) for key, item in node.items()}


def declarations() -> list[dict]:
    from jarvis.agent import registry, toolgroups

    out = []
    disabled = sorted(toolgroups.disabled_tool_names())
    for schema in registry.schemas(allowed=sorted(_GOOGLE_NAMES),
                                   exclude=disabled):
        fn = schema.get("function") or {}
        if fn.get("name"):
            out.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": _gemini_schema(fn.get("parameters") or {
                    "type": "object", "properties": {}}),
            })
    return out


def sync_installed_declarations() -> None:
    if _legacy is None:
        return
    current = [item for item in _legacy.TOOL_DECLARATIONS
               if item.get("name") not in _GOOGLE_NAMES]
    _legacy.TOOL_DECLARATIONS[:] = [*current, *declarations()]


def install(legacy_module) -> None:
    """Pasang sekali pada modul root main yang sudah di-import READ/WRAP only."""
    global _legacy
    _legacy = legacy_module
    sync_installed_declarations()
    cls = legacy_module.JarvisLive
    original = cls._execute_tool
    if getattr(original, "_jarvis_google_wrapper", False):
        return

    async def wrapped(self, fc):
        if str(getattr(fc, "name", "")) not in _GOOGLE_NAMES:
            return await original(self, fc)
        from jarvis.agent import registry

        name = str(fc.name)
        args = dict(getattr(fc, "args", None) or {})
        self.ui.set_state("THINKING")
        result = await registry.execute(name, args)
        if not self.ui.muted:
            self.ui.set_state("LISTENING")
        return legacy_module.types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result.for_llm(), "ok": result.ok,
                      "error": result.error or ""},
        )

    wrapped._jarvis_google_wrapper = True
    cls._execute_tool = wrapped
