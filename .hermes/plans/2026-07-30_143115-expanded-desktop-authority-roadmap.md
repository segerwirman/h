# Expanded Desktop Authority Roadmap & Safety Contract

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Mengubah roadmap dari deny-default menjadi pembukaan capability desktop yang bertahap untuk cron, delegation, coordinate input, generic `computer_control` / `desktop_control` / `screen_process`, tanpa mengizinkan jalur bypass terhadap policy, approval, identity, lease, audit, dan recapture.

**Architecture:** Semua capability tetap berjalan melalui native JARVIS authority. Generic tool tidak boleh langsung menjadi executor OS; ia hanya facade yang memetakan request ke primitive capability yang terdaftar dan policy-gated. Remote/voice/cron/delegation tidak mendapat akses langsung ke input injection; mereka hanya dapat menghasilkan request yang diteruskan ke desktop-local approval dan one-shot permit. Coordinate input—jika dibuka—tidak pernah menerima coordinate mentah dari model/remote; coordinate hanya dapat diterbitkan secara internal dari observation UIA atau desktop-local UI selection yang terikat observation dan RuntimeId.

**Tech Stack:** Python 3.11, Pydantic, pywinauto UIA, `CuaSafetyGate`, `ExecutionContext`, registry/policy/approval native, PyQt6 disposable fixtures, pytest.

---

## Decision record / perubahan contract

User meminta capability berikut pada akhirnya menjadi **allowed**:

```text
cron
delegation
coordinate input
generic computer_control
generic desktop_control
generic screen_process
```

"Allowed" dalam roadmap ini berarti **dapat dipakai setelah capability-specific gate lulus**, bukan unrestricted authority.

### Invarian yang tetap tidak boleh dihilangkan

```text
native JARVIS authority only
policy context wajib
actor/session/trace binding
short-lived one-shot permit untuk action berisiko
RuntimeId opaque untuk target UIA
same-session / same-surface proof
lease eksklusif
exactly one action per permit
invalidate setelah attempt
fresh recapture atau deterministic evidence
no automatic retry
audit metadata-only/redacted
emergency revoke/kill switch
```

### Explicitly rejected designs

```text
remote/voice/cron/delegation → direct OS executor
model → raw x/y input → executor
single generic tool with unrestricted shell/process/window access
vision → coordinate fallback → injection
generic computer_control as compatibility alias that bypasses registry policy
```

---

# Phase order

```text
F1  Cross-action identity & observation integrity
F2  Policy/context/permit authority hardening
F3  Lifecycle/concurrency/cancellation/failure containment
F4  Local approval UX + audit + emergency revoke
F5  Disposable canary/readiness matrix
F6  Dropdown selection
F7  Right-click then double-click
F8  Bounded text then bounded key command
F9  Semantic drag
F10 Read-only vision with privacy boundary
F11 Coordinate capability (derived/bounded, local only)
F12 Generic computer_control / desktop_control facade
F13 screen_process capability
F14 Delegation mediated authority
F15 Cron mediated authority
F16 Telegram/remote mediated authority
F17 Voice-mediated authority
```

F1–F5 adalah gate bersama. Tidak ada capability baru setelah baseline sebelum F1–F5 lolos.

---

## F1 — Cross-action identity & observation integrity

**Objective:** Semua target actionable memakai RuntimeId opaque dan tidak dapat mengenai control pengganti dengan ordinal/rect/surface sama.

**Files:**
- Modify: `jarvis/automation/cua_safety.py`
- Modify: `jarvis/automation/uia_capture.py`
- Modify: `jarvis/agent/tools/desktop_safe_click.py`
- Modify: `jarvis/agent/tools/desktop_safe_scroll.py`
- Test: `tests/test_cua_uia_safe_click.py`
- Test: `tests/test_desktop_safe_click_tool.py`
- Test: `tests/test_desktop_safe_scroll_tool.py`

**Acceptance:** replacement/reorder before action blocks; replacement after action never returns `verified=True`; absent RuntimeId is not actionable.

---

## F2 — Universal context, policy, and one-shot permit authority

**Objective:** Tidak ada execution path alternatif yang dapat langsung mencapai executor.

