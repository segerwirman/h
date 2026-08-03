"""Disposable UIA acceptance for toggling one binary visible checkbox."""
from __future__ import annotations

import asyncio
import sys
import threading


def main() -> int:
    from PyQt6.QtCore import QTimer
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QCheckBox, QVBoxLayout, QWidget

    from jarvis.agent import registry
    from jarvis.agent.adapters.ui import UIAdapter, ask_active
    from jarvis.agent.execution_context import ExecutionContext
    from jarvis.agent.tools import desktop_observe, desktop_safe_toggle
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.uia_capture import UIACaptureBackend
    from jarvis.core.bus import BUS

    app = QApplication.instance() or QApplication([])
    window = QWidget()
    checkbox = QCheckBox("Enable disposable safe mode")
    layout = QVBoxLayout(window)
    layout.addWidget(checkbox)
    window.resize(360, 120)
    window.write_log = lambda _message: None
    window.show()
    window.activateWindow()
    window.raise_()

    backend = UIACaptureBackend()
    gate = CuaSafetyGate()
    authority = SafeDesktopSession(
        gate=gate,
        capture=CaptureAdapter(gate, backend.capture),
        click_rect=lambda _rect: None,
        set_value_native=backend.set_slider_value,
        toggle_native=backend.toggle_checkbox_semantic,
        select_option_native=backend.select_option_semantic,
        click_native=backend.click_semantic,
        scroll_native=backend.scroll_semantic,
    )
    context = ExecutionContext.create(
        source="agent", actor_id="local", session_id="fixture-toggle", surface="desktop",
        toolsets=["desktop_safe"],
    )
    adapter = UIAdapter(window)
    outcome: dict = {}

    def worker() -> None:
        try:
            tools = registry.all_tools(refresh=True)
            for module in (desktop_observe, desktop_safe_toggle):
                module.desktop_safe_session = lambda: authority
            tools["desktop_observe"]._session = authority
            tools["desktop_safe_toggle"]._session = authority

            class Session:
                id = "fixture-toggle"

                def record_tool(self, *_):
                    pass

            observed = asyncio.run(registry.execute(
                "desktop_observe", {}, session=Session(), context=context))
            if not observed.ok:
                raise RuntimeError("fixture_observe_failed")
            target = next((item for item in observed.content["elements"]
                           if item.get("role") == "checkbox"), None)
            if target is None:
                raise RuntimeError("fixture_checkbox_not_observed")
            result = asyncio.run(registry.execute(
                "desktop_safe_toggle",
                {"observation_id": observed.content["observation_id"],
                 "element_id": target["element_id"]},
                adapter=adapter, session=Session(), context=context,
            ))
            outcome.update(result=result, authority=authority, target_id=target["element_id"])
        except Exception as exc:
            outcome["error"] = "fixture_failed"
            outcome["debug_error_type"] = type(exc).__name__

    def finish_when_ready() -> None:
        if not outcome:
            QTimer.singleShot(25, finish_when_ready)
            return
        QTest.qWait(250)
        if outcome.get("error"):
            print({"accepted": False, "reason": "fixture_failed", "debug_error_type": outcome.get("debug_error_type", "")})
        else:
            result = outcome["result"]
            after = outcome["authority"].gate._observations.get(
                result.meta.get("after_observation_id", ""))
            element = after.tree._by_id.get(outcome["target_id"]) if after else None
            checked = bool(element and element.states.get("checked") is True)
            accepted = bool(result.ok and checked)
            print({
                "accepted": accepted,
                "executed": result.meta.get("executed"),
                "verified": result.meta.get("verified"),
                "marker_changed": checked,
                "error": "" if accepted else "fixture_failed",
            })
        app.quit()

    def confirm_when_pending() -> None:
        if ask_active():
            BUS.publish("confirm")
            return
        if not outcome:
            QTimer.singleShot(25, confirm_when_pending)

    QTimer.singleShot(500, lambda: threading.Thread(target=worker, daemon=True).start())
    QTimer.singleShot(525, confirm_when_pending)
    QTimer.singleShot(550, finish_when_ready)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
