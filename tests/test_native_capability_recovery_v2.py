"""Regression contracts for the native capability recovery."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace


def test_router_recognizes_call_without_requiring_platform_word():
    from jarvis.agent.router import Tier, classify

    route = classify(
        "Jarvis, telepon Honbrew dan bilang aku segera menjemput",
        {"source": "voice"},
    )
    assert route.tier is Tier.AGENT
    assert "WhatsApp" in route.reason


def test_router_keeps_single_media_and_tab_controls_low_latency():
    from jarvis.agent.router import Tier, classify

    assert classify("pause video YouTube", {}).tier is Tier.SINGLE
    assert classify("kecilkan volume video", {}).tier is Tier.SINGLE
    assert classify("skip iklan", {}).tier is Tier.SINGLE
    assert classify("tutup tab browser", {}).tier is Tier.SINGLE


def test_voice_lane_exposes_native_media_tab_and_hangup_tools():
    from jarvis.integrations.voice_native_tools import declarations

    names = {item["name"] for item in declarations()}
    assert {
        "browser_media",
        "browser_tabs",
        "browser_close_tab",
        "whatsapp_hangup",
    } <= names


def test_mcp_capability_remains_visible_without_servers(monkeypatch):
    from jarvis.agent.tools import mcp_tools
    from jarvis.agent import mcp_client

    monkeypatch.setattr(mcp_client, "statuses", lambda probe=False: [])
    assert mcp_tools.available() is True
    result = asyncio.run(mcp_tools.McpList().run())
    assert result.ok
    assert "tidak ada server" in result.content


def test_prompt_save_sanitizes_name_and_writes_markdown(tmp_path, monkeypatch):
    from jarvis.agent.tools import prompt_files

    monkeypatch.setattr(prompt_files, "prompt_dir", lambda: tmp_path)
    result = asyncio.run(prompt_files.PromptSave().run(
        name="../../Prompt Kamera Jarvis",
        content="Anda adalah pengamat kamera.",
    ))
    assert result.ok
    path = tmp_path / "prompt-kamera-jarvis.md"
    assert path.read_text(encoding="utf-8").strip() == (
        "Anda adalah pengamat kamera."
    )


def test_cua_bounds_reject_outside_coordinates_without_clicking():
    from jarvis.automation.cua_driver import NativeCUADriver, ScreenBounds

    driver = NativeCUADriver()
    driver.monitor = lambda _display=0: ScreenBounds(0, 0, 1920, 1080)
    assert driver.ensure_point(1919, 1079).width == 1920
    try:
        driver.ensure_point(1920, 1080)
    except ValueError as exc:
        assert "di luar desktop" in str(exc)
    else:
        raise AssertionError("coordinate guard did not reject outside point")


def test_browser_target_closed_detection_handles_playwright_message():
    from jarvis.agent.tools.browser import _is_target_closed

    error = RuntimeError(
        "Page.goto: Target page, context or browser has been closed"
    )
    assert _is_target_closed(error) is True


def test_local_executor_reports_real_worker_result(monkeypatch):
    from jarvis.core.action_registry import Action
    from jarvis.integrations import local_action_executor

    monkeypatch.setattr(
        local_action_executor,
        "_work",
        lambda _action: "WhatsApp ditutup.",
    )
    monkeypatch.setattr(
        local_action_executor.voice_notices,
        "remember_action",
        lambda _action: None,
    )
    result = asyncio.run(local_action_executor.submit(
        Action("app", "whatsapp", "close", {"app": "WhatsApp"})
    ))
    assert result == "WhatsApp ditutup."


def test_telegram_status_explains_release_gate(monkeypatch):
    from jarvis.integrations import telegram_control

    monkeypatch.setattr(telegram_control, "credentials_ready", lambda: True)
    monkeypatch.setattr(telegram_control, "token", lambda: "saved")
    monkeypatch.setattr(telegram_control, "allowed_ids", lambda: (42,))
    monkeypatch.setattr(telegram_control, "master_enabled", lambda: True)
    monkeypatch.setattr(
        telegram_control.release_controls,
        "current",
        lambda: {"gateway": False},
    )
    monkeypatch.setattr(
        "jarvis.agent.adapters.telegram.TelegramService.get",
        lambda: SimpleNamespace(running=False),
    )
    status = telegram_control.status()
    assert status["blocked_by"] == "gateway_release_control"
    assert status["gateway_enabled"] is False
