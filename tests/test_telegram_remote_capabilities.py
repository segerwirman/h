"""Safe remote Telegram capability boundary regressions."""
from __future__ import annotations


def test_telegram_context_exposes_safe_agent_web_and_image_capabilities_only():
    from jarvis.agent.capabilities import REGISTRY
    from jarvis.gateway.base import InboundMessage

    context = InboundMessage(
        "message-1", "telegram", "chat-1", "actor-1", "cari video YouTube"
    ).execution_context()

    assert context.toolsets == frozenset(
        {"agent", "image", "memory", "messaging", "skills", "web"}
    )
    assert set(REGISTRY.exposed_tool_names(context)) >= {
        "web_search", "web_extract", "yt_search_data", "image_generate",
        "skill_list", "skill_view", "skill_manage",
        "memory_search", "memory_write",
    }
    assert "browser_navigate" not in REGISTRY.exposed_tool_names(context)
    assert "terminal" not in REGISTRY.exposed_tool_names(context)


def test_remote_agent_dispatch_is_bounded_to_safe_toolsets():
    from jarvis.agent import dispatch
    from jarvis.gateway.base import InboundMessage

    context = InboundMessage(
        "message-2", "telegram", "chat-1", "actor-1", "riset singkat"
    ).execution_context()

    assert dispatch.dispatch_risk(context) == "medium"
    assert dispatch.dispatch_risk(None) == "high"


def test_native_registry_tools_have_local_capability_descriptors():
    from jarvis.agent.capabilities import REGISTRY

    for name in ("open_app", "camera_open", "browser_navigate", "terminal"):
        descriptor = REGISTRY.descriptor_for_tool(name)
        assert descriptor is not None, name
        assert descriptor.toolset == "local"
    assert REGISTRY.descriptor_for_tool("process_list").risk == "low"
    assert REGISTRY.descriptor_for_tool("process_kill").risk == "high"


def test_remote_context_does_not_gain_synthesized_local_tools():
    from jarvis.agent.capabilities import REGISTRY
    from jarvis.gateway.base import InboundMessage

    context = InboundMessage(
        "message-3", "telegram", "chat-1", "actor-1", "buka aplikasi"
    ).execution_context()
    exposed = set(REGISTRY.exposed_tool_names(context))
    assert "open_app" not in exposed
    assert "camera_open" not in exposed
    assert "terminal" not in exposed
