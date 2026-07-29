"""Native T0/T1 executor for allowlisted Telegram ingress.

The public tier router remains the single source of the lane decision.  This
module only performs one deterministic action/tool call and never invokes the
agent loop, so the Telegram adapter has the same routing contract as UI/voice.
"""
from __future__ import annotations

import asyncio
import re
import webbrowser
from datetime import datetime

from jarvis.agent.base import ToolResult
from jarvis.agent.router import Route, Tier
from jarvis.core import config


async def execute(text: str, route: Route, *, context=None) -> ToolResult:
    if route.tier is Tier.REFLEX:
        if getattr(context, "surface", "") == "remote":
            return ToolResult.fail(
                "Aksi kontrol desktop tidak dijalankan dari Telegram."
            )
        return await _reflex(text)
    if route.tier is Tier.SINGLE:
        return await _single(text, route, context=context)
    return ToolResult.fail("Executor ringan hanya menerima tier T0/T1.")


async def _reflex(text: str) -> ToolResult:
    from jarvis.core.router import Intent, IntentRouter

    router = IntentRouter()
    router._llm_fallback = False  # lane sudah diputuskan router tier publik
    intent = await asyncio.to_thread(router.classify, text)
    if intent.intent is Intent.OPEN_APP:
        from actions.open_app import open_app
        result = await asyncio.to_thread(
            open_app, {"app_name": str(intent.slots.get("app", ""))})
        lowered = result.lower()
        if "failed" in lowered or "could not" in lowered:
            return ToolResult.fail(result)
        return ToolResult.success(result, display=result)
    if intent.intent is Intent.SYSTEM:
        return await _system_action(intent.slots)

    normalized = " ".join(text.lower().split())
    if re.search(r"\b(?:fullscreen|full screen|layar penuh)\b", normalized):
        return await _call_computer_setting("full_screen", "Mode layar penuh diubah.")
    if re.search(r"\b(?:tekan|press)\s+esc(?:ape)?\b", normalized):
        return await _call_computer_setting("press_escape", "Tombol Escape ditekan.")
    return ToolResult.fail(
        "Perintah reflex dikenali, tetapi belum memiliki aksi native yang aman."
    )


async def _system_action(slots: dict) -> ToolResult:
    action = str(slots.get("action", ""))
    mapping = {
        "volume_up": ("volume_up", "Volume dinaikkan."),
        "volume_down": ("volume_down", "Volume diturunkan."),
        "volume_mute": ("volume_mute", "Mute audio diubah."),
    }
    if action == "volume_set":
        try:
            value = max(0, min(100, int(slots.get("value", 0))))
        except (TypeError, ValueError):
            return ToolResult.fail("Nilai volume tidak valid.")
        return await _call_computer_setting(
            "volume_set", f"Volume diatur ke {value}%.", value)
    if action == "brightness":
        # Implementasi legacy hanya menyediakan increment/decrement; jangan
        # mengarang operasi set absolut yang tidak ada.
        return ToolResult.fail(
            "Kontrol kecerahan absolut belum tersedia pada aksi native Jarvis."
        )
    if action in mapping:
        function, message = mapping[action]
        return await _call_computer_setting(function, message)
    return ToolResult.fail(
        "Aksi sistem ini membutuhkan konteks UI lokal dan tidak dijalankan dari Telegram."
    )


async def _call_computer_setting(function: str, message: str,
                                 *args) -> ToolResult:
    try:
        from actions import computer_settings
        target = getattr(computer_settings, function)
        await asyncio.to_thread(target, *args)
        return ToolResult.success(message, display=message)
    except Exception as exc:  # noqa: BLE001
        return ToolResult.fail(
            f"Aksi sistem gagal ({type(exc).__name__})."
        )


