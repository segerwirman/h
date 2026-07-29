# J.A.R.V.I.S — Mark XLIX

Minimal-cinematic refactor of Mark XLVIII. The old dense HUD (`ui.py`) is
untouched and still runs via `python main.py`; Mark XLIX lives in `jarvis/`
and reuses the same Gemini Live voice pipeline.

## Run

```
python -m jarvis.main               # full assistant (voice + UI + vision)
python -m jarvis.main --no-voice    # UI/NLP only, no Gemini Live session
python -m jarvis.main --orb-test    # orb state machine, keyboard harness
```

## Layout

```
jarvis/
  ui/          orb.py  stage.py  overlays.py  theme.py  window.py
  core/        bus.py  router.py  boot.py  config.py  llm.py  log.py
  vision/      process.py  yolo.py  gestures.py  filters.py
  browser/     embed.py  extract.py
  nlp/         base.py assistant.py chatbot.py summarize.py translation.py
               document.py search.py predictive.py social.py sentiment.py
               email_filter.py
  main.py
config.yaml    every tunable (colors, thresholds, hotkeys, model ids)
```

## Hotkeys

| Key | Action |
|-----|--------|
| F1  | Sys-stats overlay (also: hover left edge) |
| F2  | Activity log drawer (also: hover right edge) |
| F3  | File upload sheet (also: drag & drop) |
| F4  | Mute microphone *(preserved from Mark XLVIII)* |
| F6  | Vision panel (camera + YOLO + hand skeleton) |
| F8  | Arm / disarm gesture control |
| F11 | Fullscreen *(preserved)* |
| ESC | Interrupt JARVIS mid-speech *(preserved)* |
| Tab | Accept predictive ghost text in the command bar |

## Gesture control

Gesture control is **never active by default**. Arm it with F8 or say
"aktifkan kontrol gestur". While armed the camera panel shows a red ARMED
border. Emergency stop: hold an open palm still for 3 seconds (always
active), or slam the mouse into a screen corner (pyautogui FAILSAFE).

| Gesture | Action |
|---------|--------|
| Open palm | Move cursor (index tip, One-Euro-filtered) |
| Fist / fist→open | Drag / release |
| Pinch (thumb+index) | Left click · twice <400 ms = double click |
| Thumb+middle pinch | Right click |
| Point up / down | Scroll |
| Peace V | Toggle listening |
| Thumbs up / down | Confirm / cancel |
| Both palms → fists | Interrupt (ESC) |
| Swipe left / right | Browser back / forward |
| L-shape | Screenshot |
| Palm hold 3 s | EMERGENCY STOP |

## Hardening (Fase 1-6)

- **Voice pipeline**: correlation `request_id` per perintah, outcome eksplisit
  (`success/timeout/tool_error/...`), tool timeout, response watchdog, TTS
  watchdog — JARVIS tidak pernah diam tanpa penjelasan. Env:
  `JARVIS_TOOL_TIMEOUT_S`, `JARVIS_RESPONSE_TIMEOUT_S`, `JARVIS_MAX_SPEAK_S`.
- **State machine** (`jarvis/core/state.py`): IDLE→LISTENING→TRANSCRIBING→
  PROCESSING→SPEAKING (+WAKING/ERROR/RECOVERING) dengan timeout per state.
- **Double clap** (`jarvis/core/wake.py`): kalibrasi ambient, adaptive noise
  floor, crest/spectral/transient check, debounce+cooldown, echo-suppression
  saat TTS, supervisor restart stream, idempotent. Diagnostik:
  `python -m jarvis.core.wake`. Config: section `wake:` / env `CLAP_*`.
- **DOCX** (`jarvis/nlp/doc_extract.py`): python-docx, resolver tipe via
  signature, error ramah, ringkasan hierarkis untuk dokumen panjang.
- **Relay.app** (`jarvis/integrations/relay/`): webhook aman (HMAC/token,
  replay guard, dedup), client dengan timeout+retry+circuit breaker, tool
  agent read-only. Setup: `docs/RELAY_SETUP.md`.
- **Health**: `python -m jarvis.core.health`. Tests: `python -m pytest tests\ -q`.
- Troubleshooting: `docs/TROUBLESHOOTING.md`. Env template: `.env.example`.

## Architecture notes

- **UI substrate is PyQt6, not Tkinter.** Mark XLVIII was already PyQt6 (the
  Tkinter description in the Mark XLIX brief was inaccurate), the voice
  pipeline marshals through Qt signals, and PyQt6-WebEngine provides the
  embedded Chromium that pywebview cannot embed into any toolkit. The spec's
  design is implemented verbatim on top of it: `OrbRenderer.set_state /
  feed_amplitude / dock / undock`, manual 16 ms redraw loop, three zones,
  cross-fading ContentStage, slide-in overlays.
- **Vision is a separate process** (`multiprocessing`, spawn). Camera, YOLO,
  MediaPipe, gesture recognition and cursor control live there; the UI only
  drains queues. A vision crash cannot take the UI down.
- **Summarization runs only on browser-sourced content**
  (`jarvis/browser/embed.py::summarize_page`); chat never routes through it.
  The source URL is attributed on the summary card.
- **Every subsystem is optional.** Missing weights/deps/keys disable the
  affected module with a log line; nothing hard-crashes.
- **numpy stays on 2.x** in this environment: mediapipe 0.10.13 imports
  cleanly and the installed opencv/ultralytics builds require it. Pin
  numpy<2.0 only if mediapipe actually fails on your machine.
