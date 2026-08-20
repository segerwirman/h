# P1-A — Executor/Classifier Route Map (read-only audit)

**Status:** Read-only inventory for roadmap P1. No source changes made. Evidence: `focused-tested` via characterization assertions in `test_gui_p1a_route_map.py`.

## 1. Overview: Input-to-Owner Path

```text
typed input → resolve_typed_action() → classifier → execution lanes → result → task/UI output
voice input → reply_flow.handle_utterance() → [clarify] or handle_command(text)
```

Every path eventually reaches one of the following owners: deterministic L0/L1, T1 tool, T2+ agent native, or chat fallback.

## 2. Owned Functions & Call Graph

### 2.1 Entry point: `CommandRoutingMixin.handle_command()` (`jarvis/ui/window_commands.py`)

Location: lines 48–115 in Mark XLIX `MainWindow` composition (injected as mixin).

```python
def handle_command(self, text: str) -> None:
    self._skip_next_intercept = True          # voice intercept gate
    self.write_log(f"You: {text}")            # logging owner: MainWindow

    if _agent_ask_active():                   # clarification gate
        confirm/cancel handling → BUS.confirm/cancel publish
        return
    if self.reply_flow.handle_utterance(text): # clarify answer owner
        return                                 # handled; no routing
    if self._confirm_self_shutdown(text):      # shutdown confirmation
        return
    if self._handle_clarify_answer(text):      # secondary clarify gate
        return

    local = resolve_typed_action(text)         # resolver seam ↓
    def _execute_local(action) → confirmation
    if isinstance(local, Action):              # L0/L1 determinism owner
        execute_typed_action(action)           # L1 executor
        return
    elif isinstance(local, ClarifyNeeded):     # ambiguous target
        write_log(jarvis question)
        return
    route = classify_execution(text, {"source": "text"})   # router seam ↓
    if route.tier >= AGENT:                    # T2+ delegate lane
        _run_agent_native(task)                # MK50 ACK owner
        return
    if google_direct.match_command(text):      # T1 light lane
        _run_google_light(*google_call)        # Google registry executor
        return
    c = self.router.classify(text)             # legacy intent router fallback
    BUS.publish("intent", ...)                 # event seam
    _dispatch_command(c, text)                 # dispatch owner ↓
```

---

### 2.2 Resolver seam: `resolve_typed_action()` / `resolve()` (`jarvis/core/resolver.py`)

Location: `jarvis/core/resolver.py`, functions `_l0`, `_l1`, `_palette`, `resolve`.

Responsibility: **L0/L1 deterministic resolution**. Does NOT classify conversation. Returns one of three outcomes:

| Return type | Owner | Thread | Failure behavior |
|-------------|-------|--------|------------------|
| `Action` | `execute_typed_action()` | inline (asyncio.run) | ValueError pass |
| `ClarifyNeeded` | write log + wait for user | UI (synchronous) | blocked until reply |
| `FallthroughToLLM` | fall through to router | N/A | falls to next seam |

Sub-seams:
- `_l0`: explicit prefix `/open|close|panel <target>` → single action match → `Action(..., reason="L0")` or `ClarifyNeeded` on ambiguity
- `_l1`: imperative verb parsing + entity lookup → `Action(..., reason="L1")` or `FallthroughToLLM`
- `_palette`: wrapper around `_l0` for command palette trigger

Thread boundaries:
- Resolver runs **on UI thread** at call site (P5-B pattern)
- `execute_typed_action(action)` runs **inline** via `asyncio.run()` (no daemon thread; `ValueError` returns `None` silently)
- No provider/network/audio calls inside resolver itself

---

### 2.3 Classifier seam: `classify_execution()` (`jarvis/ui/window_commands.py`)

Location: line 20–26 in `window_commands.py`.

```python
def classify_execution(text: str, context: dict) -> Route:
    window = sys.modules.get("jarvis.ui.window")
    override = getattr(window, "classify_execution", None)
    if override is not None and override is not classify_execution:
        return override(text, context)       # user injection seam preserved
    return _classify_execution_default(text, context)  # router.py default
```

Default classifier: `jarvis/agent/router.py`, function `classify` (not shown here; reads config key `agent.router.use_classifier`).

Route contract:

```python
@dataclass(frozen=True)
class Route:
    tier: Tier (REFLEX=0, SINGLE=1, AGENT=2, DELEGATE=3, AUTONOMOUS=4)
    lane: str ("local" | "tool" | "agent" | "chat")
    model_profile: str
    reason: str
    confidence: float
```

