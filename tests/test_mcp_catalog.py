"""Framework maturity Phase 6 — MCP specs are allowlisted before spawn."""
from __future__ import annotations


def test_catalog_rejects_command_di_luar_allowlist():
    from jarvis.agent.mcp_catalog import validate_spec

    ok, reason = validate_spec({"name": "bad", "command": "powershell", "args": []},
                               allowed_commands={"python"})
    assert ok is False
    assert reason == "command_not_allowed"


def test_catalog_accepts_allowed_stdio_spec():
    from jarvis.agent.mcp_catalog import validate_spec

    ok, reason = validate_spec({"name": "echo", "command": "python", "args": ["server.py"]},
                               allowed_commands={"python"})
    assert ok is True
    assert reason == ""


def test_catalog_rejects_secret_like_argument():
    from jarvis.agent.mcp_catalog import validate_spec

    ok, reason = validate_spec({"name": "x", "command": "python", "args": ["--token=secret"]},
                               allowed_commands={"python"})
    assert ok is False
    assert reason == "secret_argument_denied"


def test_client_filter_mcp_spec_bila_allowlist_aktif(monkeypatch):
    from jarvis.agent import mcp_client
    from jarvis.core import config

    values = {
        "mcp.servers": [{"name": "bad", "command": "powershell", "args": []}],
        "mcp.allowed_commands": ["python"],
    }
    original = config.get
    monkeypatch.setattr(config, "get", lambda key, default=None: values.get(key, original(key, default)))

    assert mcp_client.server_specs() == []


def test_client_compat_bila_allowlist_belum_diatur(monkeypatch):
    from jarvis.agent import mcp_client
    from jarvis.core import config

    values = {
        "mcp.servers": [{"name": "legacy", "command": "node", "args": []}],
        "mcp.allowed_commands": [],
    }
    original = config.get
    monkeypatch.setattr(config, "get", lambda key, default=None: values.get(key, original(key, default)))

    assert mcp_client.server_specs() == [{"name": "legacy", "command": "node", "args": []}]
