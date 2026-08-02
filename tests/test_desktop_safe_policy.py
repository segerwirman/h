"""Desktop-safe capability stays desktop-local, session-bound, and ephemeral."""
from __future__ import annotations

import asyncio

from jarvis.agent.execution_context import ExecutionContext
from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


def _context(*, surface="desktop", source="ui", toolsets=("desktop_safe",)):
    return ExecutionContext.create(
        source=source, actor_id="local-user", session_id="desktop-a",
        surface=surface, toolsets=toolsets,
    )


def test_desktop_safe_has_explicit_capability_descriptors_not_generic_local():
    from jarvis.agent.capabilities import REGISTRY

    by_tool = {item.tool_name: item for item in REGISTRY.descriptors()}

    assert by_tool["desktop_observe"].toolset == "desktop_safe"
    assert by_tool["desktop_safe_click"].toolset == "desktop_safe"
    assert by_tool["desktop_safe_scroll"].toolset == "desktop_safe"
    assert by_tool["desktop_observe"].id == "desktop_safe.desktop_observe"



def test_registry_schema_matrix_exposes_every_desktop_safe_tool_only_local_desktop():
    from jarvis.agent import registry

    expected = {"desktop_observe", "desktop_safe_click", "desktop_safe_scroll",
                "desktop_safe_set_value"}
    cases = (
        (None, set()),
        (_context(surface="desktop", source="ui"), expected),
        (_context(surface="desktop", source="agent"), expected),
        (_context(surface="voice", source="gemini_live"), set()),
        (_context(surface="remote", source="telegram"), set()),
        (_context(surface="desktop", source="cron"), set()),
        (_context(surface="desktop", source="delegation"), set()),
        (_context(surface="desktop", source="ui", toolsets=("local",)), set()),
    )
    for context, expected_names in cases:
        names = {item["function"]["name"] for item in registry.schemas(context=context)}
        assert names & expected == expected_names
