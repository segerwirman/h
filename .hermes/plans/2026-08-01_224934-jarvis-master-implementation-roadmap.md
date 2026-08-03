# JARVIS Master Implementation Roadmap

> **Untuk sesi berikutnya:** jalankan tepat satu fase pada satu waktu. Baca berurutan: `session.md`, roadmap master ini, `JARVIS.MD`, `.hermes/handoffs/current.md`, `.hermes.md`, lalu roadmap domain yang disebut `session.md`. Gunakan strict TDD, verification gates, independent review, dan jangan mulai fase berikutnya tanpa instruksi Takeda.

## Tujuan

Mengonsolidasikan seluruh rencana pasca-Phase-20 menjadi satu urutan implementasi yang aman: menstabilkan worktree, membuat recovery commits, membuktikan desktop-safe melalui production-path fixture acceptance, menyelesaikan UX Content Studio, menambah reliability/canary, lalu membangun native timer dan WhatsApp two-way call agent dengan memory serta Calendar proposal—tanpa payment, OTP, generic remote UIA, atau broad desktop authority.

## Aturan penyelesaian setiap fase

Setiap fase hanya boleh disebut **COMPLETE** jika seluruh poin berikut terpenuhi:

1. baseline worktree dan frozen fingerprint dicatat sebelum edit;
2. focused RED dibuat dan benar-benar gagal karena capability belum ada/gap nyata;
3. implementasi GREEN minimal terwiring ke production seam yang diminta;
4. negative/safety cases lulus;
5. focused regression dan relevant cross-boundary regression lulus;
6. changed Python `py_compile` lulus;
7. `git diff --check` lulus (CRLF advisory boleh dicatat);
8. `python scripts/verify_frozen.py` tetap OK;
9. independent review selesai dan blocker ditangani;
10. `session.md`, `JARVIS.MD`, `.hermes/handoffs/current.md`, `.hermes.md`, serta roadmap relevan diperbarui;
11. laporan final selalu menulis **Fase berikutnya**, tujuan, file/layer, dan guardrail;
12. jangan otomatis mengimplementasikan fase berikutnya.

## Format laporan akhir wajib

```text
FASE <ID> — <NAMA>: COMPLETE / PARTIAL / BLOCKED

Deliverable:
- ...

Authority/privacy/frozen boundary:
- ...

Evidence:
- RED ...
- GREEN ...
- regression ... passed
- py_compile ...
- diff check ...
- frozen baseline ...

Risiko/batas live proof:
- ...

FASE BERIKUTNYA: <ID> — <NAMA>
Tujuan: ...
Scope: ...
Guardrail: ...
```

---

# TRACK 0 — STABILISASI DAN RECOVERY

## Phase 20.1 — Tool Catalog Completeness & Desktop Resource Serialization

**Status:** ✅ COMPLETE — 2026-08-02

**Tujuan:** menutup satu regression aktif: tool baru jatuh ke fallback `Other`; semua desktop-safe tools harus memiliki grup eksplisit dan exclusive resource `desktop`.

**Implementasi:**
- explicit groups untuk desktop-safe, Content Studio, native system, native messaging, voice briefing, web monitoring, dan YouTube voice;
- `MODULE_RESOURCES` memetakan semua `desktop_safe_*`, `desktop_observe`, dan `desktop_visual_observe` ke `desktop`;
- disabled group tetap mengecualikan schema hanya pada session baru.

**File utama:** `jarvis/agent/toolgroups.py`, `tests/test_toolgroups_usage.py`.

**Acceptance:** production `all_groups()` tidak mempunyai fallback `other`; desktop-safe dan generic computer tidak berjalan paralel.

**Outcome:** 48/48 source tool modules dan 99 runtime tools terpetakan tanpa duplicate/unmapped. Sembilan desktop-safe tools memakai exclusive resource `desktop`; Content Studio model-only tetap resource-free. Optional safe Google/briefing modules telah pre-mapped tanpa provider enablement atau authority expansion.

**Evidence:** focused 13 passed; final matrices 259 + 93 = 352 passed; `py_compile`, diff check, frozen baseline `094b696`, dan independent static review semuanya PASS. Tidak ada staging/commit.

**Successor:** **20.2 — Continuity Cleanup**, completed 2026-08-02 tanpa runtime expansion.

---

## Phase 20.2 — Continuity & Audit Metadata Cleanup

**Status:** ✅ COMPLETE — 2026-08-02

**Tujuan:** menghapus marker stale dan membuat semua handoff menyatakan baseline/fase/next phase yang sama.

**Implementasi:**
- hapus placeholder update dan Phase-20 deferred text yang sudah usang;
- catat evidence fresh Phase 20.1;
- dokumentasikan perbedaan source-present/configured/runtime-wired/tested/live-proven;
- bootstrap dan enforce `session.md` update protocol.

**File:** `session.md`, `JARVIS.MD`, `.hermes/handoffs/current.md`, `.hermes.md`, roadmap master dan roadmap domain.

