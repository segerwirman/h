# UI U2 — Legacy Screen Awareness Assessment

**Scope:** static read-only source/AST reference audit plus focused denylist extraction.
**Runtime entry point assessed:** `python -m jarvis.main` (`jarvis/main.py`).
**No watcher deletion is proposed or performed.**

## Startup / lifecycle flow

```text
jarvis.main.run()
  → imports screen_awareness only to register supervisor stop callback
  → screen_awareness.get().stop registered at main.py:289–290
  → no ScreenAwareness.start() call on bootstrap

MainWindow local action/palette
  → _toggle_awareness() at jarvis/ui/window.py:1673
  → screen_awareness.get() at :1678
  → start/pause/resume only after explicit local interaction
```

## Consumer classification

| Consumer | Classification | Evidence | Notes |
|---|---|---|---|
| `jarvis.core.screen_awareness.ScreenAwareness` | Legacy component reused | `screen_awareness.py:107–295` | Owns daemon watcher, snapshot retention, optional OCR, BUS producer. Constructed only via `get()`; test proves construction does not start thread. |
| `jarvis.main` supervisor stop hook | Optional active lifecycle cleanup | `main.py:288–292` | Registers `.stop`, does not call `.start`; safe even when watcher never starts. |
| `jarvis.ui.window._toggle_awareness` | Lazy active local UI | `window.py:632`, `:1619`, `:1673–1695` | Signal/palette action can start watcher only after explicit local action. Icon retired from default at UI U1 but handler retained for opt-in config/palette. |
| `jarvis.core.proactive_signals` | Optional/legacy consumer | `proactive_signals.py:97–106` | Defines idempotent BUS subscription, but repository-wide reference scan found no production caller to `subscribe()`; no evidence it is active in current entry path. |
| `jarvis.automation.uia_capture.UIACaptureBackend` | Lazy active shared privacy consumer | `uia_capture.py:22`, `:59–69` | Uses shared privacy matcher before semantic UIA tree extraction; does not import watcher. |
| `jarvis.automation.visual_observe.VisualObserveService` | Lazy active shared privacy consumer | `visual_observe.py:6`, `:12–29` | Uses shared privacy matcher before one-frame in-memory summary; no watcher import. |
| `jarvis.core.privacy_denylist` | Active shared pure helper when capture lanes execute | `privacy_denylist.py:1–17` | New additive, config-backed string matcher. No capture, persistence, action, or transport authority. |

## Event dataflow

```text
ScreenAwareness._capture()
  → BUS.publish("awareness.context", model=ScreenContextModel)
  → proactive_signals._on_awareness only if proactive_signals.subscribe() was called

No other producer/consumer found in repo-wide reference scan.
```

## Risk / decision

- The legacy watcher can persist screenshots and invoke optional OCR when explicitly started; it remains a separate lane from the newer in-memory `VisualObserveService`.
- Shared denylist extraction removes `uia_capture` / `visual_observe` dependency on watcher internals without changing watcher lifecycle or capture policy.
- Do **not** prune `screen_awareness`, its handler, or `proactive_signals` based solely on this assessment. A separate, explicitly approved prune phase would require runtime evidence and dedicated migration tests.

## Verification

```text
Focused privacy/helper + UIA/visual regressions: 40 passed
Focused privacy helper/default-off regression: 6 passed
```

## Changed files

```text
jarvis/core/privacy_denylist.py
jarvis/core/screen_awareness.py
jarvis/automation/uia_capture.py
jarvis/automation/visual_observe.py
tests/test_privacy_denylist.py
tests/test_cua_uia_safe_click.py
```

## Boundaries

This assessment used static source/AST/reference scans and focused tests only. It did not start the GUI, camera, screenshot capture, OCR, browser, provider, remote service, or watcher thread.

No frozen file was modified.
