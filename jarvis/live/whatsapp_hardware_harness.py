"""WA0-live metadata-only WhatsApp hardware readiness harness.

Probe browser hanya membaca state permukaan dan keberadaan kontrol panggilan.
Probe audio membuka lalu menutup dua stream konfigurasi tanpa mengirim payload.
Probe Gemini hanya membaca lifecycle instance. Semua exception menjadi metadata
False tanpa meneruskan detail lingkungan lokal.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

_ALLOWED_WEB_STATES = {
    "stopped",
    "loading",
    "login_required",
    "ready",
    "incoming_call",
    "in_call",
    "calling",
}
_LOGGED_IN_STATES = {"ready", "incoming_call", "in_call", "calling"}


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:
        return False
    return True


def _profile_present() -> bool:
    try:
        from jarvis.integrations.whatsapp_web import _profile_dir

        return Path(_profile_dir()).is_dir()
    except Exception:
        return False


def _web_surface_probe() -> dict[str, object]:
    from jarvis.integrations.whatsapp_web import (
        WhatsAppWebService,
        _CALL_SELECTORS,
        _first_visible,
    )

    service = WhatsAppWebService.get()

    def operation(page) -> dict[str, object]:
        status = service._status_on_page(page)
        return {
            "state": status.get("state", "unknown"),
            "call_button_present": (
                _first_visible(page, _CALL_SELECTORS) is not None
            ),
        }

    return dict(service._call(operation, timeout=15))


def _audio_stream_probe() -> dict[str, object]:
    from jarvis.core import config

    input_device = str(
        config.get(
            "whatsapp_web.audio_bridge.remote_input_device", ""
        )
        or ""
    ).strip()
    output_device = str(
        config.get(
            "whatsapp_web.audio_bridge.remote_output_device", ""
        )
        or ""
    ).strip()
    distinct = bool(
        input_device
        and output_device
        and input_device.casefold() != output_device.casefold()
    )
    result: dict[str, object] = {
        "devices_distinct": distinct,
        "input_stream_ready": False,
        "output_stream_ready": False,
        "streams_exercised": False,
    }
    if not distinct:
        return result

    try:
        import sounddevice as sd

        with sd.RawInputStream(
            device=input_device,
            samplerate=16000,
            channels=1,
            dtype="int16",
            blocksize=1600,
        ):
            result["input_stream_ready"] = True
            with sd.RawOutputStream(
                device=output_device,
                samplerate=24000,
                channels=1,
                dtype="int16",
                blocksize=1200,
            ):
                result["output_stream_ready"] = True
                result["streams_exercised"] = True
    except Exception:
        pass
    return result


def _gemini_live_probe() -> dict[str, object]:
    from jarvis.integrations.whatsapp_voice import _live

    instance = _live()
    if instance is None:
        return {
            "instance_present": False,
            "loop_running": False,
            "session_ready": False,
            "queues_ready": False,
        }
    loop = getattr(instance, "_loop", None)
    try:
        loop_running = bool(loop is not None and loop.is_running())
    except Exception:
        loop_running = False
    return {
        "instance_present": True,
        "loop_running": loop_running,
        "session_ready": getattr(instance, "session", None) is not None,
        "queues_ready": (
            getattr(instance, "out_queue", None) is not None
            and getattr(instance, "audio_in_queue", None) is not None
        ),
    }


def _bool_probe(probe: Callable[[], object]) -> bool:
    try:
        return probe() is True
    except Exception:
        return False


def _mapping_probe(probe: Callable[[], Mapping[str, Any]]) -> Mapping[str, Any]:
    try:
        value = probe()
    except Exception:
        return {}
    return value if isinstance(value, Mapping) else {}


def run_hardware_check(
    *,
    playwright_probe: Callable[[], object] = _playwright_available,
    profile_probe: Callable[[], object] = _profile_present,
    web_probe: Callable[[], Mapping[str, Any]] = _web_surface_probe,
    audio_probe: Callable[[], Mapping[str, Any]] = _audio_stream_probe,
    gemini_probe: Callable[[], Mapping[str, Any]] = _gemini_live_probe,
) -> dict[str, object]:
    """Run bounded readiness probes and return allowlisted metadata only."""

    playwright_available = _bool_probe(playwright_probe)
    profile_present = _bool_probe(profile_probe)
    web = _mapping_probe(web_probe)
    audio = _mapping_probe(audio_probe)
    gemini = _mapping_probe(gemini_probe)

    raw_state = str(web.get("state", "unknown") or "unknown").casefold()
    web_state = raw_state if raw_state in _ALLOWED_WEB_STATES else "unknown"
    result: dict[str, object] = {
        "ok": False,
        "playwright_available": playwright_available,
        "profile_present": profile_present,
        "web_state": web_state,
        "logged_in": web_state in _LOGGED_IN_STATES,
        "call_button_present": web.get("call_button_present") is True,
        "audio_devices_distinct": audio.get("devices_distinct") is True,
        "input_stream_ready": audio.get("input_stream_ready") is True,
        "output_stream_ready": audio.get("output_stream_ready") is True,
        "audio_streams_exercised": audio.get("streams_exercised") is True,
        "gemini_instance_present": gemini.get("instance_present") is True,
        "gemini_loop_running": gemini.get("loop_running") is True,
        "gemini_session_ready": gemini.get("session_ready") is True,
        "gemini_queues_ready": gemini.get("queues_ready") is True,
    }
    result["ok"] = all(
        value is True
        for key, value in result.items()
        if key not in {"ok", "web_state"}
    )
    return result


__all__ = ["run_hardware_check"]
