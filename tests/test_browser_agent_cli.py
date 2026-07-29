"""BrowserAgent wraps the real vercel-labs/agent-browser CLI syntax.

Guards the exact argv built for snapshot/click/type/open and the --cdp attach,
so the wrapper stays matched to the installed CLI. subprocess is faked — no
real agent-browser process is spawned.
"""
from __future__ import annotations

import jarvis.browser.agent as mod


class _Result:
    def __init__(self, code=0, out="", err=""):
        self.returncode = code
        self.stdout = out
        self.stderr = err


def _capture(monkeypatch, result=None):
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return result or _Result(0, "@e1 [button] \"Submit\"")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    # pin executable resolution: on a dev machine with the CLI installed,
    # shutil.which returns the full …\agent-browser.CMD shim path, which
    # would make the argv assertions machine-dependent
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    return calls


def test_snapshot_attaches_cdp_and_returns_text(monkeypatch):
    calls = _capture(monkeypatch)
    a = mod.BrowserAgent(executable="agent-browser")
    a.attach("9333")
    tree = a.get_accessibility_tree()
    assert tree and "Submit" in tree
    assert calls[0] == ["agent-browser", "--cdp", "9333", "snapshot", "-i"]


def test_click_uses_ref(monkeypatch):
    calls = _capture(monkeypatch)
    a = mod.BrowserAgent(executable="agent-browser", cdp="9333")
    assert a.execute_action("click", target_id="@e2") is True
    assert calls[-1] == ["agent-browser", "--cdp", "9333", "click", "@e2"]


def test_type_passes_ref_and_text(monkeypatch):
    calls = _capture(monkeypatch)
    a = mod.BrowserAgent(executable="agent-browser", cdp="9333")
    a.execute_action("type", target_id="@e5", value="halo dunia")
    assert calls[-1] == ["agent-browser", "--cdp", "9333", "type", "@e5", "halo dunia"]


def test_navigate_uses_open(monkeypatch):
    calls = _capture(monkeypatch)
    a = mod.BrowserAgent(executable="agent-browser", cdp="9333")
    a.navigate("https://x.com")
    assert calls[-1] == ["agent-browser", "--cdp", "9333", "open", "https://x.com"]


def test_no_cdp_omits_flag(monkeypatch):
    calls = _capture(monkeypatch)
    a = mod.BrowserAgent(executable="agent-browser", cdp=None)
    a.get_accessibility_tree()
    assert calls[0] == ["agent-browser", "snapshot", "-i"]


def test_missing_cli_returns_none(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError()
    monkeypatch.setattr(mod.subprocess, "run", boom)
    a = mod.BrowserAgent(executable="agent-browser", cdp="9333")
    assert a.get_accessibility_tree() is None
    assert a.execute_action("click", target_id="@e1") is False


def test_nonzero_exit_is_failure(monkeypatch):
    _capture(monkeypatch, result=_Result(1, "", "boom"))
    a = mod.BrowserAgent(executable="agent-browser", cdp="9333")
    assert a.get_accessibility_tree() is None
    assert a.execute_action("click", target_id="@e1") is False
