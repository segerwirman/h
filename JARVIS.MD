# JARVIS — Durable Project Handoff

> **Repository:** `E:\jarvis agent\h`
> **Language:** Indonesian
> **Current implementation status:** Phase WA6 Post-Call Calendar Proposal COMPLETE (2026-08-03); Phase WA7 next — menunggu keputusan Takeda

## Start here in every new session

1. Read `session.md`.
2. Read `.hermes/plans/2026-08-01_224934-jarvis-master-implementation-roadmap.md`.
3. Read this file.
4. Read `.hermes/handoffs/current.md`.
5. Read `.hermes.md`.
6. Read the relevant domain roadmap named by `session.md`.
7. Inspect the relevant source and existing tests before proposing changes.

## Completed milestones

| Phase | Status | Summary |
|---|---:|---|
| 10–11 | ✅ | Bounded semantic desktop controls: click, scroll, set value, select option, toggle; local confirmation and recapture verification. |
| 14–14.5 | ✅ | Desktop visual observation, coarse/in-memory/read-only, privacy soak. |
| 15S | ✅ | Secure Telegram OAuth setup upload: encrypted staging, local desktop approval only. |
| 15A | ✅ | Telegram safe GWS read-only catalog and bounded remote renderer. |
| 16A | ✅ | Google installed OAuth client import bridge to existing local consent. |
| 16B | ✅ | Gmail privacy-tiered safe summaries. |
| 16C | ✅ | Calendar safe agenda plus complete locally approved event proposal. |
| 16D | ✅ | Opt-in local Calendar/Gmail TTS briefing. |
| 17A | ✅ | Public HTTPS source registry and one-shot bounded read-only fetch. |
| 17B | ✅ | Bounded SQLite metadata store, canonical URLs, hash dedupe, scan runner. |
| 17B.1 | ✅ | Scheduler isolated from generic `agent.cron` / `dispatch.run_sync`. |
| 17C | ✅ | Bounded on-request, desktop, and whitelist-gated Telegram monitor digest delivery. |
| 17D | ✅ | Opt-in local boot briefing composes Calendar, Gmail, and bounded monitor titles after readiness. |
| 18A | ✅ | Final voice can stage an opt-in Focus Mode proposal; desktop-local UI alone confirms/cancels and executes. |
| 18B | ✅ | Explicit voice briefing is parameterless/read-only and returns only the bounded safe briefing text. |
| 17E | ✅ | Validated monitor-source metadata and selected source persist, enabling restart-safe latest-summary briefing reads. |
| 17F | ✅ | Desktop-local Command Palette sheet adds/selects/clears validated monitor sources without fetch or remote authority. |
| 17G | ✅ | Desktop-local UI persists selected-source monitor job registrations with validated schedule/delivery mode. |
| 17H | ✅ | Separate supervised monitor worker loads registrations, ticks bounded scheduler, and routes existing delivery. |
| 17I | ✅ | Desktop-local metadata-only monitor status exposes safe worker/job state without raw content. |
| 17J | ✅ | Desktop-local monitor jobs can be enabled/disabled; only finite safe last status and timestamp persist. |
| 17K | ✅ | Restart-safe monitor lifecycle rehydrates only enabled registrations, preserves safe metadata, and joins launched worker threads on stop. |
| 17L | ✅ | Metadata-only low-N soak proves enabled, disabled, safe-failure, and restart worker fixtures repeatably pass. |
| 17M | ✅ | Hidden desktop-local monitor sheet presents finite job states in concise Indonesian without timestamps or raw failure detail. |
| Studio A | ✅ | Desktop-local Content Studio supports bounded local brief intake and project/scene planning without external execution. |
| Studio B | ✅ | Image generation is restricted to one explicitly selected scene via configured provider, returning local asset metadata only. |
| Studio C | ✅ | Studio action toggles only Studio via ContentStage; header focus control restores prior Focus Mode state on close; no generic desktop mutation. |
| Studio D | ✅ | Local timeline model plus bounded project-owned export (storyboard/prompt sheet/shot list/voiceover/captions/asset manifest/JSON/CSV); rejects unsafe formats, no render/publish/path leak. |
| UI U1 | ✅ | Legacy awareness icon retired from the default action panel; watcher stays default-off and can be re-added via config; Studio/Focus icons unaffected. |
| UI U2 | ✅ | Shared pure privacy denylist extracted from legacy watcher; static consumer assessment completed without pruning watcher. |
| Settings S1 | ✅ | Daily provider sheet defaults to simple setup; expert routing hidden, draft/test errors sanitized, and Save/Activate remain distinct. |
| Settings S2 | ✅ | Existing expert light/heavy routing is available only through an explicit local collapsed disclosure with no policy/config side effect. |
| 15B | ✅ | Paired Telegram can stage only allowlisted Focus Mode metadata; desktop-local sheet is sole approve/cancel/execute boundary with binding, TTL, and one-shot semantics. |
| 15C | ✅ | Paired Telegram stages fixed media commands only; desktop approval executes existing verified browser-media path and keeps result metadata-only. |
| Phase 19 | ✅ | Intent-specific bounded setter for Content Studio Judul Project only (local policy + UI + native UIA ValuePattern); rejects URL/password/OTP/payment/terminal/chat; desktop-local confirmation + recapture, no generic typing. |
| Phase 20 | ✅ | Semantic bounded reorder for Content Studio scene list only: policy admit_reorder + sheet move_scene + desktop drag semantic same-surface RuntimeId proof; schema 3 props only, confirmation mandatory, no filesystem/upload/coordinate/path/secret leak. |
| Phase 20.1 | ✅ | All 48 source tool modules and 99 runtime tools map to explicit groups; nine desktop-safe tools share exclusive `desktop` resource with generic computer control; optional safe Google/briefing modules are pre-mapped without enabling providers or broadening authority. |
| Phase 20.2 | ✅ | Durable continuity metadata is synchronized; stale next-phase markers are removed/superseded; source/config/wiring/test/fixture/live evidence is classified without treating source or unit tests as live proof. |
| Phase 20.3 | ✅ | Broadly dirty post-initial-commit worktree converted into 59 dependency-ordered, reviewable, reversible recovery commits (remediasi A46–A53, GWS A54–A57, telegram A58+TEL, monitoring A59–A70+MR, voice V1–V5, closure MR/MSG/TEL/UX1/UX2/REG/CAP1/CAP2/WIN/COV/SCR, docs DOC `29f94cd`); worktree bersih kecuali 2 artifact yang diklasifikasi; frozen `094b696` dijaga; select-option kini native (CAP1). |
| Phase 21 | ✅ | Production-path fixture acceptance: Phase 19 (title) + Phase 20 (reorder) terbukti `fixture-accepted` di fixture PyQt disposable via production UIA backend (ValuePattern + satu drag fisik + recapture + committed-value/visual-order proof). Acceptance run menemukan & meremediasi G1 (text_field identity), G2 (plain listitem card), G4 (verifikasi visual order — RuntimeId item tidak stabil pasca-reorder). Tetap BUKAN `live-proven`. |
| Phase 22 | ✅ | Content Studio scene list production UX: `QListWidget` scene cards visible dengan order number, selection via klik, Move Up/Down deterministik (first-up/last-down reject) reuse `move_scene()`, selected + asset mapping ikut reorder, timeline auto-refresh, accessibility identity stabil untuk lane UIA. |
| Phase 23 | ✅ | Content Studio export timing & preview hardening: bounded duration policy (1–600s/scene, total cap 3600s, bool/float/NaN ditolak), cumulative SRT standar, `shot_list_csv` membawa duration tervalidasi, `preview_export` in-memory (storyboard/captions/shot-list) tanpa file write; fixed export allowlist tetap authoritative. |
| Phase 24 | ✅ | Runtime lifecycle reliability sweep: static ownership table `LIFECYCLE_OWNERSHIP` (16 entri: owner/stop/join/failure state) + `audit_ownership()`; fix `CronScheduler.stop()` dan `SetupQueue.close()` dengan bounded join; `SUBPROCESS_LIMITATION` didokumentasikan (cooperative terminate, state `terminate_requested` jujur); kontrak dispatch lease release di finally dikunci test. |
| Phase 25 | ✅ | Credential-free canary: `probe_providers(no_voice=)` status boolean per provider (telegram/google/llm/voice/image/whatsapp ∈ ready/absent/disabled/skipped/unknown) tanpa menyimpan/mengekspos nilai secret; `_has_secret` nilai → bool → dibuang; mode `--no-voice` → voice `skipped`; probe tidak pernah menulis ke secrets store (dikunci test); `probe_summary()` metadata-only. |
| Phase WA0 | ✅ | WhatsApp readiness gate: `whatsapp_readiness.py` — dependency check (SDK via `find_spec`, jujur False di mesin ini), credential absence → `False` bukan crash, toggle config + allowlist policy placeholder, `client_available()`/`service_available()` boolean (official API shape), `readiness()`/`readiness_summary()` metadata-only; probe canary `whatsapp` kini status nyata (`ready`/`absent`/`disabled`); offline penuh, tanpa kredensial nyata/jaringan/live client. |
| Phase WA1 | ✅ | Native countdown timer: `countdown_timer.py` — bounded int 1–3600s, deadline monotonic anti-drift, transisi running → done/cancelled, bus signal `timer.finished`/`timer.cancelled` sekali (idempotent); `countdown_driver.py` — timer → `orb.set_progress` (orb.py frozen tidak disentuh), auto-stop saat done; wiring window `start_countdown`/`cancel_countdown` (QTimer 200ms, log lokal); murni lokal tanpa remote/network/write. |
| Phase WA2 | ✅ | Bounded call session state machine: `call_session.py` — idle → awaiting → active → done / cancelled / expired (TTL monotonic 30–3600s), remote proposal ENUM-only (`RemoteCallProposal`) tanpa eksekusi, `approve()` lokal one-shot, `end()`/`cancel()` idempotent, `result()` metadata-only (tanpa transcript/audio/path/raw), bus `call.*` ringan (session_id saja). |
| Phase WA3 | ✅ | Two-way audio proof: `call_audio.py` — `CallAudioProof` start hanya untuk session `active` (approved lokal), stop via session cancel/end, inbound+outbound via injected capture/playback (fixture-only; STT/TTS/voice_listener FROZEN tidak disentuh), duration bounded 1–600s, deadline monotonic, `result()` metadata-only + `audio_exercised` jujur, bus `call.audio.started/done` ringan. |
| Phase WA4 | ✅ | Bounded call dialogue: `call_dialogue.py` — turn alternation ketat local↔remote (double-turn ditolak), stop word → `interrupted`, secret/PII guard (marker + 12–19 digit → ditolak & tidak disimpan), `MAX_TURNS=20` → `completed`, terikat session active; `summary()` metadata-only tanpa transcript; bus `call.dialogue.turn/ended` ringan tanpa teks. |
| Phase WA5 | ✅ | Call memory & privacy: `call_memory.py` — `CallMemoryStore` in-memory (tanpa file write), field allowlist ketat `{session_id, status, duration_s, turn_count}` (transcript/audio/path ditolak), opt-in config `integrations.call.memory_enabled`, PII/secret guard (marker + 12–19 digit), retention bounded `MAX_ENTRIES=50` evict tertua + `clear()`; memory hanya metadata — dikunci test. |
| Phase WA6 | ✅ | Post-call calendar proposal: `calendar_proposal.py` — one-shot `draft → approved/rejected`, field allowlist ketat (title/start_ts/duration_min; kwarg asing ditolak), `has_conflict()` anti double-booking, `admit_start` masa depan, local approval one-shot; TANPA authority create otomatis (kontrak statis: tanpa import provider/network/write; write path `gcal_create_proposed` fase live). |