async def _single(text: str, route: Route, *, context=None) -> ToolResult:
    from jarvis.agent.router import extract_image_prompt

    image_prompt = extract_image_prompt(text)
    if image_prompt:
        return await _tool("image_generate", {"prompt": image_prompt},
                           context=context)

    google = await _google_direct(text, context=context)
    if google is not None:
        return google

    normalized = " ".join(text.lower().split())
    if re.search(r"\b(?:jam berapa|what time|tanggal berapa|hari apa)\b",
                 normalized):
        now = datetime.now().astimezone()
        value = now.strftime("%A, %d %B %Y — %H:%M %Z")
        return ToolResult.success(value, display=value)

    if route.reason == "single time or weather query" or re.search(
            r"\b(?:cuaca|weather|prakiraan)\b", normalized):
        return await _tool("web_search", {
            "query": text, "max_results": 4, "mode": "text"}, context=context)

    song = re.match(
        r"^(?:tolong\s+)?(?:putar|puterin|play)\s+(?:lagu|musik|song)\s+(.+)$",
        text.strip(), re.IGNORECASE)
    if song:
        found = await _tool("spotify_search", {
            "query": song.group(1).strip(), "type": "track"}, context=context)
        if not found.ok:
            return found
        uri = re.search(r"\[(spotify:track:[^\]]+)\]", found.for_llm())
        if uri is None:
            return ToolResult.fail("Lagu tidak ditemukan di Spotify.")
        played = await _tool("spotify_play", {"uri": uri.group(1)}, context=context)
        if played.ok:
            return ToolResult.success(
                f"Memutar {song.group(1).strip()} di Spotify.")
        return played

    if route.reason in {
        "greeting or conversational reflex",
        "single factual or explanatory question",
        "single conversational turn",
    }:
        return await _one_turn_answer(text)

    from jarvis.core.router import Intent, IntentRouter
    router = IntentRouter()
    router._llm_fallback = False  # hindari classifier kedua/network terselubung
    intent = await asyncio.to_thread(router.classify, text)
    if intent.intent is Intent.SEARCH_WEB or route.reason == "single search query":
        query = str(intent.slots.get("query") or text).strip()
        return await _tool("web_search", {"query": query, "max_results": 6},
                           context=context)
    if intent.intent in (Intent.OPEN_URL, Intent.OPEN_BROWSER_AGENT):
        if getattr(context, "surface", "") == "remote":
            return ToolResult.fail(
                "Aksi kontrol desktop tidak dijalankan dari Telegram."
            )
        url = str(intent.slots.get("url") or
                  config.get("router.known_sites.google",
                             "https://www.google.com"))
        opened = await asyncio.to_thread(webbrowser.open, url)
        if opened:
            return ToolResult.success(f"Membuka {url}")
        return ToolResult.fail("Browser sistem tidak mengonfirmasi URL terbuka.")

    if route.reason in {"single messaging action", "single in-frame UI action"}:
        return ToolResult.fail(
            "Perintah ini membutuhkan target/konteks UI yang tidak tersedia dari Telegram."
        )

    return await _one_turn_answer(text)


async def _one_turn_answer(text: str) -> ToolResult:
    from jarvis.agent import model_routing
    client = model_routing.light_client()
    answer = await asyncio.to_thread(
        client.generate,
        text,
        system=(
            "Anda adalah Jarvis. Jawab langsung, ringkas, dan dalam bahasa "
            "pengguna. Ini satu giliran tanpa tool; jangan mengaku telah "
            "menjalankan aksi eksternal."
        ),
    )
    if not answer:
        return ToolResult.fail(
            "Model jalur ringan belum tersedia. Periksa API key provider ringan."
        )
    return ToolResult.success(answer)


async def _google_direct(text: str, *, context=None) -> ToolResult | None:
    from jarvis.integrations import google_direct
    call = google_direct.match_command(text)
    if call is None:
        return None
    name, args = call
    if not google_direct.enabled_by_tool_group(name):
        return ToolResult.fail(google_direct.unavailable_message(name))
    from jarvis.agent import registry
    if registry.get(name) is None:
        return ToolResult.fail(google_direct.unavailable_message(name))
    return await registry.execute(name, args, context=context)


async def _tool(name: str, args: dict, *, context=None) -> ToolResult:
    from jarvis.agent import registry
    if registry.get(name) is None:
        return ToolResult.fail(
            f"Tool {name} belum tersedia atau belum dikonfigurasi."
        )
    return await registry.execute(name, args, context=context)
