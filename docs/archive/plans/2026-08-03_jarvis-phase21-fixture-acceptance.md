# JARVIS Phase 21 — Desktop-Safe Production-Path Fixture Acceptance (RANCANGAN)

> **Status:** ✅ EKSEKUSI SELESAI — 2026-08-03. Phase 21 COMPLETE: `fixture-accepted` untuk Phase 19 & 20 (title + reorder `verified: true`). Commit: PLAN `0d30794`, FIX `a109f69`, FIX2 `aaec855`. Acceptance run menemukan 4 remediasi production (G1 text_field identity, G2 plain listitem card, G4 verifikasi visual order pasca-reorder, + F1/F2 foreground title-bar click & drag thread) — detail di `session.md` dan master roadmap. Rancangan di bawah tetap berlaku sebagai deskripsi desain.

## Tujuan

Membuktikan Phase 19 (title setter) dan Phase 20 (scene reorder) pada fixture PyQt disposable memakai **production UIA backend** (bukan mock): `UIACaptureBackend` + `CuaSafetyGate` + `SafeDesktopSession` + native executors (`set_text_field_value` ValuePattern, `reorder_semantic` DRIVER.drag fisik). Hasil dilabeli `fixture-accepted`, bukan `live-proven` (tidak menyentuh aplikasi user).

## Arsitektur

```
┌───────────────────────── FIXTURE (disposable, PyQt6) ─────────────────────────┐
│  QLineEdit "Judul Project" (jarvis-fixture-title)  ← ValuePattern target      │
│  QListWidget 3 scene cards (jarvis-fixture-scenes) ← drag-reorder target      │
│  status label — hanya untuk verifikasi lokal, TIDAK dibaca agent              │
└───────────────────────────────────────────────────────────────────────────────┘
        ▲ bound eksplisit via HWND (window.winId())
        │
┌───────┴────────────────────────── PRODUCTION PATH (100% reuse) ───────────────┐
│  pywinauto Desktop(uia).window(handle) → UIACaptureBackend(desktop=stub)      │
│  CuaSafetyGate + CaptureAdapter → SafeDesktopSession                          │
│  set_text_native  = backend.set_text_field_value   (ValuePattern.SetValue)    │
│  reorder_native   = backend.reorder_semantic        (DRIVER.drag fisik)       │
│  _owners[obs.id] = "content-studio-acceptance-fixture"                        │
└───────────────────────────────────────────────────────────────────────────────┘
```

Pola persis `scripts/cua_safe_click_acceptance.py` (sudah terbukti): bind UIA ke HWND fixture eksplisit via stub `get_active`, sehingga foreground window lain tidak memengaruhi capture.

Fakta terverifikasi dari source (2026-08-03):
- `SafeDesktopSession` menerima semua executor via injection; `set_content_title` butuh `set_text_native`, `reorder_scene` butuh `reorder_native`.
- `set_text_field_value` membuktikan committed value berubah (`before_value != after_value` via ValuePattern) + RuntimeId + rect cocok — bukan hanya recapture (fix A48).
- `reorder_scene` butuh: role card/listitem/button, `_uia_parent_runtime_id` sama untuk src+dst, RuntimeId distinct, dan membuktikan order berubah (flip `rect[1]`) + recapture + RuntimeId keduanya.
- `reorder_semantic` memakai `DRIVER.drag` = pyautogui fisik (`FAILSAFE=True`).
- `_active_window()` memakai stub `get_active` bila di-inject — fixture aman dari window lain.

## File yang diusulkan

| File | Aksi | Isi |
|---|---|---|
| `scripts/content_studio_desktop_safe_acceptance.py` | buat | Fixture 21A+21B dalam satu window; print payload metadata-only |
| `tests/test_content_studio_desktop_safe_acceptance_contract.py` | buat | Contract RED→GREEN |
| `scripts/cua_desktop_safe_canary.py` | ubah | `_FIXTURES` + 2 entri: `content_studio_title`, `content_studio_reorder` |
| `tests/test_desktop_safe_canary.py` | ubah | calls list +2 fixture (pola test yang ada) |

Tidak menyentuh production code (`jarvis/...`) — additive test/fixture saja.

## Alur 21A — Title (production path)

```
show window → QTimer(750ms) prove:
1. capture before  → cari element role=text_field (name "Judul Project")
2. gate.reference(before.id, element_id) → _owners[before.id] = fixture owner
3. authority.set_content_title(before.id, element_id, title="Judul Fixture Aman",
                               session_id=fixture)
4. verifikasi: outcome.ok & outcome.verified  →  LOKAL: lineEdit.text() == "Judul Fixture Aman"
5. negative: panggil ulang dengan element_id basi → expect fail (stale surface/ref)
6. print {"accepted":…, "title": {"executed":…, "verified":…}, …}
```