Injection seam: `window.classify_execution` attribute can be overridden by tests/fixtures without modifying file contents.

---

### 2.4 Execution lanes

#### Lane A: T2+ agent native (`_run_agent_native(task)`)

Location: `jarvis/ui/window_actions.py`, lines 283–390.

Owner modules:
- `jarvis.agent.conversation_context` — artifact reference resolution, STORE augment/resolve
- `jarvis.agent.interactive_dispatch` — dispatch to ack flow
- `jarvis.agent.delivery_lifecycle` — acknowledged/success lifecycle
- `jarvis.agent.adapters.ui.UIAdapter` — weak-reference delivery surface

Call graph:
1. `self.orb.set_state(OrbState.EXECUTING)` → orb state change
2. `_record_task_result("TUGAS", task)` → logging owner
3. `_on_task(metadata)` → `conversation_context.STORE.begin_task()`
4. `_on_ack(raw, report)` → `delivery_lifecycle.acknowledged("typed", report)`
5. `_on_done(result, report)` → `delivery_lifecycle.success(...)`, `write_log`, `_content_sig.emit`, `_speak_line`
6. finally: `orb.set_state(IDLE)` → restore

Failure behaviors:
- Ambiguous resolution: write_log + speak question, **no task started** (owner: UI adapter gate)
- Async errors: terminal delivery via `_typed_terminal_fallback()` (write_log OR _content_sig OR both)
- No second speech owner created; async callbacks run in the unnamed worker's async context

Thread: worker thread (no named daemon; callbacks `_on_task`/`_on_ack`/`_on_done` run in async context from `interactive_dispatch`).

#### Lane B: T1 light tool (`_run_deterministic_tool()` / `_run_google_light()`)

Locations: `window_commands.py` lines 157–188 and 189–227 (not `window_actions.py`).

Shared structure:
1. `self.orb.set_state(THINKING)`
2. worker thread `target=work()` with asyncio.run(registry.execute())
3. try: success/failure log + speech
4. finally: `orb.set_state(IDLE)`

Owner registries:
- `jarvis.agent.registry` — deterministic tools registry
- `jarvis.integrations.google_direct` — Google Cloud gating + unavailable message

Failure: honest error reporting via write_log + speech; never swallow provider API errors into silence.

Thread: worker thread `"deterministic-tool"` or `"google-light-{tool_name}"` (daemon).

#### Lane C: Legacy command dispatch (`_dispatch_command(c, text)`)

Location: `window_commands.py` lines 117–155.

Cases:
- `Intent.SEARCH_WEB` → `run_search()` / `run_information()` / `run_news()` → `web_search()` worker
- `Intent.OPEN_URL` → `open_url(url)` (browser control seam)
- `Intent.OPEN_BROWSER_AGENT` → `open_browser_agent(slots)` (embedded browser seam)
- `Intent.CLARIFY` → `_ask_clarify()` (dialogue seam)
- `Intent.OPEN_APP` → `open_app(app)` (app launcher)
- `Intent.SYSTEM` → `run_system(slots, text)` (system control)
- `Intent.NATIVE_AGENT_TASK` → `run_native_task()`
- else: deterministic tool check via `tier_router.deterministic_tool()` + `registry.get()` → `_run_deterministic_tool()` OR `_chat()`

Fallback: `_chat()` is final catch-all for conversational LLM.

---

### 2.5 Chat fallback (`_chat(text)`)

Location: `window_actions.py` lines 503–537.

Owners:
- `assistant.handle_blocking(text)` → `JarvisLive.assistant` (Gemini Live client)
- `document_explanation` check via `DocumentAnalysis.is_explanation_request()` → document coordinator seam
- Delivery via `write_log()` OR `_content_sig.emit()` OR both (weak-reference surface pattern)

Failure behavior: if assistant None → write "ERR: tidak ada kanal percakapan yang aktif." immediately (UI-first safety).

Thread: worker thread `"nlp-chat"` (daemon).

---

## 3. Cross-Cutting Concerns

### 3.1 State transitions
- `ORB.THINKING`: deterministic tools (L1/T1), web lookups
- `ORB.EXECUTING`: native agent tasks (T2+)
- `ORB.IDLE`: restoration after completion/error

