"""Capability catalog: a small shared exposure boundary for tools/plugins/MCP."""
from __future__ import annotations

from dataclasses import dataclass

from jarvis.agent.execution_context import ExecutionContext
from jarvis.agent import policy


@dataclass(frozen=True)
class CapabilityDescriptor:
    id: str
    tool_name: str
    toolset: str
    risk: str
    timeout_s: float
    enabled: bool = True


class CapabilityRegistry:
    def __init__(self):
        self._items: dict[str, CapabilityDescriptor] = {}

    def register(self, descriptor: CapabilityDescriptor) -> None:
        if descriptor.id in self._items:
            raise ValueError(f"capability duplicate: {descriptor.id}")
        self._items[descriptor.id] = descriptor

    def descriptors(self) -> list[CapabilityDescriptor]:
        items = dict(self._items)
        static_tools = {item.tool_name for item in items.values()}
        # The native registry is the source of truth for local capabilities.
        # Keep the explicit descriptors above as the remote allowlist, then
        # synthesize local-only descriptors for every other discovered tool.
        try:
            from jarvis.agent import registry

            for name, tool in registry.all_tools().items():
                if name in static_tools:
                    continue
                module = type(tool).__module__.rsplit(".", 1)[-1]
                if getattr(tool, "requires_confirmation", False):
                    risk = "high"
                elif getattr(tool, "read_only", False):
                    risk = "low"
                else:
                    risk = "medium"
                descriptor = CapabilityDescriptor(
                    id=f"local.{module}.{name}",
                    tool_name=name,
                    toolset="local",
                    risk=risk,
                    timeout_s=float(getattr(tool, "timeout_s", 60)),
                )
                items[descriptor.id] = descriptor
        except Exception:                                   # noqa: BLE001
            pass
        return [items[key] for key in sorted(items)]

    def descriptor_for_tool(self, tool_name: str) -> CapabilityDescriptor | None:
        return next(
            (item for item in self.descriptors()
             if item.tool_name == tool_name),
            None,
        )

    def exposed_tool_names(self, context: ExecutionContext) -> list[str]:
        out = []
        for descriptor in self.descriptors():
            if not descriptor.enabled or descriptor.toolset not in context.toolsets:
                continue
            decision = policy.decide(context, capability=descriptor.id,
                                     risk=descriptor.risk)
            if decision.allowed:
                out.append(descriptor.tool_name)
        return out


REGISTRY = CapabilityRegistry()

# Remote ingress is deliberately opt-in.  These descriptors are the only
# agent-facing tools exposed to paired Telegram contexts; desktop/browser
# control, terminal, filesystem mutation, credentials, and account actions
# remain absent and therefore fail closed.
for _descriptor in (
    CapabilityDescriptor("desktop_safe.desktop_observe", "desktop_observe", "desktop_safe", "low", 20),
    CapabilityDescriptor("desktop_safe.desktop_safe_click", "desktop_safe_click", "desktop_safe", "medium", 30),
    CapabilityDescriptor("desktop_safe.desktop_safe_set_value", "desktop_safe_set_value", "desktop_safe", "medium", 30),
    CapabilityDescriptor("desktop_safe.desktop_safe_toggle", "desktop_safe_toggle", "desktop_safe", "medium", 30),
    CapabilityDescriptor("web.web_search", "web_search", "web", "low", 45),
    CapabilityDescriptor("web.web_extract", "web_extract", "web", "low", 60),
    CapabilityDescriptor("web.yt_search_data", "yt_search_data", "web", "low", 30),
    CapabilityDescriptor("web.yt_video_info", "yt_video_info", "web", "low", 20),
    CapabilityDescriptor("web.yt_trending", "yt_trending", "web", "low", 20),
    CapabilityDescriptor("image.image_generate", "image_generate", "image",
                         "medium", 180),
    CapabilityDescriptor("skills.skill_list", "skill_list", "skills", "low", 15),
    CapabilityDescriptor("skills.skill_view", "skill_view", "skills", "low", 15),
    CapabilityDescriptor("skills.skill_manage", "skill_manage", "skills",
                         "medium", 15),
    CapabilityDescriptor("memory.memory_search", "memory_search", "memory",
                         "low", 30),
    CapabilityDescriptor("memory.memory_write", "memory_write", "memory",
                         "medium", 30),
    CapabilityDescriptor("memory.memory_update", "memory_update", "memory",
                         "medium", 30),
    CapabilityDescriptor("memory.memory_forget", "memory_forget", "memory",
                         "medium", 30),
):
    REGISTRY.register(_descriptor)
