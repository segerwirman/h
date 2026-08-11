"""MK50 Phase 1: the deprecated Hermes runtime is inert by default."""
from __future__ import annotations

import actions.hermes_action as action_module
import pytest

from jarvis.core import boot, config
from jarvis.integrations.hermes import async_dispatch
from jarvis.integrations.hermes import bridge as bridge_module
from jarvis.integrations.hermes import messaging_service
from jarvis.integrations.hermes.bridge import HermesBridge
from jarvis.agent import skill_hub


@pytest.fixture(autouse=True)
def _fresh_bridge():
    HermesBridge._reset_for_tests()
    yield
    HermesBridge._reset_for_tests()


def _disabled_get(monkeypatch) -> None:
    real_get = config.get

    def _get(path, default=None):
        if path == "hermes.enabled":
            return False
        return real_get(path, default)

    monkeypatch.setattr(config, "get", _get)


def test_config_and_missing_config_default_to_disabled(monkeypatch):
    assert config.get("hermes.enabled", False) is False
    assert bridge_module.is_enabled() is False

    monkeypatch.setattr(config, "get", lambda _path, default=None: default)
    assert bridge_module.is_enabled() is False


def test_reference_repo_is_not_a_runtime_skill_source(monkeypatch):
    assert config.get("skills.hub_sources") == []
    monkeypatch.setattr(config, "get", lambda _path, default=None: default)
    assert skill_hub.hub_sources() == []
    assert skill_hub._DEFAULT_SOURCES == ()


def test_bridge_never_resolves_or_runs_cli_while_disabled(monkeypatch):
    _disabled_get(monkeypatch)

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("disabled Hermes bridge touched the CLI")

    monkeypatch.setattr(bridge_module.shutil, "which", _unexpected)
    monkeypatch.setattr(bridge_module.subprocess, "run", _unexpected)

    bridge = HermesBridge.get()
    bridge._resolved = "hermes"  # stale cache must not bypass the flag

    assert bridge.available() is False
    assert bridge._exe() is None
    for result in (
        bridge.send_direct("telegram", "halo"),
        bridge.run_task("riset"),
        bridge.config_set("KEY", "value"),
        bridge.gateway_command("status"),
    ):
        assert result["ok"] is False
        assert "dinonaktifkan" in result["error"].lower()
    assert bridge.list_targets() == []
    assert bridge.check()["ok"] is False
    assert "dinonaktifkan" in bridge.check()["detail"].lower()


@pytest.mark.parametrize("mode", ["status", "send", "task"])
def test_action_fails_fast_before_bridge_or_dispatch(monkeypatch, mode):
    monkeypatch.setattr(action_module, "is_enabled", lambda: False)

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("disabled action reached a Hermes runtime entry")

    monkeypatch.setattr(action_module.HermesBridge, "get",
                        classmethod(_unexpected))
    monkeypatch.setattr(action_module, "dispatch_async", _unexpected)

    out = action_module.hermes_action({
        "mode": mode,
        "task": "riset",
        "target": "telegram",
        "text": "halo",
    })
    assert "dinonaktifkan" in out.lower()
    assert "agent native jarvis" in out.lower()


def test_async_dispatch_does_not_create_bridge_or_thread(monkeypatch):
    monkeypatch.setattr(async_dispatch, "is_enabled", lambda: False)

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("disabled dispatcher started Hermes work")

    monkeypatch.setattr(async_dispatch.HermesBridge, "get",
                        classmethod(_unexpected))
    monkeypatch.setattr(async_dispatch.threading, "Thread", _unexpected)
    assert async_dispatch.dispatch_async("riset") is False
    assert async_dispatch.active_count() == 0


def test_boot_check_reports_expected_disabled_state(monkeypatch):
    monkeypatch.setattr(bridge_module, "is_enabled", lambda: False)

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("boot probed disabled Hermes CLI")

    monkeypatch.setattr(HermesBridge, "get", classmethod(_unexpected))
    result = boot._check_hermes()
    assert result.ok is True
    assert result.degraded is False
    assert "disabled" in result.detail.lower()


def test_messaging_mutations_are_inert_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(messaging_service, "is_enabled", lambda: False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("disabled messaging reached Hermes bridge")

    monkeypatch.setattr(messaging_service.HermesBridge, "get",
                        classmethod(_unexpected))
    env_path = tmp_path / ".env"
    original = "TELEGRAM_BOT_TOKEN=do-not-touch\n"
    env_path.write_text(original, encoding="utf-8")

    calls = (
        messaging_service.set_env("TELEGRAM_BOT_TOKEN", "new"),
        messaging_service.clear_env("TELEGRAM_BOT_TOKEN"),
        messaging_service.set_enabled("telegram", True),
        messaging_service.restart_gateway(),
    )
    assert all(ok is False and "dinonaktifkan" in message.lower()
               for ok, message in calls)
    assert env_path.read_text(encoding="utf-8") == original


def test_messaging_status_does_not_read_hermes_home_when_disabled(monkeypatch):
    monkeypatch.setattr(messaging_service, "is_enabled", lambda: False)

    def _unexpected(*_args, **_kwargs):
        raise AssertionError("disabled messaging read ~/.hermes runtime state")

    monkeypatch.setattr(messaging_service, "read_env", _unexpected)
    monkeypatch.setattr(messaging_service, "read_platforms_config", _unexpected)
    monkeypatch.setattr(messaging_service, "read_runtime", _unexpected)

    platforms = messaging_service.list_platforms()
    assert platforms
    assert all(item["state"] == "disabled" for item in platforms)
    assert all(item["enabled"] is False for item in platforms)
    assert all(
        field["is_set"] is False and field["redacted"] == ""
        for item in platforms for field in item["fields"]
    )
