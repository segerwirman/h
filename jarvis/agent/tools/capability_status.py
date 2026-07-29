"""Read-only self-inspection for native agent capabilities."""
from __future__ import annotations

from pydantic import BaseModel

from jarvis.agent.base import Tool, ToolResult


class _NoParams(BaseModel):
    pass


class CapabilityStatus(Tool):
    name = "capability_status"
    description = (
        "Periksa kemampuan native Jarvis yang benar-benar tersedia saat ini, "
        "provider/model kerja yang aktif, serta alasan integrasi terblokir. "
        "Gunakan sebelum menjawab pertanyaan tentang kemampuan atau koneksi."
    )
    params_schema = _NoParams
    read_only = True
    timeout_s = 15

    async def run(self, **_) -> ToolResult:
        from jarvis.agent import model_routing, toolgroups

        roles = model_routing.role_statuses()
        heavy = roles.get("heavy", {})
        lines = [
            "NATIVE AGENT MODEL",
            (
                f"- siap: {heavy.get('provider')} "
                f"({heavy.get('model') or 'default'})"
                if heavy.get("configured")
                else f"- belum siap: {heavy.get('reason') or 'unknown'}"
            ),
            "",
            "CAPABILITY GROUPS",
        ]
        available = 0
        blocked = 0
        for group in toolgroups.all_groups():
            if group["available"] and group["enabled"]:
                available += 1
                lines.append(
                    f"- READY {group['name']}: "
                    f"{', '.join(group['tools'])}")
            else:
                blocked += 1
                state = "DISABLED" if not group["enabled"] else "BLOCKED"
                reason = group.get("availability_reason") or (
                    "dimatikan pengguna" if state == "DISABLED"
                    else "belum tersedia")
                lines.append(f"- {state} {group['name']}: {reason}")
        return ToolResult.success(
            "\n".join(lines),
            display=f"{available} grup siap, {blocked} belum siap",
            ready_groups=available,
            blocked_groups=blocked,
        )
