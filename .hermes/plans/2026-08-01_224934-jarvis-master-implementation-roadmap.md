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

**Status:** NEXT — not started.

**Tujuan:** mengubah worktree besar dari initial commit menjadi checkpoint Git kecil dan reversible, tanpa reset/discard.

**Urutan commit:**
1. capability context/registry/policy/toolgroups;
2. Telegram gateway + secure remote setup/read;
3. remote proposal + verified media;
4. monitoring 17A–17M;
5. Content Studio A–D;
6. desktop-safe foundation + Phase 19/20;
7. GWS safe-read + briefing + provider UX;
8. voice native bridge + mediated voice;
9. privacy helper + awareness cleanup;
10. continuity snapshot.

**Guardrail Git:** explicit `git add <allowlist>`, bukan `git add -A`; staged diff review; targeted test; independent review; commit hanya setelah Takeda menyetujui exact staged scope.

**Acceptance:** source/test/docs tidak tersisa untracked tanpa alasan; setiap commit dapat direvert sendiri.

**Fase berikutnya:** **21 — Desktop-Safe Production-Path Fixture Acceptance**; prove Phase 19/20 pada disposable PyQt/UIA fixture. Hasilnya `fixture-accepted`, bukan external/user-surface `live-proven`.

---

# TRACK 1 — DESKTOP-SAFE DAN CONTENT STUDIO

## Phase 21 — Desktop-Safe Production-Path Fixture Acceptance Harness

**Tujuan:** membuktikan title setter dan scene reorder memakai production UIA backend pada fixture disposable, bukan aplikasi user.

**Implementasi:**
- fixture PyQt dengan stable automation IDs;
- title field live observe → local confirmation → ValuePattern → recapture/value proof;
- tiga scene cards → distinct RuntimeIds + same parent → one reorder → semantic-order proof;
- reject stale surface, parent mismatch, changed RuntimeId, no-op, lease conflict;
- fixture cleanup.

**Acceptance:** production-path `fixture-accepted` proof dipisah jelas dari unit tests; action tidak dapat keluar fixture; external/user-app `live-proven` status tetap terpisah.

**Fase berikutnya:** **22 — Scene List Production UX**; buat scene cards visible dan move controls usable.

---

## Phase 22 — Content Studio Scene List Production UX

**Tujuan:** membuat scene order terlihat dan dapat diubah user secara deterministik.

**Implementasi:** scene cards, selection, order number, Move Up/Down, selected mapping, timeline/asset sync, stable accessibility identity. Reuse `move_scene()`; jangan duplicate policy.

**Acceptance:** local-only, hidden-by-default, first-up/last-down reject, no generic drag/network/export write.

**Fase berikutnya:** **23 — Export Timing & Preview Hardening**.

---

## Phase 23 — Content Studio Export Timing & Preview Hardening

**Tujuan:** menambah duration policy, cumulative SRT timing, dan in-memory preview.

**Implementasi:** finite bounded duration, total project cap, valid SRT, preview storyboard/captions/shot-list; fixed export allowlist tetap source of truth.

**Acceptance:** strings/in-memory only; no automatic file write, video render, upload, publish, destination path.

**Fase berikutnya:** **24 — Runtime Lifecycle Reliability**.

---

# TRACK 2 — RELIABILITY, READINESS, DAN LIVE PROOF

## Phase 24 — Runtime Lifecycle Reliability Sweep

**Tujuan:** memastikan setiap thread/process/lease punya owner, stop, join, timeout, dan failure state yang jujur.

**Scope:** agent workers, voice, monitor, Telegram, cron, wake, browser/computer leases, OAuth/composer worker, normal boot dan `--no-voice`.

**Acceptance:** clean shutdown evidence; lease selalu released; non-killable subprocess limitation didokumentasikan, bukan disembunyikan.

**Fase berikutnya:** **25 — Credential-Free Canary Matrix**.

---

## Phase 25 — Credential-Free Integration Canary Matrix

**Tujuan:** status readiness jujur untuk Telegram, heavy provider, image, Google, WhatsApp, vision, voice tanpa membaca secret values.

**Output:** `component`, `configured`, `runtime_wired`, `live_proof`, fixed `reason_code`.