**Acceptance:** repo-wide search tidak menemukan status fase yang kontradiktif.

**Outcome:** continuity docs dan roadmap aktif telah disinkronkan; marker `Phase 21` sebagai immediate-next pada roadmap lama ditandai superseded; current next phase konsisten menjadi 20.3. Evidence capability tidak lagi menganggap source, registry, unit/fake test, atau disposable fixture sebagai live proof.

**Evidence:** stale-marker/next-phase search PASS; Markdown UTF-8/fence/whitespace + manual review PASS; tracked-worktree `git diff --check` PASS dengan advisory CRLF lama yang tidak terkait; untracked Markdown divalidasi terpisah karena Git diff tidak mencakupnya; frozen baseline `094b696` OK; non-document files dan Git index tidak berubah; independent documentation review PASS. Tidak ada Python test/compile karena scope hanya Markdown.

### Evidence vocabulary (canonical)

| Label | Arti minimum |
|---|---|
| `source-present` | Implementasi statis ditemukan; tidak membuktikan aktif/configured. |
| `configured` | Prasyarat konfigurasi/credential/device dinyatakan siap melalui pemeriksaan non-secret yang relevan; tidak diwariskan dari source. |
| `runtime-wired` | Ada production registry/boot/consumer seam; wiring yang conditional tetap bukan bukti configured atau running. |
| `focused-tested` | Automated focused tests benar-benar lulus; fake/mock/offscreen tetap hanya test proof. |
| `fixture-accepted` | Production path dijalankan pada fixture disposable/local yang dibatasi; bukan external/user-surface live proof. |
| `live-proven` | Explicit approved run berhasil pada service/device/surface nyata dan dicatat terpisah. |

### Capability audit snapshot after Phase 20.2

`yes` berarti label itu memiliki bukti durable; `not established` berarti Phase 20.2 tidak memeriksa/menjalankannya; `n/a` berarti label tidak relevan. Kolom tidak saling mengimplikasikan.

| Capability | source-present | configured | runtime-wired | focused-tested | fixture-accepted | live-proven |
|---|---:|---:|---:|---:|---:|---:|
| Phase 20.1 tool catalog/resource mapping | yes | n/a | yes | yes | not established | not established |
| Desktop-safe foundational click/scroll/value/select/toggle lane | yes | n/a | yes | yes | not established; scripts/plans alone are not execution evidence | not established on user apps |
| Phase 19 title setter | yes | n/a | yes | yes | not established; Phase 21 planned | not established |
| Phase 20 scene reorder | yes | n/a | yes | yes | not established; Phase 21 planned | not established |
| Monitor 17A–17M | yes | source/job readiness not established | yes | yes | yes, 17L fixed local fixtures | external-source/delivery live proof not established |
| Content Studio A/D local model/UI/export | yes | n/a | yes | yes | not established | not established |
| Studio B image-provider lane | yes | provider state not established | conditional yes | yes with fake provider | not established | not established |
| Telegram paired gateway/read/proposal/media | yes | pairing/token state not established | conditional yes | yes | not established | not established |
| Google Workspace/Gmail/Calendar/briefing | yes | OAuth/account state not established | conditional yes | yes | not established | not established |
| Gemini Live/native voice mediation | yes | model/mic/audio state not established | conditional yes | yes | not established | not established |
| WhatsApp bounded autonomous call program WA0–WA9 | yes, supporting components only | not established | not established as completed call-agent program | not established for WA0–WA9 | not established | not established |

**Fase berikutnya:** **20.3 — Git Worktree Segmentation & Recovery Commits**; lakukan audit read-only dahulu, lalu recovery commits dependency-complete dengan exact allowlist dan approval Takeda.

---

## Phase 20.3 — Git Worktree Segmentation & Recovery Commits

**Status:** ✅ COMPLETE — 2026-08-03 (59 commit; ditutup commit DOC `29f94cd`).

**Tujuan:** mengubah worktree besar dari initial commit menjadi checkpoint Git kecil dan reversible, tanpa reset/discard.

**Urutan commit rencana (A–J):** ⚠️ SUPERSEDED — eksekusi aktual mengikuti urutan dependency nyata: remediasi audit A46–A53 → GWS safe-read A54–A57 → telegram A58+TEL → monitoring A59–A70+MR → voice V1–V5 → closure MR/MSG/TEL/UX1/UX2/REG/CAP1/CAP2/WIN/COV/SCR → docs continuity DOC `29f94cd`. Rincian per-commit ada di `session.md`.

**Eksekusi aktual:** 59 commit, seluruhnya TDD RED→GREEN, isolated staged-only canary (conftest anti-editable wajib untuk `jarvis.monitoring.*` karena editable install jarvis-mk50), compile/Ruff, cached check, production scan, frozen `094b696`, independent exact-hash review, approval Takeda. 2 blocker nyata di-fix: A62 credential substring query, TEL remote fallthrough `yt_latest`. Select-option Tool kini native (CAP1, A27 terbuka). Desktop production path benar-benar `runtime-wired`; tidak ada `live-proven`.

