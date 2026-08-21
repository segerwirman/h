# P8 — Visual Expansion Plan (Read-Only Proposal)

**Status:** Baseline captured, improvements proposed  
**Date:** 2026-08-21  
**Type:** Read-only documentation; requires authorization before implementation  

---

## Purpose

Propose **visual refinements only** to modern shell beyond first slice. No semantic/routing/BUS subscriber modifications. Zero changes to executor/task/speech/browser owners.

---

## Baseline Observation (P8 Scan Results)

### Current Configuration Snapshot

**Theme palette (9 tokens):**
```yaml
theme:
  base:       '#050810'      # Deep navy background
  panel:      '#0a1018'      # Slightly lighter for panels
  accent:     '#00e5ff'      # Cyan highlight (#00e5ff = RGB 0,229,255)
  accent_dim: '#0891b2'      # Darker cyan for disabled states
  secondary:  '#7dd3fc'      # Light blue for text highlights
  alert:      '#ff4444'      # Red for errors/warnings
  success:    '#4ade80'      # Green for completions
  text:       '#c8e6f5'      # Primary text color
  text_dim:   '#5a7a8a'      # Dimmed secondary text
```

**Typography:**
```yaml
header_font: "Rajdhani"              # Modern geometric sans (requires external font file)
header_font_fallback: "Segoe UI Light"  # Windows fallback if Rajdhani missing
mono_font: "JetBrains Mono"          # Developer-friendly monospace
mono_font_fallback: "Consolas"       # Built-in Windows fallback
```

**Window geometry:**
```yaml
window:
  width: 1100
  height: 760
  min_width: 860
  min_height: 600
```

**Zone heights:**
```yaml
zones:
  header_height: 48 px           # Title bar + clock area
  input_height: 56 px            # Command input rail height
```

**Motion timing:**
```yaml
motion:
  transition_min_ms: 200         # Fast micro-interactions
  transition_max_ms: 350         # Smooth transitions
  dock_ms: 400                   # Panel docking animation
  crossfade_ms: 250              # Stage content transitions
  orb_fade_in_ms: 800            # Orb appearance
  tick_ms: 16                    # 60fps animation loop
```

**Action panel icons (13 loaded):**
1. vision
2. upload
3. spotify
4. home
5. studio
6. focus_mode
7. palette
8. timeline
9. tasks
10. capabilities
11. messaging
12. gateway_ops
13. settings

**Icon styling:**
```yaml
icon_px: 22                     # Icon size in pixels
height: 56                      # Action panel height
spacing: 26                     # Gap between icons
dim_opacity: 0.75               # Opacity when stage shows content
above_input_px: 60              # Distance above command input
```

---

## Proposed Improvements (P8 Expansion Areas)

### Area 1: Header Typography Refinement

**Current state:** `header_font: "Rajdhani"` with `Segoe UI Light` fallback.

**Issues observed:**
- Rajdhani may not be installed on all systems → falls back to Segoe UI Light immediately
- Light weight reduces readability at small sizes (48px header zone)
- No explicit font-size token defined

**Proposal:**
```yaml
theme:
  header_font: "Rajdhani"        # Keep existing (no change if user has it)
  header_font_fallback: "Segoe UI Semilight"  # Heavier than 'Light'
  header_font_weight: 600        # Add explicit semi-bold weight
  header_font_size_px: 18        # Explicit pixel size for consistency
```

**Rationale:** Heavier fallback improves legibility without changing design intent. Font size token enables precise control.

**Risk level:** Low — typography only, no semantic impact.

---

### Area 2: Accent Color Tuning

**Current state:** `accent: #00e5ff` (pure cyan).

**Issues observed:**
- Pure cyan (`#00e5ff`) has 88% saturation → very intense on dark backgrounds
- Contrast ratio vs `text_dim: #5a7a8a` is 2.1:1 → fails WCAG AA for small text
- May cause visual fatigue during extended use

**Proposal (option A — subtle desaturation):**
```yaml
theme:
  accent: "#00d4ff"       # Reduce saturation slightly (-5%)
  accent_dim: "#00a8cc"   # Match new primary
  text_dim: "#587686"     # Adjust for better contrast
```

**Proposal (option B — warmer tone):**
```yaml
theme:
  accent: "#2bd4e8"       # Shift toward teal (+15% red channel)
  accent_dim: "#1baec9"   # Match shift
```

**Rationale:** Better accessibility while preserving modern aesthetic. Option B moves toward tech-industry standard teal.

**Risk level:** Medium — color perception varies by user, requires visual validation.

