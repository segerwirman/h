"""Klien MCP minimal (PARITY v2 §5.7) — stdio, tanpa dependency baru.

MCP (Model Context Protocol) stdio transport = JSON-RPC 2.0, satu pesan
per baris di stdin/stdout server. Klien ini mengimplementasikan subset
yang dibutuhkan Jarvis: ``initialize`` → ``notifications/initialized`` →
``tools/list`` → ``tools/call``.

Server dideklarasikan di config.yaml:

    mcp:
      servers:
        - name: filesystem
          command: npx
          args: ["-y", "@modelcontextprotocol/server-filesystem", "D:/data"]
      disabled: []          # nama server yang dimatikan (toggle UI)

Koneksi lazy (spawn saat pertama dipakai), best-effort: server mati/korup
tidak pernah mengganggu Jarvis — statusnya 'error' di panel.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time

from jarvis.core import config, log, quiet

_logger = log.get("agent.mcp")

_PROTOCOL_VERSION = "2025-06-18"


def server_specs() -> list[dict]:
    raw = config.get("mcp.servers", []) or []
    from jarvis.agent.mcp_catalog import allowed_commands_from_config, validate_spec

    allowed = allowed_commands_from_config(config.get)
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        command = str(entry.get("command", "")).strip()
        if not name or not command:
            continue
        args = entry.get("args") or []
        spec = {"name": name, "command": command,
                "args": [str(a) for a in args]}
        # Empty allowlist preserves pre-Phase-6 trusted-local compatibility.
        if allowed:
            ok, reason = validate_spec(spec, allowed_commands=allowed)
            if not ok:
                _logger.warning("mcp.spec_denied", server=name, reason=reason)
                continue
        out.append(spec)
    return out


def disabled_names() -> set[str]:
    raw = config.get("mcp.disabled", []) or []
    if isinstance(raw, str):
        raw = [raw]
    try:
        return {str(v).strip() for v in raw if str(v).strip()}
    except TypeError:
        return set()


class MCPServer:
    """Satu server MCP di subprocess. Semua metode tidak pernah raise ke
    luar selain MCPError dengan pesan siap-tampil."""

    def __init__(self, name: str, command: str, args: list[str]):
        self.name = name
        self.command = command
        self.args = args
        self._proc: subprocess.Popen | None = None
        self._id = 0
        self._lock = threading.Lock()
        self.error: str = ""
        self.tools: list[dict] = []

    # ── plumbing ──────────────────────────────────────────────────────────

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _send(self, msg: dict) -> None:
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        self._proc.stdin.write(line.encode("utf-8"))
        self._proc.stdin.flush()

    def _read_response(self, want_id: int, timeout_s: float) -> dict:
        """Baca baris sampai respons ber-id cocok; notifikasi di-skip."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            raw = self._proc.stdout.readline()
            if not raw:
                raise MCPError("server menutup stdout")
            try:
                msg = json.loads(raw.decode("utf-8", errors="replace"))
            except Exception:                                # noqa: BLE001
                continue                       # baris non-JSON (log server)
            if msg.get("id") == want_id:
                if "error" in msg:
                    err = msg["error"] or {}
                    raise MCPError(str(err.get("message", err))[:200])
                return msg.get("result") or {}
        raise MCPError(f"timeout {timeout_s:.0f}s menunggu respons")

    def _rpc(self, method: str, params: dict | None = None,
             timeout_s: float = 30) -> dict:
        with self._lock:
            self._id += 1
            self._send({"jsonrpc": "2.0", "id": self._id, "method": method,
                        "params": params or {}})
            return self._read_response(self._id, timeout_s)

    def _notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method})

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Spawn + handshake. Return False (dan set .error) bila gagal."""
        if self.alive:
            return True
        try:
            self._proc = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL)
            result = self._rpc("initialize", {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "jarvis-mk50", "version": "1.0"},
            }, timeout_s=20)
            self._notify("notifications/initialized")
            self.tools = list(
                (self._rpc("tools/list", timeout_s=20) or {})
                .get("tools") or [])
            self.error = ""
            _logger.info("mcp.connected", server=self.name,
                         tools=len(self.tools),
                         proto=str(result.get("protocolVersion", ""))[:20])
            return True
        except Exception as e:                               # noqa: BLE001
            self.error = str(e)[:200]
            _logger.warning("mcp.start_failed", server=self.name,
                            error=self.error[:120])
            self.close()
            return False

    def call(self, tool: str, arguments: dict,
             timeout_s: float = 60) -> str:
        """tools/call → teks hasil (blok content type=text digabung)."""
        if not self.alive and not self.start():
            raise MCPError(self.error or "server tidak bisa dihubungi")
        result = self._rpc("tools/call",
                           {"name": tool, "arguments": arguments or {}},
                           timeout_s=timeout_s)
        if result.get("isError"):
            raise MCPError(_content_text(result)[:300] or "tool error")
        return _content_text(result)

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.kill()
            except Exception as exc:                         # noqa: BLE001
                quiet.swallowed("mcp.close_kill_failed", exc)


class MCPError(RuntimeError):
    pass


def _content_text(result: dict) -> str:
    parts = []
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(parts).strip()


# ── manager ───────────────────────────────────────────────────────────────────

_servers: dict[str, MCPServer] = {}
_mgr_lock = threading.Lock()


def get_server(name: str) -> MCPServer | None:
    spec = next((s for s in server_specs() if s["name"] == name), None)
    if spec is None:
        return None
    with _mgr_lock:
        srv = _servers.get(name)
        if srv is None:
            srv = MCPServer(spec["name"], spec["command"], spec["args"])
            _servers[name] = srv
        return srv


def statuses(probe: bool = False) -> list[dict]:
    """Status semua server untuk UI. ``probe=True`` mencoba connect
    (dipakai worker thread, bukan render)."""
    disabled = disabled_names()
    out = []
    for spec in server_specs():
        name = spec["name"]
        srv = get_server(name)
        if probe and name not in disabled and not srv.alive:
            srv.start()
        state = ("disabled" if name in disabled
                 else "connected" if srv.alive
                 else "error" if srv.error
                 else "not_connected")
        out.append({"name": name, "command": spec["command"],
                    "args": spec["args"], "state": state,
                    "enabled": name not in disabled,
                    "error": srv.error,
                    "tools": [t.get("name", "") for t in srv.tools]})
    return out


def shutdown_all() -> None:
    with _mgr_lock:
        for srv in _servers.values():
            srv.close()
        _servers.clear()