**Guardrail Git:** explicit `git add <allowlist>`, bukan `git add -A`; staged diff review; targeted test; independent review; commit hanya setelah Takeda menyetujui exact staged scope. (Dipatuhi sepanjang fase.)

**Acceptance:** TERPENUHI — source/test/docs tidak tersisa untracked tanpa alasan; setiap commit dapat direvert sendiri; sisa worktree hanya 2 artifact (`.curator_state.json` timestamp noise + `full_run.txt`) yang diklasifikasi dan TIDAK di-commit.

**Fase berikutnya:** **21 — Desktop-Safe Production-Path Fixture Acceptance** — MENUNGGU KEPUTUSAN TAKEDA (DILARANG dieksekusi tanpa approval eksplisit). Prove Phase 19/20 pada disposable PyQt/UIA fixture. Hasilnya `fixture-accepted`, bukan external/user-surface `live-proven`.

---

# TRACK 1 — DESKTOP-SAFE DAN CONTENT STUDIO

## Phase 21 — Desktop-Safe Production-Path Fixture Acceptance Harness

**Status:** ✅ COMPLETE — 2026-08-03 (3 commit: PLAN `0d30794`, FIX `a109f69`, FIX2 `aaec855`).

**Tujuan:** membuktikan title setter dan scene reorder memakai production UIA backend pada fixture disposable, bukan aplikasi user.

**Implementasi:**
- fixture PyQt disposable: QLineEdit judul + QListWidget 3 scene cards, bound eksplisit via HWND;
- 21A title: observe → `set_content_title` (ValuePattern) → recapture + committed-value proof → verified;
- 21B reorder: 3 cards same parent → satu native drag (DRIVER fisik) → recapture + visual-order proof → verified;
- negative: stale ref ditolak, source==destination ditolak; fixture cleanup otomatis.

**Remediasi production yang ditemukan acceptance run (TDD RED→GREEN):**
- G1: `_element_from_control` tidak pernah mengisi `_uia_runtime_id` untuk `text_field` → `set_content_title` fail-closed di semua aplikasi; kini diisi bila tersedia (tanpa rid tetap observasi, setter tetap tolak).
- G2: listitem non-dropdown dibuang → reorder tanpa target; kini parent List tanpa ComboBox → role `card` + RuntimeId + parent identity.
- G4: RuntimeId item list TIDAK stabil pasca-reorder di UIA umum → verifikasi diubah ke same-surface recapture + jumlah card sama + urutan visual berubah; rid berubah tanpa perubahan visual → fail-closed (test negatif).
- Fixture-side: seleksi by role (UIA Name Qt kosong), aktivasi window via klik title bar (WM_MOUSEACTIVATE), drag di thread agar event loop Qt live.

**Acceptance:** production-path `fixture-accepted` TERBUKTI untuk Phase 19 & 20 (title + reorder `verified: true`); action tidak keluar fixture; external/user-app `live-proven` tetap not established. 136 regression passed; frozen `094b696` OK.

**Fase berikutnya:** **22 — Scene List Production UX** — MENUNGGU KEPUTUSAN TAKEDA; buat scene cards visible dan move controls usable.

---

## Phase 22 — Content Studio Scene List Production UX

**Status:** ✅ COMPLETE — 2026-08-03 (commit SCN `a54c9af`).

**Tujuan:** membuat scene order terlihat dan dapat diubah user secara deterministik.

**Implementasi:**
- scene list `QListWidget` visible dari `_scenes` lokal: `1. S0`, `2. S1`, ...; klik item → `select_scene()`; selection highlight + order number;
- tombol ▲ Naik / ▼ Turun deterministik → `move_selected_up/down()` → reuse `move_scene()` (policy `admit_reorder`); first-up/last-down reject (policy + button disabled);
- selected index mengikuti scene yang dipindah; **asset mapping `_asset["scene_index"]` ikut reorder** (gap nyata di-fix: f→t, pergeseran rentang);
- refresh timeline + list otomatis; accessibility identity stabil: `jarvis-scene-list`, `jarvis-scene-move-up/down` (lane Phase 21).

**Acceptance:** local-only, hidden-by-default, first-up/last-down reject, tanpa generic drag/network/export write — TERPENUHI. TDD RED 6 failed → GREEN 6 passed; regression content 41 passed; frozen `094b696` OK.

**Fase berikutnya:** **23 — Export Timing & Preview Hardening** — MENUNGGU KEPUTUSAN TAKEDA; duration policy, cumulative SRT timing, in-memory preview.

---

## Phase 23 — Content Studio Export Timing & Preview Hardening

**Status:** ✅ COMPLETE — 2026-08-03 (TIM `999c121`).

**Tujuan:** menambah duration policy, cumulative SRT timing, dan in-memory preview.

