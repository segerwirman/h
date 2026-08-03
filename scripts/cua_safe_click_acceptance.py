"""Manual Windows-only acceptance for the narrow UIA safe-click path.

Creates an isolated, disposable PyQt fixture. It never targets user apps or
user data. The script proves UIA capture → semantic ref → one left-click → UIA
recapture and prints only IDs/statuses, not window/control text.
"""
from __future__ import annotations

import sys
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget, QVBoxLayout


def main() -> int:
    app = QApplication([])
    window = QWidget()
    window.setWindowTitle("Jarvis Safe Click Acceptance Fixture")
    button = QPushButton("Safe test action")
    button.setObjectName("jarvis-safe-click-fixture")
    button.clicked.connect(lambda: button.setText("Verified"))
    layout = QVBoxLayout(window)
    layout.addWidget(button)
    window.resize(320, 150)
    window.show()
    window.activateWindow()
    window.raise_()

    def prove() -> None:
        try:
            from jarvis.automation.cua_safe_click import CaptureAdapter
            from jarvis.automation.cua_safety import CuaSafetyGate
            from jarvis.automation.uia_capture import UIACaptureBackend, UIASafeClickService

            # Bind UIA to this disposable fixture HWND explicitly. The Hermes
            # terminal may remain foreground while this acceptance window runs,
            # so relying on global foreground selection would test the wrong UI.
            from pywinauto import Desktop
            wrapper = Desktop(backend="uia").window(handle=int(window.winId())).wrapper_object()
            backend = UIACaptureBackend(
                desktop=type("FixtureDesktop", (), {"get_active": lambda self: wrapper})(),
                max_elements=150,
            )
            gate = CuaSafetyGate(max_age_s=10)
            adapter = CaptureAdapter(gate, backend.capture)
            before = adapter.capture()
            target = next((element for scope in before.tree.scopes()
                           for element in before.tree.by_scope(scope)
                           if element.name == "Safe test action"), None)
            if target is None:
                raise RuntimeError("semantic fixture target not found")
            gate.reference(before.id, target.element_id)
            events: list[tuple[str, dict]] = []
            from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession

            authority = SafeDesktopSession(
                gate, adapter, click_rect=lambda _rect: None,
                click_native=backend.click_semantic,
            )
            authority._owners[before.id] = "cua-acceptance-fixture"
            result, error = authority.click(
                before.id, target.element_id, session_id="cua-acceptance-fixture",
            )
            if result is None:
                raise RuntimeError(error)
            # Let Windows deliver the physical mouse message and Qt process it
            # before asserting the disposable fixture's visible state.
            from PyQt6.QtTest import QTest
            QTest.qWait(200)
            if not result.ok or button.text() != "Verified":
                raise RuntimeError(
                    f"safe click did not verify fixture state "
                    f"(ok={result.ok}, executed={result.executed}, verified={result.verified}, "
                    f"reason={result.reason!r}, button_state={button.text()!r})"
                )
            print({
                "accepted": True,
                "executed": result.executed,
                "verified": result.verified,
                "audit_events": [name for name, _ in events],
            })
        except Exception as exc:  # honest fixture failure report
            print({"accepted": False, "error_type": type(exc).__name__, "detail": str(exc)[:180]})
        finally:
            app.quit()

    QTimer.singleShot(750, prove)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
