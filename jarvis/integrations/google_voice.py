"""Helper deklarasi tool Google untuk Gemini Live tanpa mengubah main.py.

Schema diambil dari registry nyata, sehingga toggle API dan scope benar-benar
menentukan tool yang terlihat pada sesi Live berikutnya. Dispatch dimiliki oleh
``voice_native_tools`` agar hanya ada satu wrapper registry pada lane suara.
"""
from __future__ import annotations

from typing import Any

GOOGLE_TOOL_NAMES = frozenset({
    "gcal_events", "gcal_create", "gcal_next",
    "yt_subscriptions", "yt_latest", "yt_search_data", "yt_my_stats",
    "gmail_list", "gmail_read", "gmail_send",
    "gdrive_search", "gdrive_read",
})


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
    for schema in registry.schemas(allowed=sorted(GOOGLE_TOOL_NAMES),
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


__all__ = ["GOOGLE_TOOL_NAMES", "declarations"]
