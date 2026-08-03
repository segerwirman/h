# Desktop-Safe Set Value Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Menambahkan `desktop_safe_set_value` yang hanya mengubah satu nilai pada slider/dropdown UIA non-sensitif, dalam sesi desktop-local yang sama, dengan konfirmasi eksplisit dan bukti UIA recapture bahwa nilai/seleksi benar-benar berubah.

**Architecture:** Capability ini memperluas rantai yang sudah terbukti: `desktop_observe → observation_id + semantic ref → desktop_safe_*`. Ia tidak menerima koordinat atau input bebas yang disalurkan ke keyboard. `SafeDesktopSession` menjadi authority untuk ownership observation, gate/risk classification, lease desktop, satu UIA-native set action, invalidasi snapshot, dan recapture verification.

**Tech Stack:** Python 3.11, Pydantic, pywinauto UIA, UI Automation ValuePattern/SelectionPattern, `CuaSafetyGate`, native registry/policy, pytest, PyQt6 fixture disposable.

---

## Non-goals dan batas keras

Jangan membuka atau menambahkan dalam fase ini:

```text
voice / Gemini Live exposure
Telegram/remote, cron, delegation
computer_control, desktop_control, screen_process
vision_analyze, screenshot, OCR
coordinate input
raw keyboard typing / key shortcuts
drag
right-click / double-click
free-form text field editing
```

`desktop_safe_set_value` hanya untuk control UIA dengan salah satu role:

```text
slider
Dropdown/ComboBox
```

Tidak boleh dipakai untuk `text_field`, `composer`, `password`, `search_field`, atau `address`.

---

## Contract target

### Schema tool

```json
{
  "observation_id": "opaque-id",
  "element_id": "uia-element-id",
  "value": "allowed-enum-or-bounded-number"
}
```

Tidak ada parameter:

```text
x, y, coordinate, text, keys, button, double, drag, amount
```

### Required chain

```text
desktop_observe
→ output hanya safe refs yang eligible untuk set-value
→ same session ownership
→ CuaSafetyGate fresh semantic ref
→ role whitelist (slider/dropdown)
→ sensitivity block / destructive confirmation
→ explicit confirmation UI adapter
→ desktop lease
→ exactly one UIA ValuePattern.SetValue / SelectionItem.Select
→ invalidate observation
→ UIA recapture same surface
→ ValuePattern/SelectionPattern state marker changed and equals requested value
→ verified ToolResult
```

### Confirmation policy

Berbeda dari `desktop_safe_click`/`desktop_safe_scroll`, setiap `desktop_safe_set_value` wajib:

```python
requires_confirmation = True
```

Confirmation text hanya boleh menunjukkan metadata aman dan nilai target yang dibatasi; jangan dump UI text/context:

```text
Ubah nilai control desktop semantik <role> ke <value>?
```

Untuk slider, tool harus memakai domain UIA yang dibaca saat observe:

```text
minimum, maximum, small_change/current_value
```

Nilai di luar domain ditolak sebelum confirmation atau executor.

Untuk dropdown, nilai harus salah satu option ID/value yang diterbitkan oleh observation saat ini, bukan label bebas yang dapat membuat matching ambigu.

---

## Task 1: Tambahkan state UIA yang deterministik untuk control set-value

**Objective:** Normalisasi state UIA yang cukup untuk membuktikan perubahan tanpa bergantung screenshot/OCR.

**Files:**
- Modify: `jarvis/automation/uia_capture.py`
- Test: `tests/test_cua_uia_safe_click.py`

**Step 1: Write failing tests**

Tambahkan test terpisah untuk:

```python
def test_uia_slider_exposes_range_state_marker():
    element = _element_from_control(fake_slider(current=25, minimum=0, maximum=100), 1)
    assert element.role == "slider"
    assert element.states["value"] == 25.0
    assert element.states["minimum"] == 0.0
    assert element.states["maximum"] == 100.0


def test_uia_combobox_exposes_selected_option_id_not_free_text():
    element = _element_from_control(fake_combo(selected_id="uia-option-2"), 1)
    assert element.role == "dropdown"
    assert element.states["selected_id"] == "uia-option-2"
```