**Files:**
- Modify: `jarvis/agent/registry.py`
- Modify: `jarvis/agent/policy.py`
- Modify/create: `jarvis/agent/approval.py`
- Test: `tests/test_desktop_safe_policy.py`
- Test: `tests/test_desktop_safe_set_value_tool.py`

**Required contract:**

```text
context=None → block
Tool.run() direct → block untuk action capability
wrong surface/source/toolset → block sebelum approval
permit = capability + trace + actor + session + observation + element + arguments digest + expiry + nonce
permit replay / cross-session / argument substitution → block
permit consumed after one attempt, including executor error
```

**Acceptance:** test matrix UI/agent/local allow vs remote/voice/cron/delegation deny at this phase. Cron/delegation become candidates only later through their mediated adapters.

---

## F3 — Lifecycle, concurrency, cancellation, and failure containment

**Objective:** Tidak ada stale authority, lease leak, background worker, atau retry otomatis setelah failure.

**Files:**
- Modify: `jarvis/agent/tools/desktop_safe_click.py`
- Modify: `jarvis/agent/dispatch.py`
- Modify: `jarvis/integrations/desktop_safe_lifecycle.py`
- Test: `tests/test_desktop_safe_lifecycle.py` (create)
- Test: `tests/test_desktop_safe_concurrency.py` (create)

**Acceptance matrix:** close/cancel, context timeout, foreground switch, UIA throw, recapture failure, permit revocation during wait, 100 lease-contention iterations. Every case releases lease and invalidates ref.

---

## F4 — Desktop-local approval UX, audit, and emergency revoke

**Objective:** User lokal adalah authority terakhir untuk capability yang dapat mengubah desktop.

**Files:**
- Create: `jarvis/integrations/desktop_safe_approval.py`
- Modify: editable desktop UI integration boundary only; do not modify frozen `ui.py`
- Modify: `jarvis/agent/approval.py`
- Test: `tests/test_desktop_safe_approval.py` (create)

**Required UX:** confirmation card includes only safe metadata: capability role, bounded target class, bounded value/action, expiry. It never exposes UI text, screenshot, secrets, or typed content.

**Emergency revoke:** desktop-local button/command revokes all outstanding desktop permits, observations, leases, pending continuation tasks, and disables desktop capability availability until explicitly re-enabled.

---

## F5 — Disposable canary and operational readiness

**Objective:** Prove every failure mode with JARVIS-owned PyQt fixtures before non-fixture UI.

**Files:**
- Create: `scripts/cua_identity_acceptance.py`
- Create: `scripts/cua_lifecycle_acceptance.py`
- Modify: `scripts/cua_safe_click_acceptance.py`
- Modify: `scripts/cua_safe_scroll_acceptance.py`
- Modify: `scripts/cua_safe_set_value_acceptance.py`

**Acceptance fixtures:** button, scroll area, slider, control replacement, busy lease, close/revoke, confirmation cancel, recapture mismatch. No browser, files, network, clipboard, login, payment, or user data.

**Exit gate:** repeat deterministic runs; all negative paths demonstrate zero executor calls; independent review has no unresolved P1/P2.

---

## F6 — Dropdown selection (desktop-local only)

**Objective:** Add one bounded `SelectionItem.Select` action using opaque stable option IDs.

**Files:**
- Modify: `jarvis/automation/uia_capture.py`
- Modify: `jarvis/agent/tools/desktop_observe.py`
- Modify: `jarvis/agent/tools/desktop_safe_set_value.py` or create `desktop_safe_select_option.py` if schema clarity requires it
- Create: `scripts/cua_safe_dropdown_acceptance.py`
- Test: `tests/test_desktop_safe_dropdown.py` (create)

**Contract:** stable dropdown RuntimeId + stable option RuntimeId/opaque ID, explicit local approval, one select, recapture exact selected opaque ID. No label matching, typing, keyboard navigation, or free-form values.

---

## F7 — Right-click then double-click (desktop-local only)

**Objective:** Add separate capabilities, never a free `button` or `double` argument to existing click.

**Files:**
- Create: `jarvis/agent/tools/desktop_safe_right_click.py`
- Create: `jarvis/agent/tools/desktop_safe_double_click.py`
- Modify: `jarvis/agent/capabilities.py`
- Modify: `jarvis/agent/policy.py`
- Test: `tests/test_desktop_safe_right_click.py` (create)
- Test: `tests/test_desktop_safe_double_click.py` (create)

