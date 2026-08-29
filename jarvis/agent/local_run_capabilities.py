"""Process-local capability overlays for one trusted desktop parent task.

The overlay only makes a small protected schema visible at model-run start.  It
is not an execution grant: registry policy and the selected-surface owner still
have to admit every call.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jarvis.agent.execution_context import ExecutionContext


_SELECTED_TAB_TOOLSET = "selected_tab"


@dataclass(frozen=True)
class LocalRunCapabilityOverlay:
    session_id: str
    task_id: str
    context: ExecutionContext
    tool_names: frozenset[str]
    _adapter: Any

    def matches(self, *, session, adapter) -> bool:
        root_adapter = _root_adapter(adapter)
        return bool(
            session is not None
            and str(getattr(session, "id", "") or "") == self.session_id
            and str(getattr(session, "registry_task_id", "") or "")
            == self.task_id
            and root_adapter is self._adapter
            and _is_trusted_local_adapter(root_adapter)
        )


def _root_adapter(adapter):
    """Unwrap the private final-text buffer without accepting arbitrary proxies."""

    candidate = adapter
    seen: set[int] = set()
    while type(candidate).__name__ == "_BufferedFinalAdapter":
        marker = id(candidate)
        if marker in seen:
            break
        seen.add(marker)
        candidate = getattr(candidate, "_delegate", None)
    return candidate


def _is_trusted_local_adapter(adapter) -> bool:
    try:
        from jarvis.agent.adapters.ui import UIAdapter

        return type(adapter) is UIAdapter and adapter._win() is not None
    except Exception:  # noqa: BLE001
        return False


def _selected_tab_tool_names() -> frozenset[str]:
    from jarvis.agent.capabilities import REGISTRY

    return frozenset(
        item.tool_name
        for item in REGISTRY.descriptors()
        if item.enabled and item.toolset == _SELECTED_TAB_TOOLSET
    )


def mint_selected_tab_overlay(
    *,
    session_id: str,
    task_id: str,
    adapter,
) -> LocalRunCapabilityOverlay:
    """Mint one immutable overlay after real dispatch identities exist."""

    session_id = str(session_id or "").strip()
    task_id = str(task_id or "").strip()
    if not session_id or not task_id:
        raise ValueError("selected-tab overlay membutuhkan session dan task")
    if not _is_trusted_local_adapter(adapter):
        raise ValueError("selected-tab overlay membutuhkan adapter UI lokal")
    context = ExecutionContext.create(
        source="ui",
        actor_id="local-user",
        session_id=session_id,
        surface="browser_tab",
        toolsets={_SELECTED_TAB_TOOLSET},
    )
    return LocalRunCapabilityOverlay(
        session_id=session_id,
        task_id=task_id,
        context=context,
        tool_names=_selected_tab_tool_names(),
        _adapter=adapter,
    )


def selected_tab_context(
    overlay,
    *,
    tool_name: str,
    session,
    adapter,
) -> tuple[ExecutionContext | None, str]:
    """Return the protected context only for an exact live binding."""

    if not isinstance(overlay, LocalRunCapabilityOverlay):
        return None, "selected_tab_overlay_required"
    if str(tool_name or "") not in overlay.tool_names:
        return None, "selected_tab_overlay_tool_denied"
    if not overlay.matches(session=session, adapter=adapter):
        return None, "selected_tab_overlay_binding_mismatch"
    return overlay.context, ""


__all__ = [
    "LocalRunCapabilityOverlay",
    "mint_selected_tab_overlay",
    "selected_tab_context",
]