**Implementasi:**
- `jarvis/core/content_timing_policy.py` (baru, pure/in-memory): `admit_duration` int finite 1–600s (bool/float/NaN/negatif/0 ditolak), `admit_durations` total cap 3600s, `cumulative_timings`, `srt_timestamp` HH:MM:SS,mmm, `build_srt` cumulative (text-count mismatch ditolak), `default_durations` 5s backward-compat;
- `content_export`: `export_project(..., durations=)` — None → default 5s; invalid → `{ok: False}` tanpa content; `captions_srt` cumulative; `shot_list_csv` membawa `duration_s` tervalidasi; `preview_export` in-memory (storyboard + baris Timing, captions, shot-list) tanpa file write;
- sheet `preview_export(fmt, durations)`; fixed export allowlist tetap authoritative.

**Acceptance:** strings/in-memory only; no automatic file write, video render, upload, publish, destination path — TERPENUHI. RED 12 failed → GREEN 13 passed; regression 85 passed; frozen `094b696` OK.

**Fase berikutnya:** **24 — Runtime Lifecycle Reliability Sweep** — MENUNGGU KEPUTUSAN TAKEDA.

---

# TRACK 2 — RELIABILITY, READINESS, DAN LIVE PROOF

## Phase 24 — Runtime Lifecycle Reliability Sweep

**Status:** ✅ COMPLETE — 2026-08-03 (LIF `1011794`).

**Tujuan:** memastikan setiap thread/process/lease boot-started atau task-owned punya owner, stop path, join policy, dan failure state jujur.

**Implementasi:**
- `jarvis/runtime/lifecycle_audit.py` (baru): static ownership table `LIFECYCLE_OWNERSHIP` 16 entri (cron, telegram, monitor worker, awareness, voice pipeline monitor, wake, browser, sweeper, dispatch, fire-and-forget, boot, classifier) — owner/stop/join/failure state; `audit_ownership()`; `SUBPROCESS_LIMITATION` (cooperative terminate + state `terminate_requested` jujur);
- fix: `CronScheduler.stop()` join bounded (`_interval+1`); `SetupQueue.close()` join bounded (`_sweep_interval+1`);
- audit: telegram/monitor/awareness/state/wake/browser/dispatch sudah benar (bounded join + lease release di finally — dikunci test kontrak); RuntimeSupervisor idempotent (test existing);
- kontrak statis: dispatch `finally` melepas slot + browser/computer/desktop-safe session.

**Acceptance:** shutdown tidak meninggalkan lease (kontrak dikunci); stop + bounded join (cron/sweeper di-fix, sisanya dikonfirmasi); timeout/cancel state jujur; batas subprocess non-killable didokumentasikan — TERPENUHI. RED 5 failed → GREEN 7 passed; regression lifecycle 74 passed; frozen `094b696` OK.

**Fase berikutnya:** **25 — Credential-Free Canary** — MENUNGGU KEPUTUSAN TAKEDA.

---

## Phase 25 — Credential-Free Integration Canary Matrix

**Status:** ✅ COMPLETE — 2026-08-03 (CAN `11430b6`).

**Tujuan:** status readiness jujur untuk Telegram, heavy provider, image, Google, WhatsApp, vision, voice tanpa membaca secret values.

**Output (implementasi):** `jarvis/runtime/credential_free_probe.py` — `probe_providers(no_voice=)` → `{telegram, google, llm, voice, image, whatsapp}` status ∈ `{ready, absent, disabled, skipped, unknown}`; `probe_summary()` metadata-only; `_has_secret` nilai → bool → dibuang; toggle off → `disabled`; `--no-voice` → voice `skipped`; image/whatsapp → `unknown` (jujur); guardrail dikunci test (tidak menulis ke secrets store, tidak mengekspos nilai, deterministik tanpa kredensial).

**Acceptance:** membedakan source-present/configured/wired/tested/live; no token/account/path/raw exception — TERPENUHI. RED 7 failed → GREEN 7 passed; regression 38 passed; frozen `094b696` OK.

**Fase berikutnya:** **WA0 — WhatsApp Call Readiness Truth**; specialization untuk call/audio hardware — MENUNGGU KEPUTUSAN TAKEDA.

---

# TRACK 3 — NATIVE TIMER DAN WHATSAPP CALL AGENT

## Phase WA0 — WhatsApp Call Capability & Hardware Readiness

**Status:** ✅ COMPLETE (bagian readiness gate) — 2026-08-03 (WAR `9ec2bb0`).

**Tujuan:** melaporkan kesiapan call secara aman sebelum autonomous call.

**Implementasi (readiness gate):** `jarvis/integrations/whatsapp_readiness.py` — `dependency_available()` (SDK via `find_spec`), `credentials_ready()` (token + phone_id; absence → False bukan crash), `toggle_enabled()`, `allowlist_configured()` (policy placeholder), `client_available()` (dependency AND credentials), `service_available()` (client AND toggle AND allowlist), `readiness()`/`readiness_summary()` metadata-only; probe canary `whatsapp` kini status nyata (`ready`/`absent`/`disabled`).