**Contract:** RuntimeId, allowlisted roles/scopes, confirmation, one action, recapture. Context menus must be verified as a safe menu-state transition; double-click requires a declared expected surface transition or marker.

---

## F8 — Bounded editable text and key commands (desktop-local only)

**Objective:** Add bounded data entry without creating generic `type(text)` or `key(keys)` authority.

**Files:**
- Create: `jarvis/agent/tools/desktop_safe_set_text.py`
- Create: `jarvis/agent/tools/desktop_safe_key_command.py`
- Create: `jarvis/automation/text_safety.py`
- Test: `tests/test_desktop_safe_set_text.py` (create)
- Test: `tests/test_desktop_safe_key_command.py` (create)

**Initial allowlist:** JARVIS-owned fixtures or named JARVIS settings panels only.

**Hard blocks:** password, OTP/PIN, login, payment, address bar, search field, composer/chat, browser, shell/terminal, code editor, file path picker, clipboard operations.

**Text contract:** max length, content classification, redacted audit, explicit confirmation, one `ValuePattern.SetValue`, exact recapture. No keystroke injection initially.

**Key contract:** fixed allowlist such as a named safe toggle only; no arbitrary chord/string. Key action carries no model-provided raw key code.

---

## F9 — Semantic drag (desktop-local only)

**Objective:** Add bounded source→destination drag to JARVIS-owned disposable fixtures only.

**Files:**
- Create: `jarvis/agent/tools/desktop_safe_drag.py`
- Create: `scripts/cua_safe_drag_acceptance.py`
- Test: `tests/test_desktop_safe_drag.py` (create)

**Contract:** source and destination RuntimeIds, allowed source/destination pair matrix, confirmation, duration/internal path fixed, one action, recapture both markers. Agent never supplies coordinates.

---

## F10 — Read-only vision analysis

**Objective:** Permit privacy-scoped image analysis with no desktop executor authority.

**Files:**
- Create: `jarvis/agent/tools/desktop_readonly_vision.py`
- Create: `jarvis/agent/vision_policy.py`
- Test: `tests/test_desktop_readonly_vision.py` (create)

**Contract:** explicit user request, privacy classification, redaction, no coordinate output accepted by desktop executors, no automatic action continuation.

---

## F11 — Coordinate capability (derived and bounded; local only)

**Objective:** Make coordinate-derived actions allowed without allowing model-supplied raw coordinates.

**Files:**
- Create: `jarvis/automation/coordinate_capability.py`
- Create: `jarvis/agent/tools/desktop_safe_coordinate_action.py`
- Modify: `jarvis/agent/capabilities.py`
- Test: `tests/test_desktop_safe_coordinate_action.py` (create)

**Safety contract:**

```text
Agent never provides x/y/rect.
Coordinate comes only from a current UIA ref or desktop-local user selection.
Coordinate is stored only inside a one-shot permit.
Target RuntimeId, surface HWND, and observation must match at execution.
Action kind is separately allowlisted; no generic pointer injection.
No coordinate is sent through remote/voice/cron/delegation.
```

**Expansion condition:** only after F1–F10 pass and a dedicated independent review approves this design.

---

## F12 — Generic `computer_control` / `desktop_control` facade

**Objective:** Allow named generic tool interfaces without unrestricted power.

**Files:**
- Create: `jarvis/agent/tools/computer_control.py`
- Create: `jarvis/agent/tools/desktop_control.py`
- Create: `jarvis/agent/desktop_capability_router.py`
- Test: `tests/test_generic_desktop_facades.py` (create)

**Facade contract:**

```text
computer_control / desktop_control
→ only enum action names mapped to already-approved narrow capabilities
→ router validates schema, policy, and permit
→ delegate to native primitive
→ no subprocess / shell / raw pointer / raw key / arbitrary process API
→ unknown generic command fails closed
```

No capability is added merely because the facade exists. The facade’s schema is dynamically limited to phase-approved actions.

---

## F13 — `screen_process` capability

**Objective:** Allow bounded, read-mostly screen/process awareness and explicit lifecycle operations without generic OS process control.

**Files:**
- Create: `jarvis/agent/tools/screen_process.py`
- Create: `jarvis/automation/process_policy.py`
- Test: `tests/test_screen_process.py` (create)

