"""WA0-live RED — metadata-only WhatsApp hardware readiness harness."""
from __future__ import annotations


_READY = {
    "state": "ready",
    "call_button_present": True,
}
_AUDIO = {
    "devices_distinct": True,
    "input_stream_ready": True,
    "output_stream_ready": True,
    "streams_exercised": True,
}
_LIVE = {
    "instance_present": True,
    "loop_running": True,
    "session_ready": True,
    "queues_ready": True,
}


def _run(**overrides):
    from jarvis.live.whatsapp_hardware_harness import run_hardware_check

    values = {
        "playwright_probe": lambda: True,
        "profile_probe": lambda: True,
        "web_probe": lambda: dict(_READY),
        "audio_probe": lambda: dict(_AUDIO),
        "gemini_probe": lambda: dict(_LIVE),
    }
    values.update(overrides)
    return run_hardware_check(**values)


def test_all_live_prerequisites_report_ready_with_bounded_metadata():
    result = _run()

    assert result == {
        "ok": True,
        "playwright_available": True,
        "profile_present": True,
        "web_state": "ready",
        "logged_in": True,
        "call_button_present": True,
        "audio_devices_distinct": True,
        "input_stream_ready": True,
        "output_stream_ready": True,
        "audio_streams_exercised": True,
        "gemini_instance_present": True,
        "gemini_loop_running": True,
        "gemini_session_ready": True,
        "gemini_queues_ready": True,
    }


def test_login_required_and_missing_call_button_fail_closed():
    result = _run(web_probe=lambda: {
        "state": "login_required",
        "call_button_present": False,
    })

    assert result["ok"] is False
    assert result["web_state"] == "login_required"
    assert result["logged_in"] is False
    assert result["call_button_present"] is False


def test_unknown_web_state_is_bounded_and_fails_closed():
    result = _run(web_probe=lambda: {
        "state": "unexpected-secret-state",
        "call_button_present": True,
        "url": "https://web.whatsapp.com/private",
        "selector": "button.secret",
    })

    assert result["ok"] is False
    assert result["web_state"] == "unknown"
    text = repr(result).casefold()
    assert "private" not in text
    assert "selector" not in text
    assert "url" not in text


def test_same_audio_device_or_unexercised_streams_fail_closed():
    result = _run(audio_probe=lambda: {
        "devices_distinct": False,
        "input_stream_ready": True,
        "output_stream_ready": True,
        "streams_exercised": False,
        "input_device": "secret device name",
    })

    assert result["ok"] is False
    assert result["audio_devices_distinct"] is False
    assert result["audio_streams_exercised"] is False
    assert "secret device name" not in repr(result)


def test_missing_gemini_session_or_queues_fail_closed():
    result = _run(gemini_probe=lambda: {
        "instance_present": True,
        "loop_running": True,
        "session_ready": False,
        "queues_ready": False,
    })

    assert result["ok"] is False
    assert result["gemini_session_ready"] is False
    assert result["gemini_queues_ready"] is False


def test_probe_exception_becomes_safe_false_metadata():
    def broken():
        raise RuntimeError("C:\\Users\\private\\token=secret")

    result = _run(profile_probe=broken, audio_probe=broken)

    assert result["ok"] is False
    assert result["profile_present"] is False
    assert result["input_stream_ready"] is False
    assert result["output_stream_ready"] is False
    assert "private" not in repr(result).casefold()
    assert "secret" not in repr(result).casefold()


def test_static_contract_has_no_call_click_or_remote_payload_leaks():
    from pathlib import Path

    source = Path("jarvis/live/whatsapp_hardware_harness.py").read_text(
        encoding="utf-8"
    ).casefold()
    assert ".click(" not in source
    assert ".fill(" not in source
    assert "start_call(" not in source
    assert "send_message(" not in source
    for forbidden in (
        "screenshot",
        "raw_html",
        "cookie",
        "header",
        "ocr",
        "coordinate",
    ):
        assert forbidden not in source
