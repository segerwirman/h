"""Disposable UIA acceptance for selecting one already-open dropdown option."""
from __future__ import annotations

import asyncio
import sys
import threading

from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QComboBox, QVBoxLayout, QWidget


def main() -> int:
    app = QApplication([])
    window = QWidget()
    window.setWindowTitle("Jarvis Safe Select Option Acceptance Fixture")
    dropdown = QComboBox()
    dropdown.setObjectName("jarvis-safe-select-option-fixture")
    dropdown.addItems(["Alpha", "Beta", "Delete all"])
    layout = QVBoxLayout(window)
    layout.addWidget(dropdown)
    window.resize(360, 120)
    window.write_log = lambda _message: None
    window.show()
    window.activateWindow()
    window.raise_()
    dropdown.showPopup()  # Fixture setup only; the desktop-safe tool never opens it.

    from jarvis.agent.adapters.ui import UIAdapter, ask_active
    from jarvis.core.bus import BUS
    adapter = UIAdapter(window)
    outcome: dict = {}

    def worker() -> None:
        try:
            from pywinauto import Desktop
            from jarvis.agent import registry
            from jarvis.agent.execution_context import ExecutionContext
            from jarvis.agent.tools import desktop_observe, desktop_safe_select_option
            from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
            from jarvis.automation.cua_safe_click import CaptureAdapter
            from jarvis.automation.cua_safety import CuaSafetyGate
            from jarvis.automation.uia_capture import UIACaptureBackend

            wrapper = Desktop(backend="uia").window(handle=int(window.winId())).wrapper_object()
            backend = UIACaptureBackend(
                desktop=type("FixtureDesktop", (), {"get_active": lambda self: wrapper})(),
                max_elements=100,
            )
            gate = CuaSafetyGate(max_age_s=10)
            authority = SafeDesktopSession(
                gate, CaptureAdapter(gate, backend.capture), lambda _rect: None,
                select_option_native=backend.select_option_semantic,
            )
            tools = registry.all_tools(refresh=True)
            for module in (desktop_observe, desktop_safe_select_option):
                module.desktop_safe_session = lambda: authority
            tools["desktop_observe"]._session = authority
            tools["desktop_safe_select_option"]._session = authority

            class Session:
                id = "cua-select-option-acceptance"

                def record_tool(self, *_):
                    pass

            context = ExecutionContext.create(
                source="agent", actor_id="local-user", session_id=Session.id,
                surface="desktop", toolsets=["desktop_safe"],
            )
            observed = asyncio.run(registry.execute(
                "desktop_observe", {}, session=Session(), context=context))
            if not observed.ok:
                raise RuntimeError("observe_failed")
            options = [item for item in observed.content["elements"]
                       if item.get("role") == "dropdown_option"]
            target = options[1] if len(options) > 1 else None
            if target is None:
                raise RuntimeError("safe_option_not_found")
            before = dropdown.currentIndex()
            result = asyncio.run(registry.execute(
                "desktop_safe_select_option",
                {"observation_id": observed.content["observation_id"],
                 "element_id": target["element_id"]},
                adapter=adapter, session=Session(), context=context,
            ))
            outcome.update(result=result, before=before, authority=authority,
                           target_id=target["element_id"])
        except Exception as exc:
            outcome.update(error_type=type(exc).__name__)

    def finish_when_ready() -> None:
        if not outcome:
            QTimer.singleShot(50, finish_when_ready)
            return
        QTest.qWait(250)
        if "error_type" in outcome:
            print({"accepted": False, "reason": "fixture_failed", "error_type": outcome["error_type"]})
        else:
            result = outcome["result"]
            after_observation = outcome["authority"].gate._observations.get(
                result.meta.get("after_observation_id", ""))
            after_element = (after_observation.tree._by_id.get(outcome["target_id"])
                             if after_observation else None)
            selected = bool(after_element and after_element.states.get("selected"))
            accepted = bool(result.ok and selected)
            print({
                "accepted": accepted,
                "executed": result.meta.get("executed"),
                "verified": result.meta.get("verified"),
                "marker_changed": selected,
                "error": "" if accepted else "fixture_failed",
            })
        app.quit()

    def confirm_when_pending() -> None:
        if ask_active():
            BUS.publish("confirm")
            return
        if not outcome:
            QTimer.singleShot(25, confirm_when_pending)

    QTimer.singleShot(750, lambda: threading.Thread(target=worker, daemon=True).start())
    QTimer.singleShot(775, confirm_when_pending)
    QTimer.singleShot(800, finish_when_ready)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
