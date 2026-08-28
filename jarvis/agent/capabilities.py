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
    direct_grant: bool = False


# Explicit opt-in only. This table is intentionally small and reviewable:
# read-only T0/T1 capabilities with no account mutation or external side effect.
# Synthesized local descriptors never inherit eligibility from their name.
_DIRECT_GRANT_IDS = frozenset({
    "web.web_search",
    "web.web_extract",
    "web.yt_search_data",
    "web.yt_video_info",
    "web.yt_trending",
    "memory.memory_search",
    "gws_read.gmail_safe_summary",
    "gws_read.gcal_safe_agenda",
    "gws_read.morning_briefing",
})


def _validate_direct_grant(descriptor: CapabilityDescriptor) -> None:
    if not descriptor.direct_grant:
        return
    if descriptor.id not in _DIRECT_GRANT_IDS:
        raise ValueError(f"direct grant capability not allowlisted: {descriptor.id}")
    if str(descriptor.risk).casefold() != "low":
        raise ValueError(f"direct grant requires low risk: {descriptor.id}")
    # The catalog is an additional boundary, never a substitute for policy.
    probe = ExecutionContext.create(
        source="agent",
        actor_id="local-direct-grant-validation",
        session_id="capability-validation",
        surface="desktop",
        toolsets={descriptor.toolset},
    )
    decision = policy.decide(
        probe, capability=descriptor.id, risk=descriptor.risk,
    )
    if not decision.allowed or decision.needs_approval:
        raise ValueError(f"direct grant policy denied: {descriptor.id}")


class CapabilityRegistry:
    def __init__(self):
        self._items: dict[str, CapabilityDescriptor] = {}

    def register(self, descriptor: CapabilityDescriptor) -> None:
        if descriptor.id in self._items:
            raise ValueError(f"capability duplicate: {descriptor.id}")
        _validate_direct_grant(descriptor)
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
        except Exception as exc:                            # noqa: BLE001
            from jarvis.core import quiet
            quiet.swallowed(
                "agent.capabilities.discovery_failed",
                exc,
            )
        return [items[key] for key in sorted(items)]

    def descriptor_for_tool(self, tool_name: str) -> CapabilityDescriptor | None:
        """Pencarian tunggal — sengaja TANPA cache lintas panggilan.

        §29 sempat meng-cache indeksnya. Tanda tangan cache apa pun yang
        cukup murah hanya menangkap *id* descriptor, bukan isinya, sehingga
        descriptor yang didaftar ulang dengan id sama tetapi ``risk`` berbeda
        akan dijawab dari salinan lama — dan nilai itu masuk ke
        ``policy.decide``. Biaya O(n²)-nya dulu datang dari ``schemas()`` yang
        memanggil ini 103 kali; itu diselesaikan di sana dengan satu indeks
        lokal, bukan dengan menyimpan jawaban melewati batas panggilan.
        """
        return self.by_tool_name().get(str(tool_name))

    def by_tool_name(self) -> dict:
        """Indeks nama tool → descriptor dari SATU snapshot ``descriptors()``."""
        return {item.tool_name: item for item in self.descriptors()}

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
    CapabilityDescriptor("desktop_safe.desktop_visual_observe", "desktop_visual_observe", "desktop_safe", "low", 15),
    CapabilityDescriptor("desktop_safe.desktop_safe_click", "desktop_safe_click", "desktop_safe", "medium", 30),
    CapabilityDescriptor("desktop_safe.desktop_safe_right_click", "desktop_safe_right_click", "desktop_safe", "medium", 30),
    CapabilityDescriptor("desktop_safe.desktop_safe_double_click", "desktop_safe_double_click", "desktop_safe", "medium", 30),
    CapabilityDescriptor("desktop_safe.desktop_safe_scroll", "desktop_safe_scroll", "desktop_safe", "medium", 30),
    CapabilityDescriptor("desktop_safe.desktop_safe_text_entry", "desktop_safe_text_entry", "desktop_safe", "medium", 30),
    CapabilityDescriptor("desktop_safe.desktop_safe_set_value", "desktop_safe_set_value", "desktop_safe", "medium", 30),
    CapabilityDescriptor("desktop_safe.desktop_safe_select_option", "desktop_safe_select_option", "desktop_safe", "medium", 30),
    CapabilityDescriptor("desktop_safe.desktop_safe_toggle", "desktop_safe_toggle", "desktop_safe", "medium", 30),
    CapabilityDescriptor("desktop_safe.desktop_safe_set_content_title", "desktop_safe_set_content_title", "desktop_safe", "medium", 30),
    CapabilityDescriptor("desktop_safe.desktop_safe_reorder_scene", "desktop_safe_reorder_scene", "desktop_safe", "medium", 30),
    CapabilityDescriptor("web.web_search", "web_search", "web", "low", 45,
                         direct_grant=True),
    CapabilityDescriptor("web.web_extract", "web_extract", "web", "low", 60,
                         direct_grant=True),
    CapabilityDescriptor("web.yt_search_data", "yt_search_data", "web", "low", 30,
                         direct_grant=True),
    CapabilityDescriptor("web.yt_video_info", "yt_video_info", "web", "low", 20,
                         direct_grant=True),
    CapabilityDescriptor("web.yt_trending", "yt_trending", "web", "low", 20,
                         direct_grant=True),
    CapabilityDescriptor("image.image_generate", "image_generate", "image",
                         "medium", 180),
    CapabilityDescriptor("skills.skill_list", "skill_list", "skills", "low", 15),
    CapabilityDescriptor("skills.skill_view", "skill_view", "skills", "low", 15),
    CapabilityDescriptor("skills.skill_manage", "skill_manage", "skills",
                         "medium", 15),
    CapabilityDescriptor("memory.memory_search", "memory_search", "memory",
                         "low", 30, direct_grant=True),
    CapabilityDescriptor("memory.memory_write", "memory_write", "memory",
                         "medium", 30),
    CapabilityDescriptor("memory.memory_update", "memory_update", "memory",
                         "medium", 30),
    CapabilityDescriptor("memory.memory_forget", "memory_forget", "memory",
                         "medium", 30),
    # Fase 15A: paired remote receives only privacy-tiered GWS read models.
    CapabilityDescriptor("gws_read.gmail_safe_summary", "gmail_safe_summary",
                         "gws_read", "low", 45, direct_grant=True),
    CapabilityDescriptor("gws_read.gcal_safe_agenda", "gcal_safe_agenda",
                         "gws_read", "low", 30, direct_grant=True),
    CapabilityDescriptor("gws_read.morning_briefing", "morning_briefing",
                         "gws_read", "low", 45, direct_grant=True),
):
    REGISTRY.register(_descriptor)
