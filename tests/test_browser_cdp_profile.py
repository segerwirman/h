"""Offline contracts for the Jarvis-owned Chrome CDP lane.

All Playwright, endpoint, and clock boundaries are faked here. These tests do
not launch Chrome, attach to the user's browser, or access the network.
"""
from __future__ import annotations

from pathlib import Path
import threading

import pytest

from jarvis.agent.tools import browser as B
from jarvis.browser.agent import BrowserAgent


class _FakeContext:
    def __init__(self):
        self.pages = []
        self.closed = 0

    def close(self):
        self.closed += 1


class _FakeChromium:
    def __init__(self, outer):
        self.outer = outer

    def launch_persistent_context(self, **kwargs):
        self.outer.calls.append(kwargs)
        return self.outer.context


class _FakePlaywright:
    def __init__(self):
        self.calls = []
        self.context = _FakeContext()
        self.chromium = _FakeChromium(self)


def _config(monkeypatch, values=None):
    values = values or {}
    defaults = {
        "agent.browser.cdp.enabled": True,
        "agent.browser.cdp.address": "127.0.0.1",
        "agent.browser.cdp.port": 9333,
        "agent.browser.cdp.user_data_dir": "",
        "agent.browser.cdp.startup_timeout_s": 0.2,
        "agent.browser.cdp.close_timeout_s": 0.2,
        "agent.browser.channel": "chrome",
        "agent.browser.user_data_dir": "",
        "agent.browser.profile_directory": "Profile 8",
        "browser.agent_cli.manage_owned_cdp": False,
    }
    defaults.update(values)
    monkeypatch.setattr(B.config, "get", lambda key, default=None:
                        defaults.get(key, default))
    return defaults


def test_default_profile_is_outside_repo_and_daily_chrome_tree(monkeypatch):
    _config(monkeypatch)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\tester\AppData\Local")
    path = Path(B._cdp_profile_dir())
    repo = Path(B.config.base_dir()).resolve()
    assert path.name == "ChromeCDPProfile"
    assert path.parent.name == "JARVIS"
    assert repo not in path.parents
    assert "Google" not in path.parts


@pytest.mark.parametrize("unsafe", [
    "Profile 8",
    "C:/Users/tester/AppData/Local/Google/Chrome/User Data",
])
def test_unsafe_profile_override_fails_closed(monkeypatch, unsafe):
    _config(monkeypatch, {"agent.browser.cdp.user_data_dir": unsafe})
    with pytest.raises(ValueError):
        B._cdp_profile_dir()


def test_repository_profile_override_fails_closed(monkeypatch):
    _config(monkeypatch, {"agent.browser.cdp.user_data_dir": str(
        B.config.base_dir() / "tmp-cdp")})
    with pytest.raises(ValueError, match="repository"):
        B._cdp_profile_dir()


def test_cdp_address_and_port_are_loopback_validated(monkeypatch):
    _config(monkeypatch, {"agent.browser.cdp.address": "0.0.0.0"})
    with pytest.raises(ValueError, match="127.0.0.1"):
        B._cdp_address()
    _config(monkeypatch, {"agent.browser.cdp.port": 80})
    with pytest.raises(ValueError, match="1024"):
        B._cdp_port()


def test_dedicated_launch_has_exact_loopback_args_and_no_user_profile_arg(
        monkeypatch):
    _config(monkeypatch)
    monkeypatch.setattr(B, "_cdp_probe", lambda *_args: None)
    pw = _FakePlaywright()
    context, browser = B._launch_browser(pw, headless=True, dedicated_cdp=True)
    assert context is pw.context
    assert browser is None
    args = pw.calls[0]["args"]
    assert "--remote-debugging-address=127.0.0.1" in args
    assert "--remote-debugging-port=9333" in args
    assert not any("profile-directory" in arg for arg in args)
    assert pw.calls[0]["user_data_dir"].replace("/", "\\").casefold().endswith(
        "jarvis\\chromecdpprofile"
    )


def test_readiness_probe_success_and_timeout_are_bounded(monkeypatch):
    _config(monkeypatch)
    probes = iter([None, {"Browser": "fake"}])
    monkeypatch.setattr(B, "_cdp_probe", lambda *_args: next(probes))
    assert B._wait_for_cdp(0.2) is True

    monkeypatch.setattr(B, "_cdp_probe", lambda *_args: None)
    assert B._wait_for_cdp(0.1) is False


def test_unknown_occupied_port_blocks_dedicated_launch(monkeypatch):
    _config(monkeypatch)
    monkeypatch.setattr(B, "_cdp_probe", lambda *_args: {"reachable": True})
    pw = _FakePlaywright()
    with pytest.raises(RuntimeError, match="dipakai"):
        B._launch_browser(pw, headless=True, dedicated_cdp=True)
    assert pw.calls == []


def test_concurrent_ensure_uses_one_host_start(monkeypatch):
    _config(monkeypatch)
    host = type("Host", (), {"_ensure": lambda self: None})()
    calls = []

    def get(cls):
        calls.append("get")
        return host

    monkeypatch.setattr(B._BrowserHost, "get", classmethod(get))
    monkeypatch.setattr(B, "browser_cdp_status", lambda: {
        "owned": True, "state": "accepting", "port": 9333,
        "ready": True, "tabs": 1, "reason": "",
    })
    results = []
    threads = [threading.Thread(target=lambda: results.append(
        B.ensure_browser_cdp())) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(calls) == 8
    assert all(result["ready"] for result in results)


def test_browser_agent_arbitrary_target_stays_attach_only(monkeypatch):
    _config(monkeypatch, {"browser.agent_cli.manage_owned_cdp": True})
    calls = []
    monkeypatch.setattr(BrowserAgent, "_run", lambda self, args: calls.append(args))
    agent = BrowserAgent(cdp="ws://external.test/devtools")
    assert agent._ensure_owned_cdp() is True
    assert calls == []


def test_status_is_aggregate_only(monkeypatch):
    _config(monkeypatch)
    host = type("Host", (), {
        "_dedicated_cdp": True,
        "_cdp_ready": True,
        "_cdp_owned": True,
        "_state": "accepting",
        "_fail": None,
        "_context": None,
    })()
    monkeypatch.setattr(B._BrowserHost, "peek", classmethod(lambda cls: host))
    result = B.browser_cdp_status()
    assert result == {
        "owned": True,
        "state": "accepting",
        "port": 9333,
        "ready": True,
        "tabs": 0,
        "reason": "",
    }
    assert not {"url", "title", "dom", "credentials"} & result.keys()


def test_close_dead_host_still_checks_endpoint_disappearance(monkeypatch):
    _config(monkeypatch)
    host = B._BrowserHost(dedicated_cdp=True)
    monkeypatch.setattr(B, "_wait_for_cdp_gone", lambda _timeout: False)
    with pytest.raises(TimeoutError, match="reachable"):
        host.close(timeout=0.1)