## Capability evidence classification

The canonical definitions and full snapshot live in the master roadmap. These labels are independent; an earlier label never implies a later one.

| Label | Meaning |
|---|---|
| `source-present` | Static implementation exists. |
| `configured` | Required configuration/credential/device readiness was checked without exposing secret values. |
| `runtime-wired` | A production registry/boot/consumer seam exists, possibly behind a gate. |
| `focused-tested` | Relevant automated tests passed; mock/fake/offscreen evidence stays in this class. |
| `fixture-accepted` | Production path ran on a bounded disposable/local fixture. |
| `live-proven` | An explicit approved run succeeded on the real external service/device/surface. |

Current audit truth: Phase 20.1 is `runtime-wired` + `focused-tested`; monitor 17L has explicit low-N `fixture-accepted` evidence. Foundational desktop-safe acceptance scripts are source-present, but the reviewed continuity docs do not contain enough execution evidence to label that lane `fixture-accepted`; Phase 19/20 remain only `focused-tested` pending the Phase 21 production-path fixture. Telegram, Google, image, voice, and WhatsApp current configuration/live state is **not established** by Phase 20.2. Their source, conditional wiring, or tests are not `live-proven`.

## Current monitoring architecture

```text
Validated MonitorSource (public HTTPS; api/rss/html)
→ fetch_source() bounded items
→ PersistentSourceRegistry (validated metadata + selected source ID)
→ desktop-local Command Palette source sheet (add/select/clear only)
→ MonitorStore (SQLite metadata only, capped + canonical dedupe)
→ scan_source()
→ MonitorScheduler.tick_detailed()
→ MonitorDeliveryCoordinator
→ render_digest() bounded
→ Telegram whitelist sink OR BUS.notify desktop sink
```

