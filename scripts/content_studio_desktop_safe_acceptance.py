"""Phase 21 — Content Studio production-path fixture acceptance (title + reorder).

Manual Windows-only acceptance. Creates an isolated, disposable PyQt fixture;
it never targets user apps or user data. Proves the production UIA path:
capture -> semantic ref -> set_content_title (ValuePattern) and reorder_scene
(one native drag) -> recapture verification, plus stale-ref and source==destination
rejection. Prints metadata-only payload (no window/field text, no path, no
coordinates, no raw exceptions).
"""
from __future__ import annotations

import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

_TITLE = "Judul Fixture Aman"
_OWNER = "content-studio-acceptance-fixture"
_SCENES = ("Scene A", "Scene B", "Scene C")


def _accept(payload: object) -> bool:
    """Accept only a bounded verified status payload for both blocks."""
    if not isinstance(payload, dict) or payload.get("accepted") is not True:
        return False
    title = payload.get("title")
    reorder = payload.get("reorder")
    return bool(
        isinstance(title, dict)
        and title.get("executed") is True
        and title.get("verified") is True
        and isinstance(reorder, dict)
        and reorder.get("executed") is True
        and reorder.get("verified") is True
    )


def _elements(tree, role: str) -> list:
    return [element for scope in tree.scopes()
            for element in tree.by_scope(scope)
            if element.role == role]


def main() -> int:
    app = QApplication([])
    window = QWidget()
    window.setWindowTitle("Jarvis Content Studio Acceptance Fixture")
    layout = QVBoxLayout(window)

    label = QLabel("Judul Project")
    label.setObjectName("jarvis-fixture-title-label")
    line_edit = QLineEdit()
    line_edit.setObjectName("jarvis-fixture-title")
    line_edit.setAccessibleName("Judul Project")
    label.setBuddy(line_edit)
    layout.addWidget(label)
    layout.addWidget(line_edit)

    scene_list = QListWidget()
    scene_list.setObjectName("jarvis-fixture-scenes")
    scene_list.setAccessibleName("Daftar Scene")
    scene_list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
    scene_list.setDefaultDropAction(Qt.DropAction.MoveAction)
    for name in _SCENES:
        scene_list.addItem(QListWidgetItem(name))
    layout.addWidget(scene_list)

    window.resize(420, 320)
    window.show()
    window.activateWindow()
    window.raise_()

    def prove() -> None:
        try:
            from PyQt6.QtTest import QTest
            from jarvis.automation.cua_safe_click import CaptureAdapter
            from jarvis.automation.cua_safety import CuaSafetyGate
            from jarvis.automation.uia_capture import UIACaptureBackend
            from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
            from pywinauto import Desktop

            # Bind UIA to this disposable fixture HWND explicitly; the terminal
            # may remain foreground while this acceptance window runs.
            wrapper = Desktop(backend="uia").window(handle=int(window.winId())).wrapper_object()
            backend = UIACaptureBackend(
                desktop=type("FixtureDesktop", (), {"get_active": lambda self: wrapper})(),
                max_elements=200,
            )
            gate = CuaSafetyGate(max_age_s=10)
            adapter = CaptureAdapter(gate, backend.capture)
            authority = SafeDesktopSession(
                gate=gate, capture=adapter, click_rect=lambda _rect: None,
                set_text_native=backend.set_text_field_value,
                reorder_native=backend.reorder_semantic,
            )

            # ── 21A: title through production ValuePattern path ──
            before = adapter.capture()
            title_el = next((element for element in _elements(before.tree, "text_field")
                             if element.name == "Judul Project"), None)
            if title_el is None:
                raise RuntimeError("semantic title field not found")
            gate.reference(before.id, title_el.element_id)
            authority._owners[before.id] = _OWNER
            t_outcome, t_error = authority.set_content_title(
                before.id, title_el.element_id, title=_TITLE, session_id=_OWNER)
            if t_outcome is None:
                raise RuntimeError(t_error)
            QTest.qWait(150)
            local_title_ok = line_edit.text() == _TITLE

            # stale ref rejection: observation sudah di-disown oleh setter
            stale_outcome, stale_error = authority.set_content_title(
                before.id, title_el.element_id, title=_TITLE, session_id=_OWNER)
            stale_rejected = stale_outcome is None and bool(stale_error)

            # ── 21B: scene reorder through one native drag ──
            obs2 = adapter.capture()
            items = sorted(_elements(obs2.tree, "listitem"), key=lambda el: el.rect[1])
            if len(items) < 3:
                raise RuntimeError("semantic scene cards not found")
            src_id = items[0].element_id
            dst_id = items[2].element_id
            if items[0].states.get("_uia_parent_runtime_id") != items[2].states.get("_uia_parent_runtime_id"):
                raise RuntimeError("scene cards do not share one parent")
            gate.reference(obs2.id, src_id)
            gate.reference(obs2.id, dst_id)
            authority._owners[obs2.id] = _OWNER

            # source==destination rejection (observation stays active)
            same_outcome, same_error = authority.reorder_scene(
                obs2.id, src_id, src_id, session_id=_OWNER)
            same_rejected = same_outcome is None and bool(same_error)

            r_outcome, r_error = authority.reorder_scene(
                obs2.id, src_id, dst_id, session_id=_OWNER)
            if r_outcome is None:
                raise RuntimeError(r_error)
            QTest.qWait(300)
            order = tuple(scene_list.item(i).text() for i in range(scene_list.count()))
            local_reorder_ok = order != _SCENES and order[0] != _SCENES[0]

            accepted = bool(
                t_outcome.ok and t_outcome.verified and local_title_ok
                and stale_rejected
                and r_outcome.ok and r_outcome.verified and local_reorder_ok
                and same_rejected)
            print({
                "accepted": accepted,
                "executed": bool(t_outcome.executed and r_outcome.executed),
                "verified": bool(t_outcome.verified and r_outcome.verified),
                "title": {"executed": t_outcome.executed, "verified": t_outcome.verified},
                "reorder": {"executed": r_outcome.executed, "verified": r_outcome.verified},
            })
        except Exception as exc:  # honest fixture failure report
            print({"accepted": False, "error_type": type(exc).__name__,
                   "detail": str(exc)[:180]})
        finally:
            app.quit()

    QTimer.singleShot(750, prove)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
