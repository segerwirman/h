"""§5.7 — klien MCP stdio (server echo nyata di subprocess) + Browse Hub."""
from __future__ import annotations

import json
import sys
import textwrap

import pytest

from jarvis.agent import capability_service as svc
from jarvis.agent import mcp_client, skill_hub, skill_usage, skills
from jarvis.core import config

_ECHO_SERVER = textwrap.dedent("""\
    import json, sys
    for line in sys.stdin:
        msg = json.loads(line)
        method = msg.get("method")
        rid = msg.get("id")
        if method == "initialize":
            out = {"jsonrpc": "2.0", "id": rid, "result":
                   {"protocolVersion": "2025-06-18",
                    "serverInfo": {"name": "echo"}}}
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            out = {"jsonrpc": "2.0", "id": rid, "result": {"tools": [
                {"name": "echo", "description": "echo balik"}]}}
        elif method == "tools/call":
            text = json.dumps(msg["params"]["arguments"])
            out = {"jsonrpc": "2.0", "id": rid, "result":
                   {"content": [{"type": "text", "text": "ECHO:" + text}]}}
        else:
            out = {"jsonrpc": "2.0", "id": rid,
                   "error": {"message": "unknown"}}
        sys.stdout.write(json.dumps(out) + "\\n")
        sys.stdout.flush()
""")


@pytest.fixture()
def echo_server(tmp_path):
    script = tmp_path / "echo_mcp.py"
    script.write_text(_ECHO_SERVER, encoding="utf-8")
    srv = mcp_client.MCPServer("echo", sys.executable, [str(script)])
    yield srv
    srv.close()


def test_mcp_handshake_list_call(echo_server):
    assert echo_server.start() is True
    assert [t["name"] for t in echo_server.tools] == ["echo"]
    hasil = echo_server.call("echo", {"pesan": "halo"})
    assert hasil == 'ECHO:{"pesan": "halo"}'
    echo_server.close()
    assert echo_server.alive is False


def test_mcp_server_mati_tidak_crash(tmp_path):
    srv = mcp_client.MCPServer("rusak", sys.executable,
                               ["-c", "import sys; sys.exit(1)"])
    assert srv.start() is False
    assert srv.error != ""


@pytest.fixture()
def mcp_cfg(monkeypatch):
    values = {"mcp.servers": [{"name": "echo", "command": "x", "args": []}],
              "mcp.disabled": []}
    orig = config.get

    def fake(key, default=None):
        return values[key] if key in values else orig(key, default)

    monkeypatch.setattr(config, "get", fake)
    return values


def test_server_specs_dan_disabled(mcp_cfg):
    assert mcp_client.server_specs() == \
        [{"name": "echo", "command": "x", "args": []}]
    mcp_cfg["mcp.disabled"] = ["echo"]
    assert mcp_client.disabled_names() == {"echo"}


def test_mcp_tools_gate(mcp_cfg, monkeypatch):
    from jarvis.agent.tools import mcp_tools
    assert mcp_tools.available() is True
    mcp_cfg["mcp.servers"] = []
    # The configuration/diagnostic tools remain visible so the agent can
    # explain that no server exists instead of silently losing MCP capability.
    assert mcp_tools.available() is True


def test_set_mcp_enabled_persist(tmp_path, monkeypatch, mcp_cfg):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("mcp:\n  servers: []\n  disabled: []\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    try:
        assert svc.set_mcp_enabled("echo", False) is True
        assert "  disabled: [echo]" in cfg.read_text(encoding="utf-8")
        assert svc.set_mcp_enabled("asing", False) is False
    finally:
        # set_mcp_enabled me-reload cache config dari file tmp — pulihkan
        # agar test lain tidak mewarisi config kosong
        monkeypatch.undo()
        config.reload()


# ── Browse Hub ────────────────────────────────────────────────────────────────

@pytest.fixture()
def hub_env(tmp_path, monkeypatch):
    d = tmp_path / "skills_data"
    d.mkdir()
    monkeypatch.setattr(skills, "skills_dir", lambda: d)
    hub = tmp_path / "hub" / "research"
    hub.mkdir(parents=True)
    for name in ("arxiv", "hermes-gateway-maintenance", "petdex"):
        folder = hub / name
        folder.mkdir()
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: d-{name}\n---\nisi",
            encoding="utf-8")
    orig = config.get

    def fake(key, default=None):
        if key == "skills.hub_sources":
            return [str(tmp_path / "hub")]
        return orig(key, default)

    monkeypatch.setattr(config, "get", fake)
    monkeypatch.setattr(config, "resolve_path",
                        lambda rel: __import__("pathlib").Path(rel))
    return d


def test_hub_list_blocklist_dan_kategori(hub_env):
    items = skill_hub.list_available()
    names = [s["name"] for s in items]
    assert names == ["arxiv"]                  # hermes-* & petdex disaring
    assert items[0]["category"] == "Research"
    assert items[0]["installed"] is False


def test_hub_install_provenance_dan_duplikat(hub_env):
    ok, _ = skill_hub.install("arxiv")
    assert ok is True
    assert (hub_env / "arxiv" / "SKILL.md").exists()
    assert skill_usage.provenance("arxiv") == "hub"
    assert skill_hub.list_available()[0]["installed"] is True
    ok, msg = skill_hub.install("arxiv")
    assert ok is False and "terinstal" in msg
    ok, _ = skill_hub.install("tidak-ada")
    assert ok is False


def test_hub_search_filter(hub_env):
    assert skill_hub.list_available("arx")[0]["name"] == "arxiv"
    assert skill_hub.list_available("zzz") == []
