"""A49: reorder verification must require parent identity and order change.

Regression: reorder_scene allowed missing parent identity and verified a no-op
drag (order unchanged) as success. Contract: both source and destination MUST
carry the same non-empty parent RuntimeId; verified requires the relative order
of source vs destination to change after the single native drag.
"""
from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
from jarvis.automation.cua_safety import CuaSafetyGate
from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


class _Desktop:
    def claim(self, _owner):
        return True

    def release(self, _owner):
        pass


def _tree(*, parent="rt-parent", y_order=(0, 1), runtime=("rt-0", "rt-1")):
    tree = ScreenElementTree()
    for idx, (ypos, rid) in enumerate(zip(y_order, runtime)):
        states = {"_uia_runtime_id": rid}
        if parent is not None:
            states["_uia_parent_runtime_id"] = parent
        tree.add(UIElement(
            f"uia-{idx}", ElementScope.PAGE_MAIN, "card", name=f"Scene {idx}",
            rect=(10, 50 + ypos * 60, 300, 50), visible=True, confidence=.95,
            provenance="uia", states=states,
        ))
    return tree


def _authority(before_tree, after_tree, native):
    frames = iter([
        CaptureFrame("uia:content-studio", before_tree),
        CaptureFrame("uia:content-studio", after_tree),
    ])
    gate = CuaSafetyGate()
    session = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: next(frames)), lambda _rect: None,
        desktop=_Desktop(), reorder_native=native,
    )
    return session


def test_reorder_rejects_missing_parent_identity_before_executor():
    calls = []

    def native(src_ref, dst_ref):
        calls.append(src_ref.element_id)

    session = _authority(
        _tree(parent=None), _tree(parent=None), native,
    )
    observation = session.observe_for("desktop-a")
    outcome, error = session.reorder_scene(
        observation.id, "uia-0", "uia-1", session_id="desktop-a")
    assert outcome is None
    assert error and "parent" in error
    assert not calls, "executor tidak boleh dipanggil tanpa parent proof"


def test_reorder_rejects_different_parent_identity():
    calls = []

    def native(src_ref, dst_ref):
        calls.append(src_ref.element_id)

    session = _authority(
        _tree(parent="rt-parent-a"), _tree(parent="rt-parent-a"), native,
    )
    observation = session.observe_for("desktop-a")
    # dst tree uses different parent only for the pre-capture; keep before-tree
    # with different parents by overriding after: same-parent after is fine here
    frames = iter([
        CaptureFrame("uia:content-studio", _tree(parent="rt-parent-a")),
        CaptureFrame("uia:content-studio", _tree(parent="rt-parent-a")),
    ])
    gate = CuaSafetyGate()
    session2 = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: next(frames)), lambda _rect: None,
        desktop=_Desktop(), reorder_native=native,
    )
    obs2 = session2.observe_for("desktop-a")
    # manually inject different parent into the before-tree element
    before = gate._observations[obs2.id]
    before.tree._by_id["uia-1"].states["_uia_parent_runtime_id"] = "rt-parent-b"
    outcome, error = session2.reorder_scene(
        obs2.id, "uia-0", "uia-1", session_id="desktop-a")
    assert outcome is None
    assert error and "parent" in error
    assert not calls


def test_reorder_not_verified_when_order_unchanged():
    def native(src_ref, dst_ref):
        pass  # no-op drag: order stays the same

    session = _authority(
        _tree(y_order=(0, 1)), _tree(y_order=(0, 1)), native,
    )
    observation = session.observe_for("desktop-a")
    outcome, error = session.reorder_scene(
        observation.id, "uia-0", "uia-1", session_id="desktop-a")
    assert error == ""
    assert outcome.executed is True
    assert outcome.verified is False
    assert outcome.ok is False


def test_reorder_verified_when_order_changed():
    def native(src_ref, dst_ref):
        pass  # order changes in the after-frame

    session = _authority(
        _tree(y_order=(0, 1)), _tree(y_order=(1, 0)), native,
    )
    observation = session.observe_for("desktop-a")
    outcome, error = session.reorder_scene(
        observation.id, "uia-0", "uia-1", session_id="desktop-a")
    assert error == ""
    assert outcome.executed is True
    assert outcome.verified is True
    assert outcome.ok is True
