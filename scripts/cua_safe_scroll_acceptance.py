"""Disposable UIA registry acceptance for desktop_safe_scroll on Windows."""
from __future__ import annotations

import asyncio
import sys
import threading

from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QScrollArea, QVBoxLayout, QWidget


def main() -> int:
    app = QApplication([])
    window = QWidget()
    window.setWindowTitle("Jarvis Safe Scroll Acceptance Fixture")
    scroll_area = QScrollArea()
    scroll_area.setObjectName("jarvis-safe-scroll-fixture")
    scroll_area.setWidgetResizable(True)
    content = QWidget()
    content_layout = QVBoxLayout(content)
    for index in range(80):
        content_layout.addWidget(QLabel(f"fixture row {index}"))
    scroll_area.setWidget(content)
    layout = QVBoxLayout(window)
    layout.addWidget(scroll_area)
    window.resize(360, 220)
    window.show()

    outcome: dict = {}

    def worker() -> None:
        try:
            from pywinauto import Desktop
            from jarvis.agent import registry
            from jarvis.agent.execution_context import ExecutionContext
            from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
            from jarvis.agent.tools import desktop_observe, desktop_safe_click, desktop_safe_scroll
            from jarvis.automation.cua_safe_click import CaptureAdapter
            from jarvis.automation.cua_safety import CuaSafetyGate
            from jarvis.automation.uia_capture import UIACaptureBackend

            wrapper = Desktop(backend="uia").window(handle=int(window.winId())).wrapper_object()
            backend = UIACaptureBackend(
                desktop=type("FixtureDesktop", (), {"get_active": lambda self: wrapper})(),
                max_elements=150,
            )
            gate = CuaSafetyGate(max_age_s=10)
            adapter = CaptureAdapter(gate, backend.capture)

            authority = SafeDesktopSession(
                gate, adapter, lambda _rect: None,
                scroll_rect=lambda _rect, _delta: None,
                scroll_native=backend.scroll_semantic,
            )
            tools = registry.all_tools(refresh=True)
            for module in (desktop_observe, desktop_safe_click, desktop_safe_scroll):
                module.desktop_safe_session = lambda: authority
            tools["desktop_observe"]._session = authority
            tools["desktop_safe_scroll"]._session = authority

            class Session:
                id = "cua-scroll-acceptance"
                def record_tool(self, *_):
                    pass

            context = ExecutionContext.create(
                source="agent", actor_id="local-user", session_id=Session.id,
                surface="desktop", toolsets=["desktop_safe"],
            )
            observed = asyncio.run(registry.execute(
                "desktop_observe", {}, session=Session(), context=context))
            if not observed.ok:
                raise RuntimeError(f"observe failed: {observed.error}")
            target = next((item for item in observed.content["elements"]
                           if item["role"] == "scrollbar"), None)
            if target is None:
                raise RuntimeError("semantic scrollbar not found")
            before = scroll_area.verticalScrollBar().value()
            result = asyncio.run(registry.execute(
                "desktop_safe_scroll",
                {"observation_id": observed.content["observation_id"],
                 "element_id": target["element_id"], "direction": "down"},
                session=Session(), context=context,
            ))
            outcome.update(result=result, before=before)
        except Exception as exc:
            outcome.update(error_type=type(exc).__name__, detail=str(exc)[:220])

    def finish_when_ready() -> None:
        if not outcome:
            QTimer.singleShot(50, finish_when_ready)
            return
        QTest.qWait(250)
        if "error_type" in outcome:
            print({"accepted": False, **outcome})
        else:
            result = outcome["result"]
            after = scroll_area.verticalScrollBar().value()
            accepted = bool(result.ok and after > outcome["before"])
            print({
                "accepted": accepted,
                "executed": result.meta.get("executed"),
                "verified": result.meta.get("verified"),
                "marker_changed": after > outcome["before"],
                "error": result.error if not accepted else "",
            })
        app.quit()

    QTimer.singleShot(750, lambda: threading.Thread(target=worker, daemon=True).start())
    QTimer.singleShot(800, finish_when_ready)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
