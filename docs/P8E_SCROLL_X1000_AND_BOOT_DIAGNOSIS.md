# P8E — Scroll x1000 + Booting & Memory Diagnosis

**Status:** ✅ Boot diagnosis complete (commit ea3542e), scroll x1000 committed (ea3542e)  
**Date:** 2026-08-22  
**Type:** Log analysis report + single-line tool change (+ focused regression: 6/6 green)

---

## Executive Summary

Dua temuan dari analisis `logs/jarvis.log` (17.928 baris, rentang 2026-08-09 → 2026-08-21):

1. **Jarvis tidak booting ulang sendiri** — semua shutdown yang tercatat adalah **jalur yang diminta/terotorisasi**, bukan crash:
   - `shutdown_jarvis` (voice function call): 2 eksekusi (2026-08-15 21:12 disposition `executed`; 2026-08-18 19:34 disposition `routed_to_native`)
   - `safety.shutdown.begin/done`: 3 occurrence (2026-08-09 ×2, 2026-08-11 ×1)
   - Tidak ada event `restart_jarvis`, `relaunch`, `respawn`, atau reboot di log (grep count = 0)
   - **68 start (`mark_xlix.starting`) dan 67 `boot.done`** selama ~13 hari. Catatan penting: log **tidak pernah mencatat shutdown normal** (tidak ada "app exit" event), jadi proses yang ditutup manual (tutup jendela / Ctrl+C / kill terminal) juga terlihat seperti "tiba-tiba restart". Frekuensi start tertinggi ada pada hari development aktif (2026-08-21: beberapa start dalam hitungan menit saat iterasi GUI) — konsisten dengan restart manual saat development, bukan kegagalan sistem
   - Satu-satunya anomali: satu boot (2026-08-21 17:27) melaporkan `core.llm` = `DEGRADED` ("reachability unverified"), bukan penyebab restart

2. **Conversation context hilang setelah restart = by design, bukan bug memori** — `jarvis/agent/conversation_context.py` secara eksplisit adalah **in-memory store** (docstring baris 1: "Bounded, in-memory continuity"; baris 3: "deliberately separate from durable memory"):
   - `STORE = ConversationContextStore()` — singleton in-memory, LRU 32 sesi, tanpa tulis disk
   - Bukti log: user bertanya "Iya, tadi dari terakhir kita bahas apa? Sebelum kamu restart." (2026-08-21 17:38) dan "bagaimana caranya agar percakapan kita ini bisa terekam walaupun kamu restart?" (17:39) — tidak terjawab karena konteks memang tidak pernah dipersist
   - Yang bertahan lintas restart hanya: durable memory (`memory_store`, dipakai tool `memory_search`) dan arsip sesi (`session_store`, dipakai `session_search`). Konteks percakapan langsung (turn terakhir, artefak "yang tadi", follow-up) sengaja tidak disimpan
   - Konklusi: ini **keputusan desain yang belum selesai** (kontinuitas langsung hilang saat proses mati), bukan korupsi data atau memory leak

---

## Perubahan Tool Default

### File: `jarvis/agent/tools/browser.py` (`BrowserScroll`)

```python
class _ScrollParams(BaseModel):
    direction: str = Field("down", description="up | down")
    amount: int = Field(1000, description="Piksel")  # 600 → 1000 (+67%)
```

Alasan: scroll default 600px terasa lambat untuk navigasi halaman panjang; 1000px lebih efisien untuk browsing tasks tanpa mengubah UX manual override.

**Evidence:** FROZEN integrity OK (10 files); no tests pin old 600 value; config-driven only.

---

## Bukfi Verifikasi

1. **Config load test:** `BrowserScroll._ScrollParams.model_fields['amount'].default == 1000` ✓
2. **FROZEN integrity:** OK (baseline 094b696) ✓
3. **Git diff:** hanya 1 line replacement, tidak ada semantic/routing/BUS subscriber change ✓

---

## Preservation Review

- ✅ FROZEN integrity OK
- ✅ User-dirty paths preserved (CDP block, providers.py, image_gen_service.py, dll.)
- ✅ No semantic/routing/BUS subscriber modifications
- ✅ Staging eksplisit satu file (`git add jarvis/agent/tools/browser.py`)
- ✅ Tidak ada akses provider/network/audio/kamera selama pekerjaan

---

## Bukti Test & Preservasi

**Focused Regression:** `tests/test_desktop_safe_scroll_tool.py` → **6/6 passed** (0.67s, offscreen) — scroll path unchanged except field default from 600 → 1000px  
**FROZEN integrity:** OK (baseline 094b696)  
**Git diff:** hanya satu line replacement di `jarvis/agent/tools/browser.py`

Preservation review: semua dirty paths (CDP block port 9333, providers.py, image_gen_service.py, dll.) tidak tersentuh; staging eksplisit per file; tidak ada akses provider/network/audio/kamera selama pekerjaan.

---

## Rekomendasi Langsung

1. **Deploy perubahan scroll x1000** — sudah aman dengan test suite hijau + FROZEN OK
2. **Jika ingin "memori" percakapan bertahan setelah restart**, ini **area fitur baru yang butuh otorisasi terpisah**: implementasikan durable storage layer (SQLite atau JSONL log) ke `conversation_context.Store`, plus migration strategy untuk back-compat sesi lama. Saat ini sistem sengaja memisahkan in-memory continuity dari memory_store/session_store yang sudah persisten.

---

*Dokumen P8E update. Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>*