**Acceptance:** membedakan source-present/configured/wired/tested/live; no token/account/path/raw exception.

**Fase berikutnya:** **WA0 — WhatsApp Call Readiness Truth**; specialization untuk call/audio hardware.

---

# TRACK 3 — NATIVE TIMER DAN WHATSAPP CALL AGENT

## Phase WA0 — WhatsApp Call Capability & Hardware Readiness

**Tujuan:** melaporkan kesiapan call secara aman sebelum autonomous call.

**Checks:** Playwright/profile/login, call button, Gemini Live instance, distinct virtual cables, streams, live-proof state. Metadata-only; tidak membuat call.

**Acceptance:** user mendapat alasan fixed kenapa call belum ready, tanpa nomor/profile URL/QR/audio/raw exception.

**Fase berikutnya:** **WA1 — Native Countdown Timer**.

---

## Phase WA1 — Native Countdown Timer

**Tujuan:** timer native terpisah dari dated reminder/Calendar.

**Tools:** create/list/status/pause/resume/cancel.

**Policy:** 1 detik–7 hari, max active bounded, monotonic deadline, duplicate label clarify, exact-once expiry, local BUS/UI/TTS, clean shutdown, no shell task per timer.

**Acceptance:** multiple timer + lifecycle + voice declarations teruji; countdown tidak memakai Task Scheduler.

**Fase berikutnya:** **WA2 — Call Session & Local Approval Authority**.

---

## Phase WA2 — WhatsApp Call Session Model & Local Approval Sheet

**Tujuan:** setiap call terikat satu contact, objective, constraints, allowed disclosures, TTL, dan local approval.

**Objective awal:** general inquiry, hotel availability, flight schedule, appointment, customer support information, reversible hold request.

**State:** DRAFT → AWAITING_APPROVAL → APPROVED → DIALING → CONNECTED → AWAITING_DECISION/COMPLETED/FAILED/CANCELLED/EXPIRED.

**Acceptance:** tidak ada call tanpa approved session; payment/account recovery/sensitive secrets ditolak.

**Fase berikutnya:** **WA3 — Two-Way Audio Live Acceptance**.

---

## Phase WA3 — Two-Way Audio Acceptance

**Tujuan:** membuktikan existing two-cable bridge pada hardware nyata.

**Implementasi:** device uniqueness, loopback tone, latency/drop/sample-rate telemetry, stream cleanup, owned test account call, one concurrent call maximum.

**Acceptance:** PCM nyata terbukti dua arah; UI status/text bukan proxy audio proof.

**Fase berikutnya:** **WA4 — Bounded Autonomous Call Dialogue**.

---

## Phase WA4 — Bounded Autonomous Call Dialogue

**Tujuan:** JARVIS berbicara menuju objective yang disetujui tanpa unrestricted phone-agent authority.

**Rules:** honest assistant disclosure where needed, one question at a time, confirm dates/prices/reference, max duration/turns, remote speech treated as untrusted data, no arbitrary tool calls, hang up/escalate on secret/payment/objective drift.

**Acceptance:** simulator membuktikan successful inquiry, safe refusal, and escalation; live call separately approved.

**Fase berikutnya:** **WA5 — Call Memory & Transcript Privacy**.

---

## Phase WA5 — Call Memory, Transcript Privacy & Recall

**Tujuan:** JARVIS mengingat hasil call tanpa menyimpan raw audio/full transcript default.

**Retention:** volatile turn buffer → bounded call record → optional approved durable semantic memory.

**Stored:** safe summary, confirmed facts, unresolved items, quoted price, reference code, duration/outcome.
**Not stored:** PCM, full transcript, full phone, OTP/PIN/password/card/CVV/passport/account secrets.

**Acceptance:** scoped device-local/user, retention bounded, searchable/deletable, tidak bocor ke remote memory.

**Fase berikutnya:** **WA6 — Post-Call Calendar Proposal**.

---

## Phase WA6 — Post-Call Review & Calendar Proposal

**Tujuan:** typed call outcome menjadi Calendar proposal, bukan automatic write.

**Mappings:** hotel stay, flight departure/arrival, service appointment, callback. Exact local review mencakup timezone, status confirmed/tentative, terms, price, reference, reminder.