**Step 2: Verify RED**

```bash
unset PYTHONPATH
python -m pytest -q \
  tests/test_cua_uia_safe_click.py::test_uia_slider_exposes_range_state_marker \
  tests/test_cua_uia_safe_click.py::test_uia_combobox_exposes_selected_option_id_not_free_text
```

Expected: FAIL karena UIA state marker belum diekstrak.

**Step 3: Minimal implementation**

- Tambahkan mapping UIA `Slider → slider`; `ComboBox → dropdown` sudah ada.
- Untuk slider, baca UIA RangeValue pattern secara defensif; tanpa `CurrentValue`, `Minimum`, dan `Maximum`, jangan terbitkan element actionable untuk set-value.
- Untuk dropdown, baca selection/UIA selection item identifier yang stable. Bila UIA tidak memberi selected stable ID, jangan klaim control set-value eligible.
- Jangan membaca screenshot, OCR, atau `window_text()` sebagai proof nilai.

**Step 4: Verify GREEN**

Jalankan dua test di atas sampai pass.

---

## Task 2: Tambahkan eligibility read-only ke `desktop_observe`

**Objective:** Observation hanya menerbitkan set-value capability metadata untuk slider/dropdown yang UIA state-nya lengkap dan non-sensitif.

**Files:**
- Modify: `jarvis/agent/tools/desktop_observe.py`
- Test: `tests/test_desktop_observe_tool.py`

**Step 1: Write failing tests**

```python
def test_desktop_observe_emits_set_value_descriptor_only_for_complete_slider():
    result = observe_fixture_with_slider()
    item = next(item for item in result.content["elements"] if item["role"] == "slider")
    assert item["actions"] == ["set_value"]
    assert item["value_domain"] == {"minimum": 0.0, "maximum": 100.0}


def test_desktop_observe_does_not_emit_set_value_for_text_field_or_incomplete_combo():
    result = observe_fixture_with_text_and_incomplete_combo()
    assert all("set_value" not in item.get("actions", []) for item in result.content["elements"])
```

**Step 2: Verify RED**

```bash
unset PYTHONPATH
python -m pytest -q tests/test_desktop_observe_tool.py
```

Expected: FAIL karena descriptor/action belum tersedia.

**Step 3: Minimal implementation**

- Pertahankan output click/scroll existing.
- Untuk slider/dropdown yang memenuhi state contract, tambahkan metadata bounded:
  - slider: `actions=["set_value"]`, `value_domain={minimum, maximum}`;
  - dropdown: `actions=["set_value"]`, `options=[{"option_id": "..."}]`.
- Jangan mengirim label option, text UI, atau nilai/isi sensitif ke agent output.
- Tetap limit total elements (`50`) dan safe-only filtering.

**Step 4: Verify GREEN**

```bash
unset PYTHONPATH
python -m pytest -q tests/test_desktop_observe_tool.py
```

---

## Task 3: TDD `SafeDesktopSession.set_value`

**Objective:** Buat executor internal yang hanya menjalankan satu native UIA set action setelah semantic/session/policy gate.

**Files:**
- Modify: `jarvis/agent/tools/desktop_safe_click.py`
- Test: `tests/test_desktop_safe_set_value_tool.py` (create)

**Step 1: Write failing tests**

Test minimal berikut harus terpisah:

```python
def test_set_value_same_session_slider_in_range_executes_once_and_verifies(): ...
def test_set_value_out_of_range_never_calls_executor(): ...
def test_set_value_text_field_never_calls_executor(): ...
def test_set_value_cross_session_never_calls_executor(): ...
def test_set_value_recapture_same_surface_but_unchanged_value_is_failed(): ...
def test_set_value_invalidates_old_observation_after_attempt(): ...
```

Fake authority harus merekam satu call `set_slider(...)` atau `select_option(...)`; tidak menggunakan pyautogui maupun coordinate API.