## Non-negotiable safety invariants

- `MonitorScheduler.create_monitor_job()` accepts only a validated `MonitorSource` and a cron schedule.
- Scheduler never imports/uses `jarvis.agent.cron`, `jarvis.agent.dispatch`, or `dispatch.run_sync`.
- No monitor authority for shell, browser automation, login, CAPTCHA bypass, typing, UIA, coordinates, desktop action, free-text agent task, or credentials.
- Store/digest never contains raw HTML, cookies, headers, token/secret/path/body, attachment, OCR, screenshot, or browser state.
- Telegram receives only a `render_digest()` string through whitelist-gated `send_from_anywhere()`.
- Desktop delivery only publishes `BUS.notify`; it does not drive UI controls.
- 17D boot briefing starts only after `BootSequence` readiness and runs on a daemon worker; it uses the existing bounded briefing tool and local drawer/TTS sinks only.
- Boot monitor content is default OFF and never invokes `fetch_source`, `MonitorScheduler`, or Telegram delivery.
- 18A voice ingress can only stage allowlisted proposal metadata from final STT when its config flag is enabled; it cannot execute or approve.
- Desktop-local UI is the only confirmation/execution boundary for the current Focus Mode proposal; no remote, UIA, coordinate, or generic desktop route exists.
- 18B voice readout has a parameterless native schema and returns only the bounded `briefing` field; it does not route raw source data or tool dumps into speech.
- 17E persists only validated public source metadata and selected source ID; persisted rows are revalidated and briefings read bounded `latest()` without fetch/scheduler authority.
- 17J persists only local job `enabled` state plus allowlisted `last_status` (`not_started`, `ok`, `source_failed`) and numeric timestamp; it never persists raw scan result, response body, exception, task, or arbitrary status text.
- Disable excludes a job from worker installation; enable/disable never starts workers or fetches a source.
- 17K runtime reconstruction rehydrates only enabled persisted registrations exactly once per worker; safe status metadata survives SQLite reopen, and `stop()` joins a launched monitor worker before reconstruction.
- 17L runs a fixed local fixture allowlist (`enabled`, `disabled`, `safe_failure`, `restart`) at low N and emits only `{fixture,status,iterations}` metadata. It fails closed and marks later fixtures `not_run`; it never exposes child output or exception content.
- 17M maps finite persisted job state to concise Indonesian labels: `Aktif`/`Dinonaktifkan` and `Belum pernah berjalan`/`Pemeriksaan terakhir aman`/`Gagal mengambil sumber`; no timestamp or raw failure content is rendered.
- Studio A accepts bounded local `.txt`, `.md`, `.docx`, and `.pdf` creative briefs, returning text without source paths; its project/scene model and hidden stage panel are desktop-local and do not upload, generate, render, publish, browse, login, or invoke remote authority.
- Studio B accepts only one explicit valid scene index, invokes the existing configured image lane with `n=1`, and returns `{scene_index,provider,model,state}` only; asset path stays internal and no bulk/publish/remote/OAuth-token path exists.
- Studio C toggles only the registered Studio panel via `ContentStage`; same icon closes it. Header `FOCUS ON/OFF` emits only a boolean request; controller restores prior Focus Mode state that existed before Studio opened. No generic desktop mutation, terminal overlay, or frozen-file change is introduced.
- Studio D builds a local scene timeline (order, title, narration, visual_prompt, duration, asset_state) and exports only project-owned strings via a fixed format allowlist (`storyboard_md`, `prompt_sheet`, `shot_list_csv`, `voiceover_md`, `captions_srt`, `asset_manifest_json`, `project_json`, `project_csv`). Unknown/unsafe formats fail closed; it never renders/edits video, writes files, publishes, uploads, or leaks paths/secrets.
- UI U1 removes `awareness` from the default `action_panel.icons` list only; the `screen_awareness` watcher stays default-off and is not deleted, the `awareness_clicked` signal and `_toggle_awareness` handler remain, and re-adding `awareness` to config restores the icon. Studio and Focus icons are unaffected.
- UI U2 adds pure `privacy_denylist.is_denylisted()` shared by legacy watcher, UIA capture, and in-memory visual observe; compatibility wrapper preserves watcher behavior. Static audit classifies watcher start as local lazy, supervisor stop as optional lifecycle cleanup, proactive subscription as currently unproven/optional, and UIA/visual observe as lazy shared-helper consumers. No prune/deletion occurs.
- Settings S1 hides expert light/heavy routing controls by default while retaining the existing simple provider path (Select → Connect/Key → Test → Choose Model → Activate). Discovery and agent-probe failures use fixed safe UI messages, never raw error/draft-secret text; Test uses the existing in-memory draft and Save/Activate remain distinct.
- Settings S2 adds one local `TAMPILKAN/SEMBUNYIKAN ROUTING LANJUTAN` disclosure. It starts collapsed, only toggles existing expert widget visibility, and performs no provider routing/config write or policy change.
- 15B remote ingress accepts exact Focus Mode phrases from a paired Telegram actor only, then stages actor/session-bound metadata in a TTL one-shot queue. Telegram receives only the safe pending-local-approval notice; `RemoteProposalSheet` on desktop alone approve/cancels through a narrow Focus Mode executor. No generic action, raw argument, UIA/coordinate/screenshot/secret, or remote approval route exists.
- 15C extends that queue with fixed `media_play/pause/mute/unmute/volume_up/volume_down` actions only. Desktop approval maps them to existing `BrowserMedia.run()` and accepts success only through its post-action verification; remote-facing result is `{state, muted, volume_percent}` only, never page URL/title/DOM/content. Navigation, set-volume, toggle, skip-ad, coordinates, and remote desktop actions reject.
- Phase 19 implements exactly one trusted local intent `content_studio_title` (Judul Project). It uses `content_title_policy.admit_title()` bounded 1-120, rejects URL, password/passcode/PIN/OTP, payment/credit-card, sign-in/login, bank/transfer, terminal/shell, send-email/compose/chat. Desktop tool `desktop_safe_set_content_title` accepts only `{observation_id, element_id, project_title}`, requires registry confirmation, checks session ownership, requires RuntimeId identity and same-surface recapture, never exposes raw title/path/secret, never accepts coordinates/key/drag/generic text dispatch. UI sheet `set_project_title()` routes only through policy and preserves other fields. No submit/navigation/publish/network/path-leak.
- Phase 20 implements exactly one trusted local intent `content_studio_scene_reorder` (Content Studio scene list). Policy `content_scene_reorder.admit_reorder(from,to,size)` bounded int only (bool rejected), same-surface, same parent RuntimeId, no coordinate/path/generic drag/upload. Sheet `move_scene(from,to)` uses only policy, returns safe metadata, preserves other project fields, updates selected mapping. Desktop tool `desktop_safe_reorder_scene` schema only `{observation_id, source_element_id, destination_element_id}`, requires registry confirmation, session ownership, distinct RuntimeId, same-surface + same-parent verification, one native drag center-to-center only, recapture verifies both RuntimeId, no filesystem/upload/path/secret leak. `desktop_observe` advertises card role with intent fixed, no label leak.
- Phase 20.1 changes catalog/resource metadata only. Production registry has no fallback `other`, duplicate group/module membership, or unmapped module; diagnostic fallback remains for unknown future modules. All semantic desktop observation/mutation modules use exclusive resource `desktop`; Content Studio model-only prompt remains resource-free. Provider availability/config, schemas, remote toolsets, confirmation, and executor authority are unchanged.
- Local desktop approval remains the authority for all mutation.

## Validation standard

```bash
unset PYTHONPATH; python -m pytest -q <focused-tests>
python -m py_compile <changed-python-files>
git diff --check
python scripts/verify_frozen.py
```

## Next recommended phase
**Phase WA7 — Reservation Commitment Gate** — MENUNGGU KEPUTUSAN TAKEDA (DILARANG dimulai tanpa approval eksplisit).

Gate komitmen reservasi: reservasi = komitmen → wajib gate ekstra (local approval + fixed disclosure labels + cancellation window), tanpa auto-commit; setiap gate failure → no-op + alasan fixed. Sampai disetujui: verifikasi posisi read-only, presentasikan status + opsi, minta approval sebelum eksekusi apa pun. Jangan ubah provider/credential/live integration/authority/frozen.

For detailed current test evidence, changed files, and exact next implementation contract, read `.hermes/handoffs/current.md`.
