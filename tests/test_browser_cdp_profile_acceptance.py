"""P3-A offline acceptance for the dedicated Jarvis CDP profile."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from jarvis.agent.tools import browser
from jarvis.browser.agent import BrowserAgent
from jarvis.integrations import user_browser


def _config(monkeypatch, values: dict):
    monkeypatch.setattr(browser.config, "get",
                        lambda key, default=None: values.get(key, default))
    monkeypatch.setattr(browser.config, "base_dir",
                        lambda: str(Path.cwd()))


def test_dedicated_defaults_are_loopback_9333_and_isolated(monkeypatch, tmp_path):
    _config(monkeypatch, {})
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    assert browser._cdp_enabled() is True
    assert browser._cdp_address() == "127.0.0.1"
    assert browser._cdp_port() == 9333
    profile = Path(browser._cdp_profile_dir())
    assert profile == tmp_path / "local" / "JARVIS" / "ChromeCDPProfile"
    assert Path.cwd() not in profile.parents
    assert "Chrome" not in profile.parts
    assert "Profile 8" not in str(profile)


def test_unsafe_profile_paths_and_non_loopback_config_fail_closed(monkeypatch,
                                                                    tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    _config(monkeypatch, {"agent.browser.cdp.address": "0.0.0.0"})
    with pytest.raises(ValueError, match="127.0.0.1"):
        browser._cdp_address()

    unsafe_paths = (
        (str(repo / "profile"), repo),
        (str(tmp_path / "local" / "Google" / "Chrome" / "User Data"),
         tmp_path / "repo"),
        (str(tmp_path / "other" / "Profile 8"), tmp_path / "repo"),
    )
    for unsafe, base_dir in unsafe_paths:
        _config(monkeypatch, {"agent.browser.cdp.user_data_dir": unsafe})
        monkeypatch.setattr(browser.config, "base_dir", lambda: str(base_dir))
        with pytest.raises(ValueError):
            browser._cdp_profile_dir()


def test_fake_launch_receives_dedicated_loopback_arguments_without_user_profile(
        monkeypatch, tmp_path):
    values = {
        "agent.browser.cdp.enabled": True,
        "agent.browser.cdp.address": "127.0.0.1",
        "agent.browser.cdp.port": 9333,
        "agent.browser.cdp.user_data_dir": str(tmp_path / "cdp-profile"),
        "agent.browser.channel": "chrome",
        "agent.browser.profile_directory": "Profile 8",
    }
    _config(monkeypatch, values)
    monkeypatch.setattr(browser, "_cdp_probe", lambda *_args: None)
    calls: list[dict] = []

    class Chromium:
        def launch_persistent_context(self, **kwargs):
            calls.append(kwargs)
            return "fake-context"

    class Playwright:
        chromium = Chromium()

    context, browser_process = browser._launch_browser(
        Playwright(), True, dedicated_cdp=True
    )
    assert context == "fake-context"
    assert browser_process is None
    assert calls[0]["user_data_dir"] == str(tmp_path / "cdp-profile")
    assert "--remote-debugging-address=127.0.0.1" in calls[0]["args"]
    assert "--remote-debugging-port=9333" in calls[0]["args"]
    assert not any(arg.startswith("--profile-directory=")
                    for arg in calls[0]["args"])


def test_aggregate_status_never_contains_page_metadata(monkeypatch):
    _config(monkeypatch, {"agent.browser.cdp.port": 9333})
    monkeypatch.setattr(browser._BrowserHost, "peek", classmethod(lambda cls: None))

    status = browser.browser_cdp_status()
    assert status == {
        "owned": False,
        "state": "stopped",
        "port": 9333,
        "ready": False,
        "tabs": 0,
        "reason": "dedicated CDP belum dimulai",
    }
    forbidden = ("url", "title", "dom", "token", "cookie", "local state")
    assert not any(key in str(status).casefold() for key in forbidden)


def test_user_browser_lane_remains_attach_only_and_uses_9222(monkeypatch):
    _config(monkeypatch, {"user_browser.debug_port": 9222})
    assert user_browser.debug_port() == 9222
    assert "remote-debugging-port=9222" in user_browser._unreachable_reason(None)
    assert "Chrome yang sudah berjalan tidak bisa disambungkan belakangan" \
        in user_browser._unreachable_reason(None)


def test_browser_agent_arbitrary_cdp_target_stays_attach_only(monkeypatch):
    values = {
        "browser.agent_cli.executable": "agent-browser",
        "browser.agent_cli.cdp_flag": "--cdp",
        "browser.agent_cli.manage_owned_cdp": True,
    }
    _config(monkeypatch, values)
    agent = BrowserAgent(cdp="ws://127.0.0.1:9999")
    ensured: list[bool] = []
    monkeypatch.setattr(agent, "_ensure_owned_cdp",
                        lambda: ensured.append(True) or True)
    monkeypatch.setattr(agent, "_resolve_executable", lambda: "fake-agent-browser")
    assert agent._base() == ["fake-agent-browser", "--cdp", "ws://127.0.0.1:9999"]
    assert agent._ensure_owned_cdp() is True
    assert ensured == [True]


def test_fake_readiness_ownership_timeout_and_bounded_close_seams(monkeypatch):
    calls: list[tuple] = []
    probes = iter([None, {"Browser": "owned"}])
    monkeypatch.setattr(browser, "_cdp_probe", lambda *args: next(probes))
    clock = iter([0.0, 0.2, 0.25, 0.4, 0.45, 0.6])
    monkeypatch.setattr(browser.time, "monotonic", clock.__next__)
    monkeypatch.setattr(browser.time, "sleep", lambda _value: None)
    assert browser._wait_for_cdp(timeout_s=1.0) is True
    assert calls == []

    occupied = {"reachable": True}
    monkeypatch.setattr(browser, "_cdp_probe", lambda *_args: occupied)
    class Chromium:
        def launch_persistent_context(self, **_kwargs):
            raise AssertionError("occupied port must prevent launch")
    class Playwright:
        chromium = Chromium()
    monkeypatch.setattr(browser, "_cdp_profile_dir", lambda: "C:/safe/cdp")
    monkeypatch.setattr(browser, "_cdp_address", lambda: "127.0.0.1")
    monkeypatch.setattr(browser, "_cdp_port", lambda: 9333)
    with pytest.raises(RuntimeError, match="sudah dipakai"):
        browser._launch_browser(Playwright(), True, dedicated_cdp=True)


def test_concurrent_owned_cdp_facade_serializes_fake_ensure(monkeypatch):
    from jarvis.integrations import jarvis_browser_cdp

    entered = threading.Event()
    release = threading.Event()
    results: list[dict] = []

    def fake_ensure():
        entered.set()
        release.wait(timeout=2)
        return {"owned": True, "ready": True, "state": "accepting",
                "port": 9333, "tabs": 0, "reason": ""}

    monkeypatch.setattr(jarvis_browser_cdp.browser, "ensure_browser_cdp",
                        fake_ensure)
    threads = [threading.Thread(
        target=lambda: results.append(jarvis_browser_cdp.ensure()))
        for _ in range(2)]
    for thread in threads:
        thread.start()
    assert entered.wait(timeout=2) is True
    release.set()
    for thread in threads:
        thread.join(timeout=2)
    assert len(results) == 2
    assert all(result["owned"] and result["ready"] for result in results)