### 3.2 Logging seams
- `write_log()` invoked by every lane; owns the canonical record buffer
- `_speak_line()` called after successful completion only (never during error paths that rely on write_log alone)

### 3.3 Clarification gates
Before ANY routing:
1. `_agent_ask_active()` → confirm/cancel word detection
2. `reply_flow.handle_utterance()` → CONFIRM/batal processing
3. `_confirm_self_shutdown()` → self-shutdown confirmation
4. `_handle_clarify_answer()` → pending clarification answer

These are **priority filters**; if matched, NO classification occurs. This prevents "aplikasi" from being reclassified when clarifying a prior ambiguity.

### 3.4 Injection seams (tests/fixtures)
- `window.classify_execution` override → testable without network
- `window.on_text_command = cb` → capture submitted inputs (P5-D/C pattern)
- `window.on_interrupt` → interrupt handler registration
- `window._content_sig` → stage content signal emitter (weak-reference safe)

### 3.5 Thread ownership summary

| Seam | Thread | Ownership |
|------|--------|-----------|
| `resolve_typed_action()` | UI (main) | `resolver.py` |
| `execute_typed_action(action)` | Inline `asyncio.run()` (no worker thread) | `local_action_executor` |
| `classify_execution()` | UI (main) | `router.py` |
| `_run_agent_native()` | Unnamed daemon worker | `interactive_dispatch` + `delivery_lifecycle` |
| `_run_deterministic_tool()` | Worker `"deterministic-tool"` | `registry` |
| `_run_google_light()` | Worker `"google-light-{name}"` | `google_direct` + `registry` |
| `_chat()` | Worker `"nlp-chat"` | Gemini Live client |

No cross-thread mutation: all deliveries use signals/BUS/queue, not shared mutable state.

---

## 4. Routing Decisions per Input Class

| Input class | First hit | Decision point | Owner | Invariant |
|-------------|----------|----------------|-------|---------|
| Deterministic local action (`/open spotify`) | resolver `_l0` | single-action match | L1 executor | No LLM used; one task |
| Imperative verb action (`buka spotify`) | resolver `_l1` | verb+entity lookup | L1 executor | One tool execution |
| Ambiguous target (`buka Spotify` w/o preference) | resolver `_l1` → `ClarifyNeeded` | app_or_site clarification | UX question | No execution; waits for reply |
| T2+ multi-step (`ringkas dan kirim email`) | router `classify_execution` | tier>=AGENT branch | Native agent | ACK flow + lifecycle |
| Google cloud tool (`cek saham TSLA`) | `google_direct.match_command` | enabled_by_tool_group | T1 registry | Registry execute once |
| Web search (`caris resto Jakarta`) | legacy router.intent → `SEARCH_WEB` | mode=defaults to "search" | `web_search` worker | Tool-based, not URL navigation |
| Fallback conversation (`cerita tentang …`) | else-branch `_chat` | assistant.client not None | Gemini Live | Single response emission |

---

## 5. Known Gaps (to be addressed in P1-B characterization)

1. **Duplicate route possibility**: If `classifier` override returns tier>=AGENT while legacy intent also hits SEARCH_WEB, could there be two executions? Test needed: submit same text under override vs non-override, measure task IDs emitted.
2. **Speech duplication**: Confirm that `write_log` + `_speak_line` never duplicate across lanes (agent native vs chat).
3. **Worker starvation**: Multiple rapid parallel submissions; verify thread pool capacity and queue ordering (should be FIFO, bounded).
4. **Error isolation**: If `_run_google_light()` fails hard, ensure `_chat()` can still run later in same session (thread crash propagation test).
5. **Provider timeout vs orb state**: When T1/T2 times out, orb must transition back to IDLE within bounded time; currently relies on `finally` blocks but no unit test for timeout scenarios.

---

## 6. Next Step (P1-B)

**Characterization matrix construction**: For each input class above, add one offline test fixture that asserts the exact sequence of method invocations and owner selection (e.g., assert `asyncio.run(registry.execute(...))` called exactly once for T1 cases, and `_run_agent_native` called exactly once for T2+ cases).

**RED-first boundary**: Pick one failing case (likely duplicate route scenario), construct minimal fake registry/provider, assert it fails because of unguarded double-call, then implement **one** guard seam (e.g., `task_id` dedup before execution).

---

*This document is read-only evidence for roadmap P1-A. It does not authorize any source change. The next implementation phase requires separate authorization after P1-B accepts this map.*

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
