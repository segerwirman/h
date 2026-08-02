"""A46: restore SafeDesktopSession class shape and default production bindings.

Regression: A42 (514ae65) nested set_value/toggle/click/select_option inside a
duplicate _default_session instead of the class, and the production default
session referenced DRIVER.click_rect (AttributeError) since A20. These tests
lock the class shape, single toplevel factory, and default-session construction
with every native callback bound.
"""
import asyncio
import ast
from pathlib import Path

_SRC = (
    Path(__file__).resolve().parents[1]
    / "jarvis" / "agent" / "tools" / "desktop_safe_click.py"
)

_REQUIRED_CLASS_METHODS = {
    "__post_init__", "_disown", "observe_for", "observe", "clear_session",
    "clear_all", "set_content_title", "set_value", "toggle", "select_option",
    "scroll", "click", "reorder_scene",
}

_PUBLIC_ACTION_METHODS = {
    "set_content_title", "set_value", "toggle", "select_option",
    "scroll", "click", "reorder_scene",
}

_REQUIRED_CALLBACKS = {
    "click_rect", "scroll_rect", "click_native", "toggle_native",
    "set_value_native", "select_option_native", "scroll_native",
    "set_text_native", "reorder_native",
}


def _module() -> ast.Module:
    return ast.parse(_SRC.read_text(encoding="utf-8"))


def _session_class(mod: ast.Module) -> ast.ClassDef:
    for node in mod.body:
        if isinstance(node, ast.ClassDef) and node.name == "SafeDesktopSession":
            return node
    raise AssertionError("SafeDesktopSession class tidak ditemukan")


def test_class_action_methods_are_all_members():
    cls = _session_class(_module())
    methods = {node.name for node in cls.body if isinstance(node, ast.FunctionDef)}
    missing = _REQUIRED_CLASS_METHODS - methods
    assert not missing, f"SafeDesktopSession kehilangan method: {sorted(missing)}"


def test_only_one_toplevel_default_session():
    mod = _module()
    defs = [
        node for node in mod.body
        if isinstance(node, ast.FunctionDef) and node.name == "_default_session"
    ]
    assert len(defs) == 1, "duplicate _default_session harus dihapus"


def test_no_driver_click_rect_reference():
    src = _SRC.read_text(encoding="utf-8")
    assert "DRIVER.click_rect" not in src


def test_default_session_builds_with_all_native_callbacks():
    from jarvis.agent.tools.desktop_safe_click import desktop_safe_session

    session = desktop_safe_session()
    for method in _PUBLIC_ACTION_METHODS:
        assert hasattr(session, method), f"method {method} hilang dari session"
    for callback in _REQUIRED_CALLBACKS:
        assert getattr(session, callback, None) is not None, \
            f"callback {callback} tidak terikat pada default session"


def test_registry_desktop_safe_click_uses_default_session_without_attribute_error():
    from jarvis.agent import registry
    from jarvis.agent.execution_context import ExecutionContext

    class Session:
        id = "desktop-a"

        def record_tool(self, *_):
            pass

    context = ExecutionContext.create(
        source="agent", actor_id="local", session_id="desktop-a",
        surface="desktop", toolsets=["desktop_safe"],
    )
    result = asyncio.run(registry.execute(
        "desktop_safe_click",
        {"observation_id": "nope", "element_id": "uia-1"},
        session=Session(), context=context,
    ))
    assert result.ok is False
    assert "AttributeError" not in (result.error or "")
    # fail closed on unknown observation, not on missing production session
    assert "tidak diterbitkan" in (result.error or "") or \
        "tidak aman" in (result.error or "") or \
        "belum tersedia" in (result.error or "")
