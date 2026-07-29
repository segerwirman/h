"""Validation for explicit trusted-local MCP stdio server specifications."""
from __future__ import annotations

_SECRET_MARKERS = ("token=", "api_key=", "apikey=", "password=", "secret=")


def validate_spec(spec: dict, *, allowed_commands: set[str]) -> tuple[bool, str]:
    if not isinstance(spec, dict):
        return False, "invalid_spec"
    name = str(spec.get("name") or "").strip()
    command = str(spec.get("command") or "").strip()
    args = spec.get("args") or []
    if not name or not command or not isinstance(args, list):
        return False, "invalid_spec"
    if command not in {str(item) for item in allowed_commands}:
        return False, "command_not_allowed"
    if any(marker in str(arg).lower() for arg in args for marker in _SECRET_MARKERS):
        return False, "secret_argument_denied"
    return True, ""


def allowed_commands_from_config(config_get) -> set[str]:
    raw = config_get("mcp.allowed_commands", []) or []
    if isinstance(raw, str):
        raw = [raw]
    return {str(item).strip() for item in raw if str(item).strip()}