**Phase 13a read-only allowlist:** active surface opaque ID, process existence/status for JARVIS-owned fixture/process allowlist, desktop capability status, lease state.

**Phase 13b mutable operations:** only JARVIS-owned child processes with provenance token. Stop/restart requires desktop-local confirmation, one-shot permit, timeout, and post-condition verification. No arbitrary PID/name kill, no shell command execution, and no system process management.

---

## F14 — Delegation mediated authority

**Objective:** Allow delegation to request desktop work while preventing child/subagent direct desktop executor access.

**Files:**
- Create: `jarvis/agent/delegation_desktop_mediator.py`
- Modify: `jarvis/agent/dispatch.py`
- Modify: `jarvis/agent/policy.py`
- Test: `tests/test_delegation_desktop_mediator.py` (create)

**Contract:**

```text
subagent proposal (structured, no executor access)
→ parent validates task scope
→ desktop-local approval UI
→ parent-owned one-shot permit
→ parent native executor
→ redacted result returned to subagent
```

Subagent cannot see RuntimeId, coordinates, UI labels, screenshots, permits, or raw process details.

---

## F15 — Cron mediated authority

**Objective:** Allow scheduled desktop tasks only with pre-authorized, immutable, JARVIS-owned task manifests.

**Files:**
- Create: `jarvis/agent/cron_desktop_mediator.py`
- Create: `jarvis/agent/desktop_task_manifest.py`
- Modify: scheduler/cron integration entrypoint after locating it during implementation
- Test: `tests/test_cron_desktop_mediator.py` (create)

**Contract:**

```text
user creates local manifest interactively
→ manifest names a narrow capability, target class, expected state, expiry, schedule, and max runs
→ manifest signed/stored locally with revision
→ cron tick validates manifest, device/session availability, and quiet-hours policy
→ one execution attempt
→ verify / audit / notify
→ failure never broadens scope or retries action blindly
```

Cron cannot run free-form prompts, raw coordinates, free-form text, generic process operations, remote requests, or approval bypass. Each manifest supports a kill switch and automatic expiry.

---

## F16 — Telegram/remote mediated authority

**Objective:** Allow approved remote requests without granting direct desktop control.

**Files:**
- Create: `jarvis/integrations/remote_desktop_mediator.py`
- Modify: Telegram ingress/router only after runtime call-chain discovery
- Test: `tests/test_remote_desktop_mediator.py` (create)

**Contract:** actor allowlist, device/session binding, nonce, replay protection, short expiry, rate limit, desktop-local approval, redacted result delivery, cancellation, emergency revoke. Remote does not receive screenshots/UI text/RuntimeIds/coordinates/permits.

---

## F17 — Voice-mediated authority

**Objective:** Allow voice to propose—not execute—approved desktop actions.

**Files:**
- Create: `jarvis/integrations/voice_desktop_mediator.py`
- Modify: voice tool declaration only after all F1–F16 gates pass
- Test: `tests/test_voice_desktop_mediator.py` (create)

**Contract:** confidence threshold, ambiguity rejection, barge-in cancellation, transcript redaction, short session expiry, visible desktop-local approval, then parent native executor. Voice cannot directly approve or receive coordinate/RuntimeId authority.

---

## Global final verification per phase

```bash
unset PYTHONPATH
python -m pytest -q <focused tests for that phase>
python -m py_compile <changed modules>
git diff --check
python scripts/verify_frozen.py
```

For every desktop action phase also run the matching disposable acceptance script. Do not claim full-suite health unless it is actually run and returns an explicit all-pass summary.

## Commit discipline

The worktree is dirty. Do not use `git add -A`; do not stage `.hermes/`. Before each narrow commit, inspect status and stage only phase-specific source/test files after user approval of the scope.

## Exit criteria for an "allowed" capability

A requested capability becomes allowed only when its phase has all of:

```text
narrow schema
policy context enforcement
approval/permit contract where applicable
identity/session/lease enforcement
negative tests showing zero executor calls
failure injection tests
JARVIS-owned disposable acceptance
independent review with no unresolved P1/P2
kill switch/revoke proof
redacted audit proof
```

Until then it remains disabled by default, even if it appears in the long-term roadmap.