**Acceptance:** second local approval wajib; ambiguous date/time clarifies; reuse existing `gcal_create_proposed` sebagai satu-satunya write path.

**Fase berikutnya:** **WA7 — Reservation Commitment Gate**.

---

## Phase WA7 — Inquiry vs Reservation Commitment Gate

**Tujuan:** memisahkan inquiry, reversible hold, reservation without payment, financial commitment, dan sensitive identity.

**Decision continuation:** exact option/price/fees/date/cancellation readback → local approval → short-lived exact-option permit. Changed term invalidates permit.

**Hard block:** payment, deposit, bank transfer, card, CVV, OTP, PIN, password; user mengambil alih official payment channel.

**Acceptance:** simulator membuktikan changed-price invalidation dan no-payment boundary.

**Fase berikutnya:** **WA8 — Customer-Service Case Manager**.

---

## Phase WA8 — Customer-Service Case Manager

**Tujuan:** memperluas typed cases: service hours, appointment, order-status inquiry dengan non-secret reference, warranty, complaint ticket, callback.

**Acceptance:** setiap case punya field allowlist, disclosure policy, stop/escalation rules; tidak ada free-form mission yang memperluas authority.

**Fase berikutnya:** **WA9 — Controlled Live Rollout**.

---

## Phase WA9 — WhatsApp Call Agent Controlled Live Rollout

**Tujuan:** rollout bertahap dengan master toggle default-off, duration/turn caps, visible hangup, kill switch, metadata-only audit.

**Rings:** owned test account → consenting trusted contact → information-only business call → appointment inquiry → hotel/flight availability → reservation continuation without payment.

**Acceptance:** failure menghentikan progression; kill switch menutup web call, streams, Gemini phone state, pending permit.

**Fase berikutnya:** **26 — Cross-Integration Live Acceptance Ring**.

---

## Phase 26 — Cross-Integration Explicit Live Acceptance Ring

**Tujuan:** live proof terpisah untuk voice, Telegram, heavy provider, image, Google, WhatsApp. Setiap integration memerlukan explicit approval.

**Acceptance:** kegagalan satu integration tidak menghapus offline readiness lain; evidence live tidak dicampur dengan unit claims.

**Fase berikutnya:** **27 — Named Local Capability Facade**.

---

# TRACK 4 — BOUNDED CAPABILITY EXPANSION

## Phase 27 — Named Local Capability Request Facade

**Tujuan:** enum facade untuk capability proven saja: Content Studio title/reorder, Focus Mode, browser media, timer, approved call-session start/status/hangup.

**Permanent reject:** arbitrary tool/action, coordinate, selector, key, path, URL, screenshot, raw text dispatch, login/payment.

**Acceptance:** original per-capability policy/confirmation/verification tetap berlaku.

**Fase berikutnya:** **28 — Mediated Remote Proposal Facade**.

---

## Phase 28 — Mediated Remote Proposal Facade

**Tujuan:** paired remote actor hanya membuat proposal enum; tidak approve/execute dan tidak menerima UIA refs/transcript/audio/path.

**Acceptance:** actor/session/TTL/one-shot/fixed labels/local approval/metadata result.

**Fase berikutnya:** **29 — Next Exact Trusted UI Surface**.

---

## Phase 29 — Optional Next Trusted UI Surface

**Tujuan:** satu semantic action baru hanya setelah Takeda menentukan exact app/widget/use-case.

**Selection gate:** stable role/RuntimeId, bounded/reversible action, local confirmation, fresh recapture, no filesystem/login/payment/permission/terminal/remote ingress.

**Fase berikutnya:** ditentukan Takeda setelah audit Phase 29; tidak dipilih otomatis.

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

**Phase 20.3 — Git Worktree Segmentation & Recovery Commits.**
Scope: mulai dengan audit read-only branch/HEAD/status/staged/generated artifacts/frozen dan dependency graph; kemudian usulkan exact allowlist untuk satu recovery commit pada satu waktu.
Guardrail: jangan stage saat discovery; jangan gunakan `git add -A`, reset/checkout/restore/clean/stash/discard/amend; review cached diff + targeted tests + frozen + independent review; commit hanya setelah Takeda menyetujui exact staged scope. Jangan mengubah provider/credential/live integration/authority/frozen atau mulai Phase 21.