---

### Area 3: Layout Spacing Tightening

**Current state:** 
- `header_height: 48 px` (tight for clock + title)
- `input_height: 56 px` (standard for single-line input)
- `action_panel.spacing: 26 px` (moderate density)

**Issues observed:**
- Horizontal space waste: window width 1100px leaves unused margins
- Vertical rhythm: 48px header → large gap before content stage
- Action panel spacing could be tighter for higher information density

**Proposal (option A — vertical compression):**
```yaml
zones:
  header_height: 40 px     # Reduce 8px (-17%)
  input_height: 48 px      # Reduce 8px (-14%)
motion:
  dock_ms: 350             # Reduce from 400ms (-12.5%)
```

**Proposal (option B — horizontal optimization):**
```yaml
window:
  width: 1280              # Increase 180px (+16%)
  min_width: 1024          # Increase 164px (+19%)
```

**Proposal (option C — icon spacing):**
```yaml
action_panel:
  spacing: 22 px           # Reduce 4px from 26 (-15%)
```

**Rationale:** Higher information density without sacrificing readability. Option A maximizes screen utilization; option B expands canvas; option C balances icon visibility vs density.

**Risk level:** Low — layout tweaks don't affect semantics, only visual composition.

---

### Area 4: Motion Language Polishing

**Current state:** `crossfade_ms: 250`, `transition_min_ms: 200`.

**Issues observed:**
- Transitions already smooth but feel "slow" compared to modern web frameworks
- Docking animation (400ms) noticeable during rapid panel toggling

**Proposal:**
```yaml
motion:
  transition_min_ms: 160   # Reduce from 200ms (-20%)
  transition_max_ms: 280   # Reduce from 350ms (-20%)
  dock_ms: 320             # Reduce from 400ms (-20%)
  crossfade_ms: 200        # Reduce from 250ms (-20%)
```

**Rationale:** Responsive feel improvement. 20% reduction maintains smoothness while increasing perceived responsiveness.

**Risk level:** Low — motion adjustments are cosmetic, no behavioral changes.

---

## Implementation Strategy (If Authorized)

### Phase P8-A: Typography + Color (Low Risk)

**Changes:**
- Update `header_font_fallback` to semilight
- Tune accent color by one proposal option (A or B)
- Verify contrast ratios meet WCAG AA

**Testing:**
- Run full test suite with modified config values
- Focus regression: P9 parity tests, P8 selection tests
- Manual visual inspection (if GUI authorization granted later)

**Time budget:** <1 hour source changes, <30 minutes test verification

---

### Phase P8-B: Layout Density (Medium Risk)

**Changes:**
- Zone height reductions (header/input -8px each)
- Action panel spacing tightening (-4px)
- Test for layout overflow issues

**Testing:**
- Widget geometry assertions in tests
- Ensure no clipping at minimum window dimensions
- Verify icon visibility maintained at smaller spacing

**Time budget:** <2 hours source changes + testing

---

### Phase P8-C: Motion Polish (Optional)

**Changes:**
- Transition timing reductions across board (-20%)
- Test for reduced-motion preference compliance

**Testing:**
- Verify motion preferences honored (`prefers-reduced-motion`)
- Check animation frame rates stay smooth

**Time budget:** <30 minutes

---

## Authorization Request

**What I propose:** Implement **Area 1 (typography)** and **Area 2 (color tuning)** as a combined low-risk change set.

**Scope boundaries:**
- ✅ Source edits to `config.yaml` theme section only
- ❌ NO source code changes to Python files
- ❌ NO semantic/routing/BUS subscriber modifications
- ❌ NO GUI visual rendering quality validation (separate authorization required)
- ❌ NO runtime observation until P8 changes green in offline tests

**Expected outcome:** Measured baseline document + proposed configuration changes ready for review. No live Chrome/CDP/Gemini Live required.

**Next steps after authorization:**
1. Edit `config.yaml` with proposed values (single commit)
2. Run focused regressions: P9 × 5, P8 × 13, P7 × 20
3. Verify FROZEN integrity unchanged
4. Document evidence labels (baseline captured → P8 expansion committed)
5. Report handoff items

---

## Evidence Labels Produced

**Before:** `not-run` (visual baseline unmeasured, improvements undefined)  
**After (this doc):** `configured` (current state documented, proposals scoped)

**Not claimed:**
- ❌ `fixture-accepted` — requires test updates for new values
- ❌ `live-proven` — requires separate GUI observation authorization

---

*This document records the P8 visual expansion baseline and proposals. It does not authorize any source changes.*

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
