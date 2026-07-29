# Architecture Inventory — Framework Maturity Phase 0

## Scope and native boundary

| Item | Current state | Decision |
|---|---|---|
| Active desktop entry | `python -m jarvis.main` | Canonical desktop launch |
| Root `main.py` / `ui.py` | Legacy voice/UI compatibility path | Frozen behavior/identity; modify only through approved seams |
| Hermes source | `hermes-agent-main/` may exist beside the repo | Read-only design reference; never a Jarvis runtime dependency |
| Hermes bridge | `jarvis/integrations/hermes/*` | disabled by default; native Jarvis gateway supersedes it |
| Frozen contract | `config/frozen_manifest.json` + `scripts/verify_frozen.py` | Must pass or have an explicitly recorded approved exception |

## Runtime layers

| Layer | Paths | State | Responsibility |
|---|---|---|---|
| Core runtime | `core/`, `jarvis/core/` | active | config, secure storage, voice, state, settings, release controls |
| Agent | `jarvis/agent/` | active | router, providers, dispatch, loop, tools, lifecycle, context, skills, cron, MCP |
| UI | `jarvis/ui/` | active | orb, window, panels, settings, management surface |
| Gateway | `jarvis/gateway/`, `jarvis/agent/adapters/telegram.py` | active foundation | normalized Telegram ingress, dedup, delivery boundary |
| Integrations | `jarvis/integrations/` | lazy-active | OAuth, Google, Telegram control, relay, YouTube |
| Dashboard | `dashboard/` | lazy-active | authenticated management/control surface |
| Browser/Vision | `jarvis/browser/`, `jarvis/vision/` | lazy-active | contextual browser and sensor capabilities |
| Tests/scripts/docs | `tests/`, `scripts/`, `docs/` | development/ops | regression, verification, runbooks |

## Legacy helper reachability and modernization queue

| Helper | Known callers | State | Latency class | Safety class | Modernization owner |
|---|---|---|---|---|---|
| `actions/browser_control.py` | root `main.py`, `flight_finder.py` | active | high cold-start/network | browser mutation | Phase 3/4 browser service |
| `actions/file_controller.py` | root `main.py` | active | low/local I/O | file write/delete | Phase 3 capability adapter |
| `actions/computer_control.py` | root `main.py` | active | medium OS automation | desktop control | Phase 3/4 desktop service |
| `actions/desktop.py` | root `main.py` | active | medium OS automation | desktop control | Phase 3/4 desktop service |
| `actions/youtube_video.py` | root `main.py` | active | high network/browser | browser/media | Phase 3 cache/reuse adapter |
| `actions/weather_report.py` | root `main.py` | active | medium browser/network | read-only web | Phase 3 TTL cache adapter |
| `actions/dev_agent.py` | root `main.py` | active | high LLM/subprocess | code/process | Phase 3 resource pool/approval adapter |
| `actions/send_message.py` | root `main.py` | active | medium network | external messaging | Phase 3 queue; Phase 10 gateway |
| `actions/computer_settings.py` | root `main.py`, `window.py`, Telegram light adapter | active | medium subprocess | desktop state | Phase 3 native/cached adapter |
| `actions/screen_processor.py` | root `main.py` | active | high capture/model | privacy/vision | Phase 3 frame budget + consent |
| `actions/open_app.py` | root `main.py`, `window.py`, Telegram light adapter | active | medium process spawn | desktop launch | Phase 3 desktop adapter |
| `actions/hermes_action.py` | compatibility tests only | compatibility-only | external process | external runtime bridge | remain disabled; retire after native parity |

## Baseline findings

1. Root-level `pytest -q` previously discovered nested external test trees. `pytest.ini` now scopes collection to `tests`.
2. `tests/test_curator.py` encodes obsolete automatic archive expectations. Current Phase 9 curator contract is review-first: automatic maintenance marks stale; physical archive is explicit and recoverable.
3. `main.py` differs from the frozen hash because approved maturity work wired deterministic delivery/context into its legacy seam. The freeze baseline must be refreshed only after focused regression and this inventory are accepted.
4. Workspace contains uncommitted changes from earlier maturity phases. Phase-by-phase tests must be used until a clean committed baseline exists.

## Phase 0 exit conditions

- `pytest -q` discovers only Jarvis `tests/`.
- Inventory and test accurately state legacy reachability.
- Curator tests match adopted review-first contract.
- Frozen manifest refresh is performed only after targeted regression and documented approval.
- No runtime path invokes Hermes when `integrations.hermes.enabled` is false.