**Step 2: Verify RED**

```bash
unset PYTHONPATH
python -m pytest -q tests/test_desktop_safe_set_value_tool.py
```

Expected: FAIL karena executor/session method belum ada.

**Step 3: Minimal implementation**

Tambahkan method internal dengan bentuk konseptual:

```python
def set_value(self, observation_id, element_id, value, *, session_id):
    require_same_session(...)
    ref = gate.reference(...)
    decision = gate.evaluate(ref, action="set_value")
    require role in {"slider", "dropdown"}
    require UIA state domain complete
    require value in bounded domain
    claim desktop lease
    invoke exactly one injected/UIA native setter
    invalidate observation
    recapture same surface
    require state marker changed and equals requested value
    release lease
```

Important:

- Tidak ada retry otomatis.
- Kegagalan recapture setelah set attempt dilaporkan sebagai `executed=True`, `verified=False`.
- Jangan implement `type`, `key`, drag, atau coordinate fallback.

**Step 4: Verify GREEN**

```bash
unset PYTHONPATH
python -m pytest -q tests/test_desktop_safe_set_value_tool.py
```

---

## Task 4: Tambahkan native tool `desktop_safe_set_value`

**Objective:** Daftarkan satu tool desktop-local yang menerima ID + value domain bounded saja, dan selalu meminta confirmation.

**Files:**
- Create: `jarvis/agent/tools/desktop_safe_set_value.py`
- Modify: `jarvis/agent/capabilities.py`
- Test: `tests/test_desktop_safe_set_value_tool.py`

**Step 1: Write failing tests**

```python
def test_set_value_schema_has_only_observation_id_element_id_value():
    props = DesktopSafeSetValue().json_schema()["properties"]
    assert set(props) == {"observation_id", "element_id", "value"}


def test_set_value_always_requires_confirmation():
    assert DesktopSafeSetValue().needs_confirmation(...) is True


def test_set_value_is_desktop_safe_capability_not_voice_schema():
    assert descriptor.toolset == "desktop_safe"
    assert "desktop_safe_set_value" not in voice_schema_names
```

**Step 2: Verify RED**

```bash
unset PYTHONPATH
python -m pytest -q tests/test_desktop_safe_set_value_tool.py
```

**Step 3: Minimal implementation**

- `wants_context=True`, `timeout_s=30`, non-read-only.
- `requires_confirmation=True`; confirmation happens through existing registry adapter flow.
- Add explicit descriptor:

```python
CapabilityDescriptor(
    "desktop_safe.desktop_safe_set_value",
    "desktop_safe_set_value",
    "desktop_safe",
    "medium",
    30,
)
```

- Do not add it to `jarvis/integrations/voice_native_tools.py`.
- Use existing `desktop_safe` policy. Verify it remains absent from remote/voice/cron/delegation schemas.

**Step 4: Verify GREEN**

```bash
unset PYTHONPATH
python -m pytest -q \
  tests/test_desktop_safe_set_value_tool.py \
  tests/test_desktop_safe_policy.py \
  tests/test_desktop_observe_tool.py
```

---

## Task 5: Add disposable PyQt registry acceptance fixture

**Objective:** Buktikan ValuePattern/SelectionPattern set action melalui product path, pada UI disposable tanpa data user.

**Files:**
- Create: `scripts/cua_safe_set_value_acceptance.py`
- Test: optional narrow helper tests only; fixture output is manual acceptance evidence.

**Fixture choice:** mulai hanya dengan `QSlider` karena domain range dan state marker deterministik. Jangan memasukkan dropdown pada acceptance pertama bila UIA SelectionPattern belum terbukti di environment.

**Step 1: Create fixture behavior**

```text
PyQt QWidget temporary
→ QSlider range 0..100, initial value 25
→ no files/network/clipboard/user data
→ UIA wrapper bound explicitly to fixture HWND
→ registry.execute("desktop_observe", desktop-local context)
→ select slider semantic ID
→ registry.execute("desktop_safe_set_value", value=30)
→ QSlider value must equal 30
→ UIA recapture marker must equal 30
→ print opaque/status result only
```