**Belum dikerjakan (call/hardware lane, fase call berikutnya):** Playwright/profile/login check, call button check, Gemini Live instance check, distinct virtual cables, streams, live-proof state. Metadata-only; tidak membuat call.

**Acceptance (gate):** offline penuh; tanpa kredensial nyata, jaringan, live client; hanya gate boolean — TERPENUHI. RED 8 failed → GREEN 8 passed; regression 15 passed; frozen `094b696` OK.

**Fase berikutnya:** **WA1 — Native Countdown Timer** — MENUNGGU KEPUTUSAN TAKEDA.

---

## Phase WA1 — Native Countdown Timer

**Status:** ✅ COMPLETE (intisari) — 2026-08-03 (TIM2 `3e53f91`).

**Tujuan:** timer native terpisah dari dated reminder/Calendar.

**Tools (implementasi):** start (`start_countdown`) / cancel (`cancel_countdown`) — single bounded timer; status via orb progress + bus signals.

**Policy (implementasi):** 1–3600 detik bounded int, monotonic deadline (anti-drift), exact-once expiry (`timer.finished` sekali), local BUS/UI, clean shutdown (driver auto-stop), no shell task per timer.

**Belum dikerjakan (timer lanjutan):** — multi-timer bersamaan, pause/resume, status list, TTS announcement, duplicate label clarify, 7-hari rentang: ✅ COMPLETE (TIM3 `d989dd3`, 2026-08-03) — multi-timer bounded 8, label unik, pause/resume anti-drift, status_list, due + announce opsional; sisa: wire ke UI/facade (opsional).

**Acceptance (intisari):** lifecycle + transisi status + bus signal teruji (RED 10 → GREEN 11); countdown tidak memakai Task Scheduler — TERPENUHI. Regression window 35 passed; frozen `094b696` OK.

**Fase berikutnya:** **WA2 — Call Session & Local Approval Authority** — MENUNGGU KEPUTUSAN TAKEDA.

---
## Phase WA2 — WhatsApp Call Session Model & Local Approval Sheet

**Status:** ✅ COMPLETE (state machine inti) — 2026-08-03 (CAL `bbd6437`).

**Tujuan:** setiap call terikat satu contact, objective, constraints, allowed disclosures, TTL, dan local approval.

**Objective awal:** general inquiry, hotel availability, flight schedule, appointment, customer support information, reversible hold request.

**State (implementasi):** idle → awaiting → active → done / cancelled / expired (TTL monotonic 30–3600s); remote proposal ENUM-only (`RemoteCallProposal` ACCEPT/DECLINE/END/EXTEND) tanpa eksekusi; `approve()` lokal one-shot; end/cancel idempotent; `result()` metadata-only (tanpa transcript/audio/path/raw — dikunci test); bus `call.*` ringan hanya session_id.

**Belum dikerjakan (call lanjutan):** — DIALING → CONNECTED → AWAITING_DECISION/FAILED states, constraints & allowed disclosures field, approval sheet UI: ✅ COMPLETE (CST `3cd527d`, 2026-08-03) — states + constraints + allowed disclosures + ApprovalSheet metadata-only; sisa: tidak ada.

**Acceptance:** tidak ada call tanpa approved session; payment/account recovery/sensitive secrets ditolak; actor/session/TTL/one-shot/metadata result — TERPENUHI (state machine inti). RED 8 failed → GREEN 8 passed; regression 33 passed; frozen `094b696` OK.

**Fase berikutnya:** **WA3 — Two-Way Audio Live Acceptance** — MENUNGGU KEPUTUSAN TAKEDA.

---

## Phase WA3 — Two-Way Audio Acceptance

**Status:** ✅ COMPLETE (harness) — 2026-08-03 (AUD `6bed7a2`).

**Tujuan:** membuktikan existing two-cable bridge pada hardware nyata.

**Implementasi (harness):**
- `jarvis/core/call_audio.py`: `CallAudioProof` — start hanya untuk session `active` (approved lokal WA2); stop via session cancel/end; inbound+outbound via injected `capture`/`playback` (fixture-only; STT/TTS/voice_listener FROZEN tidak disentuh);
- `admit_duration` int 1–600s; deadline monotonic; `stop()` idempotent; `result()` metadata-only + `audio_exercised` jujur (tanpa fungsi audio → False); bus `call.audio.started/done` ringan.

**Belum dikerjakan (live acceptance):** hardware nyata (two-cable bridge, virtual cables) — live proof memerlukan sesi acceptance manual terpisah; `live-proven` tetap tidak established.

**Acceptance (harness):** dua arah audio path teruji via fixture; bounded duration; tanpa remote control/authority baru — TERPENUHI. RED 9 failed → GREEN 9 passed; regression 35 passed; frozen `094b696` OK.

**Fase berikutnya:** **WA4 — Bounded Autonomous Call Dialogue** — MENUNGGU KEPUTUSAN TAKEDA.

---

## Phase WA4 — Bounded Autonomous Call Dialogue

**Status:** ✅ COMPLETE — 2026-08-03 (DIA `3e20ad1`).

