"""A57: GWS read tools explicit activation (descriptors + group membership).

Regression: gmail_safe/gcal_safe_agenda/calendar_safe auto-discovered as
generic-local without a descriptor; morning_briefing must stay unactivated
until the monitoring vertical exists.
"""
from __future__ import annotations


def test_gws_read_tools_have_explicit_descriptors_and_remote_read_schema(monkeypatch):
    from jarvis.integrations import google_auth
    monkeypatch.setattr(google_auth, "has_read_scope", lambda api: True)
    monkeypatch.setattr(google_auth, "has_write_scope", lambda api: False)

    from jarvis.agent import registry
    from jarvis.agent.capabilities import REGISTRY
    from jarvis.agent.execution_context import ExecutionContext
    from jarvis.agent.tools.gcal_safe_agenda import GcalSafeAgenda
    from jarvis.agent.tools.gmail_safe import GmailSafeSummary

    for tool_cls in (GmailSafeSummary, GcalSafeAgenda):
        descriptor = REGISTRY.descriptor_for_tool(tool_cls.name)
        assert descriptor is not None, f"{tool_cls.name} harus punya descriptor"
        assert descriptor.toolset == "gws_read", f"{tool_cls.name} toolset gws_read"

    # re-discover with read scope granted so the module gates open
    all_tools = registry.all_tools(refresh=True)
    assert GmailSafeSummary.name in all_tools
    assert GcalSafeAgenda.name in all_tools

    for surface, source, toolsets, allowed in (
        ("remote", "telegram", ["gws_read"], True),
        ("desktop", "agent", ["gws_read"], True),
        ("desktop", "cron", ["gws_read"], True),        # read-only low-risk: briefing otomatis
        ("desktop", "delegation", ["gws_read"], True),  # read-only low-risk
        ("desktop", "agent", ["agent"], False),         # tanpa toolset gws_read -> toolset_denied
        ("remote", "telegram", ["agent"], False),
    ):
        ctx = ExecutionContext.create(
            source=source, actor_id="local", session_id="s",
            surface=surface, toolsets=toolsets,
        )
        names = {item["function"]["name"] for item in registry.schemas(context=ctx)}
        assert (GmailSafeSummary.name in names) is allowed
        assert (GcalSafeAgenda.name in names) is allowed


def test_gws_morning_briefing_not_activated_without_monitoring():
    from jarvis.agent.capabilities import REGISTRY

    assert REGISTRY.descriptor_for_tool("morning_briefing") is None


def test_gws_tools_membership_in_google_cloud_group():
    from jarvis.agent.toolgroups import TOOL_GROUPS

    group = next(g for g in TOOL_GROUPS if g.id == "google_cloud")
    for module in ("gmail_safe", "gcal_safe_agenda", "calendar_safe"):
        assert module in group.modules, f"{module} harus di google_cloud group"