**Step 2: Run manual acceptance**

```bash
unset PYTHONPATH
python scripts/cua_safe_set_value_acceptance.py
```

Expected form:

```text
{
  "accepted": true,
  "executed": true,
  "verified": true,
  "marker_changed": true
}
```

If UIA RangeValue is absent or stale, report the concrete failure and do **not** introduce screenshot/OCR fallback.

---

## Task 6: Registry schema and lifecycle regression matrix

**Objective:** Prove this remains desktop-local only and teardown revokes pending set-value observations.

**Files:**
- Modify: `tests/test_desktop_safe_policy.py`
- Modify: `tests/test_desktop_observe_tool.py`

**Step 1: Add failing tests**

```python
def test_registry_schema_exposes_set_value_only_for_desktop_agent_context(): ...
def test_remote_voice_cron_and_delegation_schemas_exclude_set_value(): ...
def test_ui_close_or_session_cleanup_revokes_set_value_observation(): ...
def test_destructive_or_sensitive_control_never_emits_set_value_descriptor(): ...
```

**Step 2: Verify RED then GREEN**

```bash
unset PYTHONPATH
python -m pytest -q tests/test_desktop_safe_policy.py tests/test_desktop_observe_tool.py
```

Expected after implementation: pass.

---

## Final verification

Run after all tasks, without claiming full-suite health if an unrelated pre-existing failure remains:

```bash
unset PYTHONPATH
python -m pytest -q \
  tests/test_desktop_safe_set_value_tool.py \
  tests/test_desktop_safe_policy.py \
  tests/test_desktop_observe_tool.py \
  tests/test_desktop_safe_scroll_tool.py \
  tests/test_desktop_safe_click_tool.py \
  tests/test_cua_uia_safe_click.py \
  tests/test_cua_safe_click.py \
  tests/test_cua_safety_gate.py \
  tests/test_automation_services.py

unset PYTHONPATH
python scripts/cua_safe_set_value_acceptance.py

unset PYTHONPATH
python -m py_compile \
  jarvis/agent/tools/desktop_safe_set_value.py \
  jarvis/agent/tools/desktop_observe.py \
  jarvis/agent/tools/desktop_safe_click.py \
  jarvis/automation/uia_capture.py \
  scripts/cua_safe_set_value_acceptance.py

python scripts/verify_frozen.py
git diff --check
```

## Acceptance gate to finish

Set-value may be considered desktop-local-ready only if all are true:

- Registry desktop-local acceptance on disposable QSlider passes.
- Value state marker after recapture equals requested bounded value.
- Tool always requires explicit confirmation.
- Range/domain rejection prevents executor call.
- Cross-session/stale/teardown IDs fail before executor.
- Remote, voice, cron, delegation schemas contain none of `desktop_observe`, `desktop_safe_click`, `desktop_safe_scroll`, `desktop_safe_set_value`.
- No coordinate, keyboard, typing, drag, screenshot/OCR/vision fallback exists.

## Risks and decisions

| Risk | Decision |
|---|---|
| Slider may expose no RangeValuePattern | Do not expose `set_value`; fail closed. |
| Dropdown option labels could leak or be ambiguous | Use only stable option IDs; defer dropdown execution if UIA pattern is not reliable. |
| UIA set action could land but recapture fail | Never retry; return executed/unverified. |
| User confirmation could be bypassed by existing policy | Tool-level `requires_confirmation=True` remains mandatory even when desktop-safe policy allows capability. |
| Frozen UI change pressure | No frozen file edits needed; retain editable lifecycle bridge. |

## Explicitly deferred

```text
type
key
drag
right-click
double-click
coordinate input
voice/remote exposure
vision_analyze
computer_control
desktop_control
screen_process
```

No commit is included in this plan because the worktree is dirty; inspect and obtain scope approval before staging.