**Tujuan:** turn-based bounded dialogue dalam sesi call yang sudah di-approve.

**Implementasi:**
- `jarvis/core/call_dialogue.py`: `CallDialogue` — turn alternation ketat local↔remote (double-turn ditolak); stop word (`stop/berhenti/cukup/tutup/selesai/jangan lanjut/tidak usah/sudah cukup`) → `interrupted`; secret/PII guard (marker password/token/api key/secret/kartu/norek/otp/pin/credential atau 12–19 digit → ditolak & tidak disimpan); `MAX_TURNS=20` → `completed`; terikat session active; session end/expired → ended, cancel → interrupted;
- `summary()` metadata-only (session_id/status/turn_count/sources — tanpa konten teks/transcript, dikunci test); bus `call.dialogue.turn/ended` ringan (session_id + index + source, tanpa teks).

**Acceptance:** turn policy + stop word + no PII + objective guard + summary metadata-only — TERPENUHI. RED 8 failed → GREEN 8 passed; regression 36 passed; frozen `094b696` OK.

**Belum dikerjakan (dialogue lanjutan):** one-question-at-a-time rule, confirm dates/prices/reference, escalation on payment/objective drift, simulator successful-inquiry/safe-refusal/escalation proof; live call acceptance terpisah.

**Fase berikutnya:** **WA5 — Call Memory & Privacy** — MENUNGGU KEPUTUSAN TAKEDA.

---

## Phase WA5 — Call Memory, Transcript Privacy & Recall

**Status:** ✅ COMPLETE (memory & privacy) — 2026-08-03 (MEM `b29dcba`).

**Tujuan:** JARVIS mengingat hasil call tanpa menyimpan raw audio/full transcript default.

**Retention:** volatile turn buffer → bounded call record → optional approved durable semantic memory (recall/durable memory belum dikerjakan).

**Stored (implementasi):** safe summary metadata-only (session_id, status, duration_s, turn_count) — allowlist ketat.
**Not stored (dikunci test):** PCM, full transcript, full phone, OTP/PIN/password/card/CVV/passport/account secrets; tanpa file write (in-memory).

**Implementasi:** `jarvis/core/call_memory.py` — `CallMemoryStore` in-memory ring buffer; field allowlist ketat; opt-in config `integrations.call.memory_enabled` (default False); PII/secret guard (marker + 12–19 digit); retention bounded `MAX_ENTRIES=50` evict tertua; `clear()`; `list_summaries()` metadata-only.

**Acceptance:** scoped device-local/user, retention bounded, searchable/deletable, tidak bocor ke remote memory — TERPENUHI (bagian memory). RED 7 failed → GREEN 7 passed; regression 32 passed; frozen `094b696` OK.

**Fase berikutnya:** **WA6 — Post-Call Calendar Proposal**.

---

## Phase WA6 — Post-Call Review & Calendar Proposal

**Status:** ✅ COMPLETE (proposal inti) — 2026-08-03 (CAL2 `cc97138`).

**Tujuan:** typed call outcome menjadi Calendar proposal, bukan automatic write.

**Implementasi (proposal inti):**
- `jarvis/core/calendar_proposal.py`: `CalendarProposal` one-shot draft → approved/rejected; field allowlist ketat (title 1–120, start_ts masa depan, duration 5–1440 menit; kwarg asing ditolak); `has_conflict()` anti double-booking; local approval one-shot; `result()` metadata-only;
- kontrak statis: tanpa import provider/network/write — tidak ada authority create otomatis (write path `gcal_create_proposed` fase live).

**Belum dikerjakan (review lanjutan):** mappings typed outcome (hotel stay, flight departure/arrival, service appointment, callback), timezone review, status confirmed/tentative, terms/price/reference/reminder; second local approval flow dan write path `gcal_create_proposed` (fase live).

**Acceptance (proposal inti):** field allowlist + conflict check + local approval + metadata result — TERPENUHI. RED 8 failed → GREEN 8 passed; regression 51 passed; frozen `094b696` OK.

**Fase berikutnya:** **WA7 — Reservation Commitment Gate** — MENUNGGU KEPUTUSAN TAKEDA.

---

## Phase WA7 — Inquiry vs Reservation Commitment Gate

**Status:** ✅ COMPLETE (commitment gate inti) — 2026-08-03 (RES `584b235`).

**Tujuan:** memisahkan inquiry, reversible hold, reservation without payment, financial commitment, dan sensitive identity.

**Implementasi (gate inti):** `jarvis/core/reservation_gate.py` — `ReservationCommitmentGate` gate murni: local approval (`reservation_approval_missing`); fixed disclosure labels (`commitment/cancellation_policy/no_refund/subject_to_availability`; asing → `reservation_unknown_label`; kosong → `reservation_disclosure_missing`); cancellation window 1–365 hari (`reservation_cancellation_window_missing`); failure = no-op (state tidak berubah, tidak mencatat — dikunci test); commitment tercatat hanya setelah green light sebagai metadata `ready`; reason codes closed set; tanpa auto-commit.

