# Arsip Planning Jarvis

Folder ini menyimpan roadmap, assessment, dan rencana sanitasi yang tidak lagi
menjadi instruksi aktif. Urutan file mengikuti timestamp pada basename. Sumber
kebenaran implementasi aktif tetap `jarvisfix.md`; arsip ini tidak boleh
mengalahkan kode, test, atau evidence terbaru.

## Kategori status

- `complete-evidenced`: file memuat bukti penyelesaian eksplisit.
- `superseded/absorbed`: scope dipindahkan ke roadmap/implementasi lebih baru;
  status ini tidak menyatakan semua checklist lama selesai satu per satu.
- `assessment-record`: hasil assessment, bukan rencana implementasi aktif.
- `deferred-items-remain`: sebagian scope selesai, tetapi file menyebut item
  yang sengaja ditunda atau masih memerlukan keputusan.

SHA-256 dipendekkan menjadi 12 karakter dan dihitung setelah path internal
arsip diperbaiki. `Refs` adalah jumlah sebutan basename/path pada file tracked selain `INDEX.md`
saat indeks dibuat; nilai ini inventory, bukan bukti runtime.

| Tanggal | Scope | Status | Original path | Archived path | Evidence / commit | SHA-256 | Refs |
|---|---|---|---|---|---|---:|---:|
| 2026-07-21 | Natural conversation maturity | `superseded/absorbed` | `.hermes/plans/2026-07-21_085845-jarvis-maturity-natural-conversation.md` | `docs/archive/plans/2026-07-21_085845-jarvis-maturity-natural-conversation.md` | Tidak ada commit/pass count di file; scope diserap roadmap berikutnya | `d0a6adeedbbc` | 2 |
| 2026-07-22 | Framework maturity | `superseded/absorbed` | `.hermes/plans/2026-07-22_100647-jarvis-framework-maturity.md` | `docs/archive/plans/2026-07-22_100647-jarvis-framework-maturity.md` | Completion definition saja; diserap master roadmap | `716c56af9163` | 0 |
| 2026-07-22 | Telegram manager lifecycle | `superseded/absorbed` | `.hermes/plans/2026-07-22_165918-telegram-manager-lifecycle.md` | `docs/archive/plans/2026-07-22_165918-telegram-manager-lifecycle.md` | Rencana 6 task; tanpa bukti terminal di file | `cd9aae439cb1` | 0 |
| 2026-07-22 | Phase 14 local-first dashboard/Telegram rollout | `superseded/absorbed` | `.hermes/plans/2026-07-22_182154-phase14-local-first-dashboard-telegram-rollout.md` | `docs/archive/plans/2026-07-22_182154-phase14-local-first-dashboard-telegram-rollout.md` | Kriteria completion belum ditandai di file | `d43afc808174` | 2 |
| 2026-07-22 | Phase 15A critical hardening | `superseded/absorbed` | `.hermes/plans/2026-07-22_222009-phase15a-critical-hardening.md` | `docs/archive/plans/2026-07-22_222009-phase15a-critical-hardening.md` | Rencana RED→GREEN; tanpa hasil terminal di file | `a46c9c924351` | 2 |
| 2026-07-22 | Phase 15B runtime authority | `superseded/absorbed` | `.hermes/plans/2026-07-22_222500-phase15b-runtime-authority.md` | `docs/archive/plans/2026-07-22_222500-phase15b-runtime-authority.md` | Scope RuntimeSupervisor diserap; hasil lanjut `LIF 1011794` | `9fd9658992b7` | 2 |
| 2026-07-22 | Phase 15B.2 cooperative voice stop | `superseded/absorbed` | `.hermes/plans/2026-07-22_225616-phase15b2-voice-cooperative-stop.md` | `docs/archive/plans/2026-07-22_225616-phase15b2-voice-cooperative-stop.md` | Minimal TDD plan; tanpa hasil terminal di file | `e69168754d52` | 2 |
| 2026-07-22 | Phase 16 reliability evaluation | `superseded/absorbed` | `.hermes/plans/2026-07-22_230000-phase16-reliability-evaluation.md` | `docs/archive/plans/2026-07-22_230000-phase16-reliability-evaluation.md` | Target evaluation/runbook kemudian tersedia; file sendiri tanpa hasil | `7f2589f7e114` | 2 |
| 2026-07-22 | Phase 17 Telegram production ring | `superseded/absorbed` | `.hermes/plans/2026-07-22_231000-phase17-telegram-production-ring.md` | `docs/archive/plans/2026-07-22_231000-phase17-telegram-production-ring.md` | Target acceptance doc kemudian tersedia; file sendiri tanpa hasil | `414777786894` | 2 |
| 2026-07-23 | Phase 18 ecosystem extension safety | `superseded/absorbed` | `.hermes/plans/2026-07-23_000000-phase18-ecosystem-extension-safety.md` | `docs/archive/plans/2026-07-23_000000-phase18-ecosystem-extension-safety.md` | Rencana plugin validation; tanpa hasil terminal di file | `5f5e429060fb` | 4 |
| 2026-07-27 | Repository sanitation | `deferred-items-remain` | `docs/DELETION_PLAN.md` | `docs/archive/plans/2026-07-27-repository-sanitation.md` | `928b59e`, `d7084a1`, `96fc4ac`, `d96ca9c`, `98be3e7`, `1db42d2`; beberapa item eksplisit ditunda | `5d9953c1369f` | 3 |
| 2026-07-30 | Desktop-safe set value | `deferred-items-remain` | `.hermes/plans/2026-07-30_123955-desktop-safe-set-value.md` | `docs/archive/plans/2026-07-30_123955-desktop-safe-set-value.md` | File menyatakan tidak ada commit dan scope tambahan ditunda | `c26e487a5c6f` | 0 |
| 2026-07-30 | Expanded desktop authority | `deferred-items-remain` | `.hermes/plans/2026-07-30_143115-expanded-desktop-authority-roadmap.md` | `docs/archive/plans/2026-07-30_143115-expanded-desktop-authority-roadmap.md` | Exit criteria/review/kill switch tidak dibuktikan di file | `b5bcc8b29b00` | 0 |
| 2026-07-30 | Post-Phase-8 readiness/canary | `superseded/absorbed` | `.hermes/plans/2026-07-30_170000-post-phase8-readiness-and-canary.md` | `docs/archive/plans/2026-07-30_170000-post-phase8-readiness-and-canary.md` | Canary kemudian diserap Phase 21 fixture acceptance | `94d44b5d8aca` | 0 |
| 2026-07-31 | Jarvis domain roadmap | `superseded/absorbed` | `.hermes/plans/2026-07-31_032152-jarvis-roadmap.md` | `docs/archive/plans/2026-07-31_032152-jarvis-roadmap.md` | Self-declared superseded; menyimpan pass counts dan baseline `094b696` | `b4dc15068171` | 4 |
| 2026-07-31 | Jarvis next phases | `superseded/absorbed` | `.hermes/plans/2026-07-31_123827-jarvis-next-phases.md` | `docs/archive/plans/2026-07-31_123827-jarvis-next-phases.md` | Self-declared superseded; detail domain dipertahankan | `c4558e79d9a6` | 4 |
| 2026-08-01 | Post-Phase-20 stabilization | `deferred-items-remain` | `.hermes/plans/2026-08-01_222148-jarvis-post-phase20-stabilization-and-next-implementation.md` | `docs/archive/plans/2026-08-01_222148-jarvis-post-phase20-stabilization-and-next-implementation.md` | 20.1–25 evidenced; 26–29 eksplisit ditunda pada record ini | `87c45a4de006` | 2 |
| 2026-08-01 | WhatsApp call-agent roadmap | `deferred-items-remain` | `.hermes/plans/2026-08-01_224041-jarvis-whatsapp-call-agent-calendar-timer-roadmap.md` | `docs/archive/plans/2026-08-01_224041-jarvis-whatsapp-call-agent-calendar-timer-roadmap.md` | Foundation `37 passed`; WA phases belum diberi commit di file | `e2956e3e188b` | 2 |
| 2026-08-01 | Master implementation roadmap | `complete-evidenced` | `.hermes/plans/2026-08-01_224934-jarvis-master-implementation-roadmap.md` | `docs/archive/plans/2026-08-01_224934-jarvis-master-implementation-roadmap.md` | 20.1–29/WA0–WA9 memiliki commit; live lane tambahan tetap approval-gated | `57e54ab99c10` | 4 |
| 2026-08-03 | Phase 21 fixture acceptance | `complete-evidenced` | `.hermes/plans/2026-08-03_jarvis-phase21-fixture-acceptance.md` | `docs/archive/plans/2026-08-03_jarvis-phase21-fixture-acceptance.md` | `0d30794`, `a109f69`, `aaec855`; `fixture-accepted`, bukan `live-proven` | `2f0e6a7e18d0` | 0 |
| 2026-08-07 | UI U2 screen-awareness assessment | `assessment-record` | `.hermes/plans/2026-08-07-ui-u2-screen-awareness-assessment.md` | `docs/archive/plans/2026-08-07-ui-u2-screen-awareness-assessment.md` | Static audit; 40 + 6 focused passed; tidak mengusulkan deletion | `5f73483e43be` | 3 |

## Batas

Dokumen aktif yang sengaja tidak dipindahkan: `docs/UI_LEGACY_RETIREMENT_PLAN.md`
(masih terbuka), `docs/PHASE12_VERIFICATION.md` (evidence), `jarvisfix.md`,
`session.md`, runtime prompt/skills, runbook operator, dan user content.
