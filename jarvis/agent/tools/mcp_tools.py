"""Tool MCP (PARITY v2 §5.7) — jembatan ke server MCP eksternal.

Dua tool, bukan injeksi schema dinamis per-tool (v1 yang jujur):
    mcp_list — daftar server + tool yang tersedia (read-only)
    mcp_call — panggil satu tool di satu server

Tool status tetap dimuat walau belum ada server, sehingga agent dapat
menjelaskan konfigurasi yang kurang alih-alih kehilangan capability MCP.
"""
from __future__ import annotations

import asyncio
import json

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult


def available() -> bool:
    return True


class _ListParams(BaseModel):
    pass


class McpList(Tool):
    name = "mcp_list"
    description = ("Daftar server MCP terkonfigurasi + tool yang mereka "
                   "sediakan (connect bila perlu).")
    params_schema = _ListParams
    read_only = True
    timeout_s = 60

    async def run(self, **_) -> ToolResult:
        from jarvis.agent import mcp_client
        # Listing must remain low-latency and side-effect free. Connect one
        # configured server explicitly with mcp_connect; mcp_call also starts
        # its target lazily.
        stats = await asyncio.to_thread(mcp_client.statuses, False)
        if not stats:
            return ToolResult.success("tidak ada server MCP terkonfigurasi",
                                      display="0 server")
        lines = []
        for s in stats:
            tools = ", ".join(s["tools"]) or "-"
            extra = f" ({s['error'][:80]})" if s["state"] == "error" else ""
            lines.append(f"- {s['name']} [{s['state']}]{extra}: {tools}")
        return ToolResult.success("\n".join(lines),
                                  display=f"{len(stats)} server")


class _ConnectParams(BaseModel):
    server: str = Field(description="Nama server MCP terkonfigurasi")


class McpConnect(Tool):
    name = "mcp_connect"
    description = (
        "Hubungkan satu server MCP yang sudah dideklarasikan di config.yaml "
        "dan ambil daftar tool-nya."
    )
    params_schema = _ConnectParams
    timeout_s = 60

    async def run(self, server: str, **_) -> ToolResult:
        from jarvis.agent import mcp_client

        name = str(server or "").strip()
        if name in mcp_client.disabled_names():
            return ToolResult.fail(f"server '{name}' dimatikan user")
        srv = mcp_client.get_server(name)
        if srv is None:
            return ToolResult.fail(
                f"server MCP tidak dikenal: {name}; tambahkan ke mcp.servers"
            )
        connected = await asyncio.to_thread(srv.start)
        if not connected:
            return ToolResult.fail(srv.error or "server MCP gagal terhubung")
        tools = [str(item.get("name", "")) for item in srv.tools]
        return ToolResult.success(
            {"server": name, "state": "connected", "tools": tools},
            display=f"MCP {name} terhubung ({len(tools)} tool)",
        )


class _CallParams(BaseModel):
    server: str = Field(description="Nama server MCP (lihat mcp_list)")
    tool: str = Field(description="Nama tool di server itu")
    arguments: str = Field("{}", description="Argumen JSON object")


class McpCall(Tool):
    name = "mcp_call"
    description = ("Panggil satu tool di server MCP eksternal. Argumen "
                   "berupa JSON object sesuai schema tool.")
    params_schema = _CallParams
    timeout_s = 90

    async def run(self, server: str, tool: str, arguments: str = "{}",
                  **_) -> ToolResult:
        from jarvis.agent import mcp_client
        if server in mcp_client.disabled_names():
            return ToolResult.fail(f"server '{server}' dimatikan user")
        srv = mcp_client.get_server(server)
        if srv is None:
            return ToolResult.fail(f"server MCP tidak dikenal: {server}")
        try:
            args = json.loads(arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError("bukan object")
        except Exception:                                    # noqa: BLE001
            return ToolResult.fail("arguments harus JSON object")
        try:
            text = await asyncio.to_thread(srv.call, tool, args)
        except mcp_client.MCPError as e:
            return ToolResult.fail(f"MCP: {str(e)[:200]}")
        except Exception as e:                               # noqa: BLE001
            return ToolResult.fail(f"MCP gagal: {str(e)[:200]}")
        return ToolResult.success(text[:24_000] or "(hasil kosong)",
                                  display=f"{server}:{tool}")