**Decision continuation:** ✅ COMPLETE — `jarvis/core/reservation_continuation.py` — `ExactOptionPermit` (readback exact option → local approval → short-lived permit TTL 120s; **changed term invalidates permit selamanya**); `HardBlockGuard` no-payment boundary; `simulate_decision_flow()` bukti changed-price invalidation & no-payment (RED 7 → GREEN 7; regression 116 passed; CON `b1003f9`).

**Hard block:** ✅ COMPLETE (guard) — payment, deposit, bank transfer, card, CVV, OTP, PIN, password → reason fixed `reservation_payment_hard_block`; **belum dikerjakan**: user mengambil alih official payment channel (live lane).

**Acceptance:** gate failure no-op + alasan fixed; tanpa auto-commit — TERPENUHI (gate inti). RED 7 failed → GREEN 7 passed; regression 58 passed; frozen `094b696` OK. Simulator changed-price invalidation & no-payment boundary: belum dikerjakan.

**Fase berikutnya:** **WA8 — Customer-Service Case Manager**.

---

## Phase WA8 — Customer-Service Case Manager

**Status:** ✅ COMPLETE — 2026-08-03 (CSE `25b3789`).

**Tujuan:** memperluas typed cases: service hours, appointment, order-status inquiry dengan non-secret reference, warranty, complaint ticket, callback.

**Implementasi:**
- `jarvis/core/service_case.py`: `ServiceCase` one-shot — typed fixed set `{service_hours, appointment, order_status}` (warranty/complaint/callback belum didukung — ditolak); non-secret reference (order_status wajib; secret marker/12–19 digit ditolak); field allowlist (set_note 1–300 + secret guard); disclosure policy per type (`service_hours→hours`, `appointment→appointment_availability`, `order_status→order_status_update`; payment_details tidak pernah); stop/escalation rules (secret/payment/OTP/CVV/transfer → escalated + reason fixed `service_case_secret_touch` + stop: disclose ditolak setelah escalate).

**Acceptance:** setiap case punya field allowlist, disclosure policy, stop/escalation rules; tidak ada free-form mission yang memperluas authority — TERPENUHI. RED 8 failed → GREEN 8 passed; regression 66 passed; frozen `094b696` OK.

**Fase berikutnya:** **WA9 — WhatsApp Call Agent Controlled Live Rollout** — MENUNGGU KEPUTUSAN TAKEDA.

---

## Phase WA9 — WhatsApp Call Agent Controlled Live Rollout

**Status:** ✅ COMPLETE (rollout policy) — 2026-08-03 (WRO `3fb6d2a`).

**Tujuan:** controlled rollout WhatsApp.

**Implementasi:** `jarvis/integrations/whatsapp_rollout.py` — `WhatsAppRolloutPolicy` gate outbound lokal deny-by-default: toggle config (`rollout_enabled` default False); allowlist; opt-out/revoke; rate limiting sliding 60s (5/menit); daily caps per-hari (50, reset per-hari); deny reasons fixed set.

**Acceptance:** deny-by-default + allowlist + rate limit + caps + opt-out — TERPENUHI. RED 7 failed → GREEN 7 passed; regression 81 passed; frozen `094b696` OK.

**Belum dikerjakan (live lane):** master toggle duration/turn caps, visible hangup, kill switch (web call, streams, Gemini phone state, pending permit), rollout rings (owned test account → consenting trusted contact → information-only business call → appointment inquiry → hotel/flight availability → reservation continuation without payment); live integration membutuhkan approval live terpisah.

**Fase berikutnya:** **26 — Cross-Integration Live Ring** — MENUNGGU KEPUTUSAN TAKEDA.

---

## Phase 26 — Cross-Integration Explicit Live Acceptance Ring

**Status:** ✅ COMPLETE (offline proof ring) — 2026-08-03 (RIN `fd7d999`).

**Tujuan:** exercise ring yang membuktikan rangkaian inti berjalan bersama.

**Implementasi:** `jarvis/runtime/integration_ring.py` — `run_ring()` alur deterministik offline memakai 10 modul inti WA0→WA9 bersama (readiness → rollout → countdown → session → audio → dialogue → memory → proposal → reservation → case); ring ok = semua step selesai; status gate jujur apa adanya (deny-by-default adalah hasil).

**Acceptance:** semua modul inti ter-exercise bersama; deterministik; metadata-only — TERPENUHI. RED 7 failed → GREEN 7 passed; regression 88 passed; frozen `094b696` OK.

**Belum dikerjakan (live lane):** live proof terpisah untuk voice, Telegram, heavy provider, image, Google, WhatsApp — setiap integration memerlukan explicit approval; kegagalan satu integration tidak menghapus offline readiness lain; evidence live tidak dicampur dengan unit claims.

**Fase berikutnya:** **27 — Named Local Capability Facade** — MENUNGGU KEPUTUSAN TAKEDA.

---