## Alur 21B — Reorder (production path)

```
1. capture before → cari 2 listitem (Scene A, Scene C) — RuntimeId distinct,
   _uia_parent_runtime_id SAMA (satu list container)
2. gate.reference keduanya → authority.reorder_scene(obs, src, dst, session_id=fixture)
3. DRIVER.drag fisik center-to-center (satu drag, durasi tetap 0.35s)
4. verifikasi: outcome.ok & verified (order flip + recapture + RuntimeId keduanya)
   →  LOKAL: urutan item di QListWidget berubah (C di posisi 0)
5. negative: src==dst → reject (dijamin policy, diverifikasi fixture-side)
6. print payload metadata-only
```

## Payload output (metadata only)

```json
{"accepted": true,
 "title": {"executed": true, "verified": true},
 "reorder": {"executed": true, "verified": true}}
```

Tidak ada teks window/field, nilai mentah, path, koordinat, atau exception raw. Helper `_accept(payload)` dipakai canary + contract test.

## Draft RED test — `tests/test_content_studio_desktop_safe_acceptance_contract.py`

```python
"""Phase 21 contract — RED pertama: fixture script & canary registration belum ada."""
from __future__ import annotations
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "content_studio_desktop_safe_acceptance.py"


def _fixture_module():
    spec = importlib.util.spec_from_file_location("content_studio_acceptance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_content_studio_acceptance_script_exists_and_exposes_main():
    module = _fixture_module()          # RED: FileNotFoundError (script belum ada)
    assert callable(module.main)


def test_accept_payload_requires_title_and_reorder_verified_blocks():
    module = _fixture_module()
    ok = {"accepted": True,
          "title": {"executed": True, "verified": True},
          "reorder": {"executed": True, "verified": True}}
    assert module._accept(ok) is True
    assert module._accept({"accepted": True}) is False
    assert module._accept({**ok, "title": {"executed": True, "verified": False}}) is False
```

RED kedua — tambahan di `tests/test_desktop_safe_canary.py`:

```python
def test_canary_covers_content_studio_title_and_reorder():
    module = _canary_module()
    names = [name for name, _ in module._FIXTURES]
    assert "content_studio_title" in names      # RED: belum ada
    assert "content_studio_reorder" in names    # RED: belum ada
```

## Validasi & gates (saat eksekusi, setelah approval)

- RED (2 file gagal nyata) → GREEN (script + canary) → isolated staged-only canary.
- `jarvis/automation.*` dan `jarvis/agent/tools/*` TIDAK ada di MAPPING editable jarvis-mk50 → RED valid tanpa conftest anti-editable; tetap diverifikasi saat run.
- `py_compile` 4 file, `ruff`, `git diff --check`, `python scripts/verify_frozen.py` (`094b696`), production/privacy scan (payload tidak memuat teks window/field/path/koordinat).
- Manual fixture run (`python scripts/content_studio_desktop_safe_acceptance.py`) — approval terpisah Takeda (menjalankan UI di desktop; drag fisik memindahkan kursor sesaat). Hasil = `fixture-accepted`, bukan `live-proven`.
- Independent exact-hash review → approval → commit.
- Usulan 2 commit kecil: (1) script fixture + contract test; (2) canary registration + test update.

## Risiko & mitigasi

| Risiko | Mitigasi |
|---|---|
| Drag fisik pyautogui vs drag-loop modal Qt (event loop) | Pola QTimer + `QTest.qWait` seperti click acceptance; bila QListWidget InternalMove flaky di bawah input sintetis → custom drop target di fixture (tetap production path, fixture-side) |
| `pyautogui.FAILSAFE=True` — kursor user di corner membatalkan drag | Run manual: user tidak menyentuh mouse selama run |
| RuntimeId/ValuePattern tidak tersedia untuk QLineEdit/QListWidget | Inilah yang dibuktikan; bila UIA tak expose → temuan jujur, fixture disesuaikan (QLineEdit = edit control ber-ValuePattern, high confidence) |
| `_uia_parent_runtime_id` sama untuk kedua card | QListWidget: semua item satu list container, high confidence; diverifikasi di run |
| Window fixture harus aktif untuk drag | `activateWindow()` + `raise_()` (pola click acceptance); run saat Takeda siap |

## Batas

- Disposable fixture only: tidak ada filesystem/drop zone, aplikasi user, network, retry setelah aksi.
- Tidak ada perubahan provider/credential/live integration/authority/frozen.
- Hasil acceptance tidak pernah dipromosikan ke `live-proven`.
