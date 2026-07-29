"""EventBus — thread-safe pub/sub decoupling every subsystem from the UI.

Publishers may call from any thread or drain events shipped from other
processes. Subscribers registered with ``ui=True`` are invoked on the Qt main
thread via the drain timer that MainWindow installs; plain subscribers are
invoked synchronously on the publisher's thread.

Topics in use:
    log            {level, source, message}
    state          {state}                     orb / assistant state
    boot.check     {subsystem, ok, detail}
    boot.done      {online, failed}
    intent         {intent, text, meta}
    amplitude      {level}                     0.0–1.0 mic/TTS level
    vision.frame   {jpeg}                      annotated camera frame
    vision.object  {objects}                   YOLO detections
    vision.gesture {gesture, meta}
    vision.status  {armed, alive, detail}
    browser.nav    {url, title}
    summary.chunk  {text, done, source_url}
    nlp.response   {module, text}
    notify         {title, body}               ambient notifications
    confirm        {}                          pending destructive action approved
    cancel         {}                          pending destructive action rejected
    focus.changed  {active, until}             Focus Mode toggled
    awareness.context {model}                  new ScreenContextModel captured
    awareness.status  {paused}                 screen awareness pause/resume
"""
from __future__ import annotations

import queue
import threading
import traceback
from collections import defaultdict
from typing import Callable

Handler = Callable[[dict], None]


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._ui_subs: dict[str, list[Handler]] = defaultdict(list)
        self._ui_queue: "queue.Queue[tuple[str, dict]]" = queue.Queue()
        self._lock = threading.Lock()

    def subscribe(self, topic: str, handler: Handler, ui: bool = False) -> None:
        with self._lock:
            (self._ui_subs if ui else self._subs)[topic].append(handler)

    def publish(self, topic: str, **data) -> None:
        with self._lock:
            direct = list(self._subs.get(topic, ()))
            has_ui = bool(self._ui_subs.get(topic))
        for fn in direct:
            try:
                fn(data)
            except Exception:
                traceback.print_exc()
        if has_ui:
            self._ui_queue.put((topic, data))

    def drain_ui(self, max_events: int = 64) -> None:
        """Call from the UI thread (Qt timer). Dispatches queued UI events."""
        for _ in range(max_events):
            try:
                topic, data = self._ui_queue.get_nowait()
            except queue.Empty:
                return
            with self._lock:
                handlers = list(self._ui_subs.get(topic, ()))
            for fn in handlers:
                try:
                    fn(data)
                except Exception:
                    traceback.print_exc()


BUS = EventBus()