# TRACK 4 — BOUNDED CAPABILITY EXPANSION

## Phase 27 — Named Local Capability Facade

**Status:** ✅ COMPLETE — 2026-08-03 (FAC `aaa4dba`).

**Tujuan:** komposisi lokal yang dipanggil agent dengan nama eksplisit.

**Implementasi:** `jarvis/core/local_facades.py` — `LocalFacadeRegistry` komposisi lokal bernama: steps fixed tuple immutable, deny-unknown (`facade_unknown`), langkah gagal → berhenti + report per-step; facade default `check_order_status` (ServiceCase WA8) & `book_reservation` (CalendarProposal WA6 → ReservationCommitmentGate WA7).

**Acceptance:** facade bernama; fixed steps; deny-unknown; tanpa authority baru — TERPENUHI. RED 8 failed → GREEN 8 passed; regression 96 passed; frozen `094b696` OK.

**Belum dikerjakan (facade lanjutan):** — enum facade untuk capability lain — Content Studio title/reorder, Focus Mode, browser media, timer, approved call-session start/status/hangup; permanent reject rules; per-capability policy/confirmation/verification: ✅ COMPLETE (CAP `7e72d79`, 2026-08-03) — enum 8 capability + permanent rejects + per-capability allowlist/confirmation; sisa: wire ke desktop tools nyata (fixture acceptance per capability, fase terpisah).

**Fase berikutnya:** **28 — Mediated Remote Facade** — MENUNGGU KEPUTUSAN TAKEDA.

---

## Phase 28 — Mediated Remote Proposal Facade

**Status:** ✅ COMPLETE (bridge inti) — 2026-08-03 (RMF `0cae0a2`).

**Tujuan:** facade lokal hanya diekspos ke remote sebagai proposal termediasi.

**Implementasi:** `jarvis/core/remote_facade_bridge.py` — `RemoteFacadeBridge`: remote HANYA `propose` (deny-unknown → `facade_unknown`; args disimpan LOKAL); `remote_view()`/`pending()` metadata-only tanpa args; eksekusi hanya via `approve()`/`reject()` LOKAL — one-shot + TTL 300s (`proposal_expired`); bridge TANPA `invoke`/`execute`/`run`; `result(pid)` metadata-only; status `awaiting_approval → done/failed/rejected/expired`.

**Acceptance:** remote hanya propose; approval lokal; tanpa invoke remote — TERPENUHI. RED 8 failed → GREEN 8 passed; regression 104 passed; frozen `094b696` OK.

**Belum dikerjakan (actor binding lanjutan):** paired remote actor identity binding; larangan eksplisit remote menerima UIA refs/transcript/audio/path.

**Fase berikutnya:** **29 — Next Exact Trusted UI Surface** — MENUNGGU KEPUTUSAN TAKEDA.

---

## Phase 29 — Optional Next Trusted UI Surface

**Status:** ✅ COMPLETE — 2026-08-03 (UIF `27c71f8`).

**Tujuan:** satu semantic action baru hanya setelah Takeda menentukan exact app/widget/use-case.

**Implementasi (surface dipilih: window countdown → facade):** facade `start_countdown` di `local_facades.py` (komposisi WA1 CountdownTimer) + `MainWindow(services, facades=None)` — window countdown route via facade invoke; UI TIDAK pernah bypass facade (test deny registry → False + `_countdown is None`); `invoke` mengembalikan `artifacts` LOKAL ONLY (timer) — remote view/bridge tidak pernah menyertakan.

**Selection gate:** stable role/RuntimeId, bounded/reversible action, local confirmation, fresh recapture, no filesystem/login/payment/permission/terminal/remote ingress — dipatuhi (offscreen test, tanpa authority baru).

**Acceptance:** fixture acceptance + offscreen test; tanpa authority baru — TERPENUHI. RED 2 failed → GREEN 13 passed; regression 63 passed; frozen `094b696` OK.

**Fase berikutnya:** ditentukan Takeda setelah audit Phase 29; tidak dipilih otomatis. **ROADMAP UTAMA 20.1 → 29 SELESAI.**

---

# Urutan eksekusi final

```text
20.1 → 20.2 → 20.3
→ 21 → 22 → 23
→ 24 → 25
→ WA0 → WA1 → WA2 → WA3 → WA4 → WA5 → WA6 → WA7 → WA8 → WA9
→ 26 → 27 → 28 → 29
```

# Immediate next phase

**WA4-lanjutan — Dialogue Lanjutan** (MENUNGGU KEPUTUSAN TAKEDA; DILARANG dieksekusi tanpa approval eksplisit).
Scope: one-question-at-a-time rule, confirm dates/prices/reference, escalation on payment/objective drift, simulator successful-inquiry/safe-refusal/escalation proof.
Guardrail: tidak ada eksekusi tanpa approval eksplisit Takeda; untuk setiap commit — exact allowlist, staged diff review, targeted tests, frozen, independent review, approval Takeda; jangan mengubah provider/credential/live integration/authority/frozen.
