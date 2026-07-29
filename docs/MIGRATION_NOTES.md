# MIGRATION_NOTES — Jarvis MK50 Standalone

> Sumber kebenaran aktif: `JARVIS_MK50_MASTER_SPEC.md`. Catatan lama di
> bagian “Arsip pra-master-spec” dipertahankan hanya sebagai konteks sejarah
> dan tidak boleh mengalahkan master spec atau kode nyata.

## TITIK LANJUT

- **Selesai & ter-commit:** Fase 0 (discovery), Fase 1 (Router + de-Hermes),
  Fase 2 (bug YouTube + interaktivitas), Fase 3 (model routing per lane §3),
  Fase 4 (web lokal Indonesia §6), Fase 5 (ContentStage vision/info/home +
  buang Tabbit + panel Home Assistant + lazy vision §7/§8, termasuk koreksi
  kontrak ketat ContentStage), Fase 6 (secret store berlapis, OAuth OpenAI +
  Anthropic, migrasi credential, dan telemetri teragregasi/berotasi §9),
  Fase 7 (satu OAuth Google + Calendar/YouTube Data/Gmail/Drive dengan gate
  API/scope/write nyata §10), Fase 8 (Telegram Control native + Settings
  Messaging §11), dan Fase 9 (CI hash FROZEN, rencana pensiun UI legacy,
  dokumentasi final, serta regresi §12–§14).
- **Berikutnya:** tidak ada fase implementasi tersisa pada urutan §13. MK50
  selesai sampai Fase 9; tunggu arahan user untuk pekerjaan baru. Validasi live
  dengan akun/perangkat user tetap dicatat sebagai batas penerimaan, bukan fase
  implementasi tambahan.

### Program pematangan pasca-MK50 (2026-07-21)

- User secara eksplisit meminta pengembangan bertahap untuk: OpenAI OAuth dan
  multi-provider, percakapan natural, toolsets, Skills Hub/lifecycle, surface
  management, plugin ecosystem, serta gateway multi-platform.
- Ini adalah ekstensi setelah MK50, **bukan** penulisan ulang MK50. Zona
  FROZEN pada master spec tetap berlaku; perubahan runtime harus hanya melalui
  seam perilaku yang diperlukan.
- Roadmap detail disimpan di
  `.hermes/plans/2026-07-21_085845-jarvis-maturity-natural-conversation.md`.
  Acceptance contract ada di `docs/JARVIS_CONVERSATION_ACCEPTANCE.md`.
- Fase 0 program ini hanya dokumentasi dan baseline; regression awal OAuth,
  provider, model routing, interaktivitas, ingress, dan voice routing lulus:
  **66 passed in 6.61s**.
- Fase 1 (hardening OpenAI OAuth) selesai: status aman tanpa token/account-id,
  klasifikasi error, refresh dan retry request asli tepat satu kali pada HTTP
  401, cache LLM reset pada login/logout/reauth, capability
  `chat`/`tools`/`streaming`, serta status reconnect aman di Settings. Regression
  terkait setelah perubahan: **72 passed in 6.96s**.
- Fase 2 (multi-provider policy) selesai: role `voice_transport`, `light`,
  `heavy`, `conversation`, dan `auxiliary` kini eksplisit; `conversation=auto`
  mengikuti light, heavy tidak pernah turun diam-diam ke light, capability tak
  dikenal diperlakukan unavailable, dan Settings menampilkan ringkasan role
  aman. Regression terkait: **83 passed in 6.21s**.
- Fase 3 (deterministic ConversationDelivery) selesai: result terverifikasi
  dipisah menjadi `display_text`, `speech_text`, dan factual anchors; voice
  menerima brief maksimum dua kalimat/260 karakter, desktop UI dan Telegram
  mempertahankan report detail, dan root Gemini Live tidak lagi diberi instruksi
  literal `PERSIS`. Regression terkait: **120 passed in 8.33s**.
- Fase berikutnya yang boleh dikerjakan adalah naturalizer LLM opsional yang
  fact-grounded dan timeout-bounded; fallback deterministik Fase 3 wajib tetap
  menjadi default. Tidak ada fase lain yang digabung sebelum fase tersebut
  tervalidasi dan dilaporkan.
- **ContentStage sekarang tepat `vision` / `info` / `home`.** Panel lama
  `content`, `capabilities`, `messaging`, `settings`, dan summary browser tidak
  lagi didaftarkan. Tombol Messaging kini membuka Settings Telegram yang nyata;
  Capabilities tetap memberi status jujur dan Settings provider tetap membuka
  sheet yang nyata.
- **Utang di luar kode (aksi user):** rotasi `RELAY_WEBHOOK_SECRET` yang
  pernah tracked (16 commit lama) dan pencabutan key Gemini lama di history
  (lihat catatan Fase 0). `JARVIS_MK50_MASTER_SPEC.md` masih untracked —
  keputusan commit ada di user.
- **Kondisi runtime yang perlu disadari:** lane berat kini TIDAK memakai
  kunci Gemini (§0 kep. 3). Di mesin dev ini rantai heavy resolve ke
  provider `local` (LM Studio, dari providers.json); isi
  `routing.heavy.provider` di `config.yaml` bila ingin provider berat
  eksplisit. Tanpa kandidat siap, tugas T2+ degrade jujur mengarah ke
  Settings.

## Baseline Inventory (Fase 0 — 2026-07-20)

### Baseline dan batas kerja

- `JARVIS_MK50_MASTER_SPEC.md` dibaca seluruhnya (758 baris) sebelum
  perubahan apa pun.
- Entry aktif adalah `python -m jarvis.main`; entry ini membuat
  `jarvis.ui.window.JarvisUI` lalu membungkus `main.JarvisLive` yang lama
  untuk Gemini Live/voice (`jarvis/main.py:24-40,43-67,148-151`).
- `python main.py` dan UI root `ui.py` masih ada sebagai jalur legacy
  kedua.
- `hermes-agent-main/` ada sebagai referensi yang di-`gitignore`, tetap
  READ-ONLY, dan tidak dibuka untuk ditulis, dijalankan, atau dimasukkan ke
  runtime pada fase ini.
- Repo adalah Git repository pada branch `main`. Klaim lama bahwa repo bukan
  Git repository sudah tidak berlaku.
- Fase 0 hanya mengubah dokumentasi/higiene secret; tidak ada kode fungsional
  atau file FROZEN yang diubah.

### Struktur repo nyata (3–4 level, diringkas)

```text
repo/
├─ main.py, ui.py                  # Gemini Live/voice + UI legacy (FROZEN by scope)
├─ actions/                        # action callable legacy untuk Gemini Live
├─ core/
│  ├─ stt.py, tts.py
│  └─ voice_listener.py            # pipeline suara legacy (FROZEN)
├─ config/                         # aset + secret runtime yang di-ignore
├─ dashboard/                      # remote web/phone ingress
├─ docs/
├─ hermes-agent-main/              # referensi READ-ONLY; bukan runtime
├─ jarvis/
│  ├─ main.py                      # entry aplikasi aktif
│  ├─ agent/
│  │  ├─ adapters/                 # base, UI, Telegram
│  │  ├─ tools/                    # browser, web, HA, vision, file, terminal, dst.
│  │  ├─ dispatch.py, loop.py
│  │  ├─ providers.py, llm_client.py
│  │  └─ registry.py, skills.py, memory_store.py
│  ├─ browser/                     # embedded Chromium + Tabbit paths
│  ├─ core/
│  │  ├─ router.py                 # router intent lama
│  │  ├─ secrets_store.py
│  │  └─ config.py, wake.py, bus.py
│  ├─ integrations/
│  │  ├─ hermes/                   # jalur lama masih aktif di kode
│  │  ├─ relay/
│  │  └─ comments/
│  ├─ nlp/
│  ├─ ui/                          # window, stage, panels, actionpanel, orb, theme
│  └─ vision/
├─ memory/
├─ scripts/
└─ tests/
```

### Ingress dan seam intent → aksi yang benar-benar ada

| Sumber | Alur aktual | Boundary aksi | Temuan |
|---|---|---|---|
| Teks desktop | `CommandBar.submitted` → `MainWindow.handle_command` → `IntentRouter.classify` | `jarvis/ui/window.py::_dispatch_command` (`:665-681`) | Seam paling jelas untuk jalur typed. |
| Voice aktif | `jarvis/main.py` → `main.JarvisLive` → Gemini Live memilih tool | `main.py::_execute_tool` (`:729-920`), dipanggil dari `:1091-1103` | Boundary menerima nama/argumen tool, bukan utterance lengkap. |
| Transcript voice ke UI | `main.py:997-1025` → log `You:` → `MainWindow._append_log` | `_voice_intercept` (`window.py:1543-1566`) | Intercept hanya subset UI/browser dan bersifat post-hoc; bukan seam pre-action yang aman untuk tier routing. |
| Telegram | `_on_text` / `_on_voice` → `_handle_task` | `jarvis.agent.dispatch.dispatch_async` (`telegram.py:344-370`) | Semua teks bebas langsung menjadi agent berat; belum melalui router tier. |
| Dashboard | queue command → `JarvisLive._process_dashboard_commands` | Gemini Live langsung (`main.py:1346-1366`) | Bypass `IntentRouter`. Phone mic juga masuk sebagai audio mentah. |

**Kesimpulan seam:** kode nyata belum mempunyai satu seam universal untuk
voice, teks, dan Telegram. `MainWindow._dispatch_command` adalah seam typed,
`JarvisLive._execute_tool` adalah boundary perilaku voice, dan
`TelegramService._handle_task` adalah boundary Telegram. Fase 1 harus
menambahkan satu façade routing tipis sebagai otoritas bersama dan memanggilnya
dari boundary tersebut. Mekanisme mic/STT/TTS/wake, konfigurasi suara, dan
playback tetap FROZEN. `_voice_intercept` tidak boleh dianggap solusi
universal karena terlambat terhadap eksekusi tool Gemini Live.

### Router dan fondasi agent yang sudah ada

- `jarvis/core/router.py::IntentRouter` sudah melakukan klasifikasi
  SEARCH/APP/URL/SYSTEM/CHAT/HERMES, tetapi kontraknya bukan `Tier`/`Route`
  pada §2 master spec. Rules Hermes masih ada di `:79-105,180-201,260-265`.
  Router ini harus dibungkus/direuse seperlunya, bukan ditimpa secara buta.
- `jarvis/agent/dispatch.py:68-142` sudah menjadi entry async ke
  `jarvis/agent/loop.py`; registry, loop, skills, dan memory sudah ada dan
  tidak akan ditulis ulang.
- Jalur Hermes runtime masih nyata: tool schema `hermes_agent` di
  `main.py:540-565`, eksekusi di `main.py:881-883`, fallback UI di
  `window.py:848-954`, dan `config.yaml:381-382` masih
  `hermes.enabled: true`. Ini inventaris untuk Fase 1, bukan diubah di Fase 0.

### Provider config nyata

| Kebutuhan | Lokasi aktual | Status baseline |
|---|---|---|
| Loader config | `jarvis/core/config.py` → root `config.yaml`; juga memuat root `.env` | Aktif. |
| Gemini Live/voice | `main.py:88-99,1394-1403` → `config/api_keys.json` | Model dan path legacy terpisah dari registry agent. |
| Text/classifier ringan lama | `config.yaml:357-363` + `jarvis/core/llm.py` | Gemini text/classify. |
| Provider agent | `jarvis/agent/providers.py` + `config/providers.json` | Registry multi-provider sudah ada; provider aktif saat discovery: `gemini`. |
| Routing lane master spec | section `routing.light/heavy` | Belum ada. |
| Provider metadata master spec | section top-level `providers` | Belum ada. |
| Locale master spec | section top-level `locale` | Belum ada. |

`config/providers.json`, `config/api_keys.json`, dan
`config/youtube_oauth.json` ada secara lokal, di-ignore, dan tidak tracked.
Ketiganya masih memuat credential plaintext non-kosong (API key serta material
OAuth termasuk refresh token/client secret); `providers.save_provider()` juga
menulis `api_key` ke JSON (`providers.py:230-254`) dan Settings menyalin key
Gemini ke `api_keys.json` (`settings_providers.py:185-200`). Ini bertentangan
dengan master spec dan harus dimigrasikan ke `secrets_store` pada Fase 6.
Nilai credential tidak disalin ke catatan migrasi ini.

### Secret store dan higiene Git

- Implementasi aktual berada di `jarvis/core/secrets_store.py`.
- API tersedia: `get`, `set`, `delete`, `available`.
- Backend aktual hanya environment-read + keyring OS. Jika keyring tidak ada
  atau gagal, `set` mengembalikan `False`; DPAPI dan Fernet fallback §9
  belum ada. `requirements.txt` sudah memuat `cryptography`, tetapi belum
  memuat `keyring`/`pywin32`. Ini gap Fase 6.
- Sebelum perbaikan Fase 0, `.env`, `config/api_keys.json`,
  `config/providers.json`, dan OAuth runtime sudah di-ignore, tetapi pola
  `.jarvis/.keyfile` dan `.jarvis/secrets.dat` belum ada.
- Fase 0 menambah ignore untuk varian `.env.*` (dengan
  `!.env.example`) dan fallback store `.jarvis/.keyfile` /
  `.jarvis/secrets.dat`, termasuk mirror pada subdirectory. Path
  `~/.jarvis/*` normal berada di luar worktree; pola repo melindungi portable
  copy/mirror yang mungkin masuk worktree.
- Audit menemukan `.env.example:10` yang tracked pernah berisi
  `RELAY_WEBHOOK_SECRET` nyata dan sama dengan runtime `.env`. Nilainya
  sudah dikosongkan pada Fase 0. Secret tersebut masih ada dalam 16 commit,
  dari `8c4e8c4` sampai baseline `cc85ccb`; user wajib merotasinya.
  History tidak ditulis ulang karena itu operasi destruktif di luar Fase 0.
- `config/providers.json` juga pernah tracked pada dua commit (`8c4e8c4`,
  `1b9d5bf`) sebelum dilepas dari index oleh `825b324`; history memuat kandidat
  key Gemini lama. Key aktif sekarang berbeda, tetapi status revoke key lama
  tidak dapat diverifikasi. User perlu memastikan key historis itu dicabut.
- Pemindaian signature secret tracked tidak menemukan pola Google/OpenAI/
  Slack/Telegram token lain; nilai credential runtime lain tidak disalin ke
  catatan migrasi ini.

### Registrasi ContentStage aktual

`ContentStage` didefinisikan di `jarvis/ui/stage.py:30`; registry-nya
`ContentStage.register` ada di `:63-66`. Registrasi aktual:

| Key | Widget/lokasi |
|---|---|
| `browser` | `EmbeddedBrowser`, `window.py:320-322` |
| `vision` | `VisionPanel`, `window.py:323-324` |
| `content` | `QTextBrowser` generik, `window.py:338-343` |
| `capabilities` | `CapabilitiesPanel`, `window.py:411-414` |
| `messaging` | `MessagingPanel`, `window.py:411-416` |
| `settings` | `SettingsPanel`, `window.py:411-418` |
| `browser_agent` | browser/Tabbit lazy, `window.py:1345-1379` |

Tidak ada `InfoPanel`, `HomePanel`, registrasi `"info"`, atau registrasi
`"home"`. `stage.py` masih mempunyai special-case browser
(`:99-100`) dan `SummaryCard` browser-specific (`:207+`). Messaging
masih berada di ContentStage dan default-nya masih mengarah ke service Hermes
(`jarvis/ui/panels.py:766-780`). Target hanya `vision/info/home` adalah
pekerjaan Fase 5/8; tidak disentuh sekarang.

### Batas FROZEN yang direkam

- **FROZEN voice:** root `main.py` pada mekanisme mic, audio transport,
  transcript, TTS/playback, voice Charon; `core/stt.py`, `core/tts.py`,
  `core/voice_listener.py`; `jarvis/core/wake.py`.
- **FROZEN visual:** `jarvis/ui/theme.py`, `jarvis/ui/orb.py`, aset/animasi
  orb, root `ui.py`, dan layout dasar.
- **SEMI-FROZEN:** `jarvis/ui/window.py` hanya untuk seam/wiring minimal;
  `jarvis/ui/actionpanel.py` hanya perubahan fase yang diizinkan.
- **Boleh pada fase terkait:** `jarvis/ui/stage.py` dan panel baru, tanpa
  mengubah identitas visual.

### Checklist Fase 0

- [x] Master spec dibaca seluruhnya.
- [x] Struktur repo nyata dipetakan 3–4 level.
- [x] Seam intent → aksi dan ketidakadaan seam universal diidentifikasi.
- [x] Lokasi voice dispatch diidentifikasi tanpa mengubah pipeline suara.
- [x] Provider config dan `secrets_store.py` diinventaris.
- [x] Registrasi ContentStage aktual diinventaris.
- [x] `.gitignore` menutup `.env`, `config/api_keys.json`,
  `.jarvis/.keyfile`, dan `.jarvis/secrets.dat`.
- [x] Secret tracked di `.env.example` disanitasi; kebutuhan rotasi/history
  dicatat tanpa menampilkan nilainya.
- [x] Tidak ada kode fungsional atau file FROZEN yang diubah.

---

## Fase 1 — Router + de-Hermes (2026-07-20)

### Router tier bersama

- Ditambahkan `jarvis/agent/router.py` dengan kontrak `Tier`, `Route`, dan
  `classify(text, context)` sesuai §2. Router tier ini berdiri di depan
  `jarvis/core/router.py`; router intent lama tetap menangani jenis aksi untuk
  lane ringan dan tidak ditulis ulang.
- Rules deterministik mencakup T0 reflex, T1 satu aksi/percakapan/pembacaan
  data, sinyal T2 multi-langkah/penilaian/agentik/file-kode-terminal-browser,
  serta context eksplisit T3 delegate dan T4 scheduler.
- Contoh kunci `buka dan putar youtube deddy corbuzier terbaru` dipastikan T2.
  Permintaan read-only seperti berita terbaru, kalender, email, dan video
  langganan terbaru tetap T1 sesuai pengecualian §2/§10.
- Input ambigu memakai Gemini melalui provider nyata
  `jarvis.agent.providers.get_provider("gemini")`; output JSON diparse
  defensif. Exception, output malformed, provider kosong, classifier sibuk,
  atau budget terlampaui selalu menjadi T2.
- Fallback jaringan dibatasi oleh `router.classify_budget_ms` (100 ms pada
  config sekarang) dan hanya satu worker daemon boleh aktif. Ini mencegah
  classifier opsional membekukan UI/event loop; keputusan yang terlambat tidak
  pernah menurunkan request menjadi ringan.

### Seam intent → aksi yang dipasang

| Ingress | Seam Fase 1 | T0/T1 | T2+ |
|---|---|---|---|
| Teks desktop | `MainWindow.handle_command` setelah confirmation/reply gate, sebelum `IntentRouter` | Jalur intent/aksi lama utuh | Existing `MainWindow._run_agent_native` |
| Voice Gemini Live | `JarvisLive._receive_audio`, tepat sebelum FunctionCall menjadi `_execute_tool` | FunctionCall lama dieksekusi setelah transkrip final | Tool Gemini ditekan; task diserahkan sekali ke `jarvis.agent.dispatch` |
| Dashboard text | `JarvisLive._process_dashboard_commands` | Gemini Live lama | Native agent; hasil/gagal dibroadcast jujur |
| Telegram | `TelegramService._handle_task` | T0/tool-backed T1 degrade jujur tanpa LLM/agent; T1 text-only memakai Gemini satu giliran | Native agent + adapter Telegram lama |

`MainWindow._voice_intercept` tetap post-hoc dan bukan authority. Ia hanya
menghentikan aksi UI legacy untuk route T2+ supaya heavy voice yang sudah
ditangani root seam tidak dieksekusi dua kali.

### Boundary voice yang aman

- SDK `google-genai` yang terpasang diverifikasi mempunyai
  `Transcription.finished` dan `LiveServerToolCallCancellation.ids`.
- Ditambahkan `jarvis/agent/voice_gate.py` untuk menahan metadata FunctionCall
  sampai `input_transcription.finished is True`. Tidak ada aksi ringan yang
  boleh berjalan dari potongan seperti `buka` sebelum utterance lengkap.
- Setelah transkrip final, router bersama menentukan lane. Route heavy juga
  diklaim walau model belum mengirim tool call, sehingga Gemini Live bukan
  authority untuk memutuskan tugas berat.
- Bila marker final tidak tiba dalam 2,5 detik setelah tool call/turn boundary,
  gate default ke T2. Bila tidak ada teks yang dapat diserahkan, tidak ada aksi
  dijalankan dan pesan error menyatakan transkrip tidak lengkap.
- Cancellation membuang FunctionCall yang masih tertahan. Synthetic
  `FunctionResponse` dikirim untuk heavy call yang ditekan agar sesi Live
  tidak menggantung.
- Karena SDK tidak menjamin ordering transkrip terhadap model turn,
  `turn_complete` mempertahankan gate selama grace period walau teks masih
  kosong. Final transcript yang datang sesudahnya tetap diproses lalu state
  dibersihkan; pending call kosong tidak pernah dibuang tanpa response.
- Bila handoff heavy gagal sebelum mulai (provider/import/start), pesan error
  disimpan sampai turn boundary aman lalu dikirim melalui jalur suara Live;
  kegagalan tidak hanya ditulis ke log.
- Perubahan root `main.py` dibatasi pada boundary dispatch di
  `_receive_audio`, penghapusan schema Hermes, dan wrapper native agent.
  `_listen_audio`, `_send_realtime`, `_play_audio`, mic, VAD, sample rate,
  wake, STT/TTS, model Live, serta voice `Charon` tidak diubah.

### De-Hermes

- Kode nyata memakai path `hermes.enabled`, bukan saran path
  `integrations.hermes.enabled`; path nyata dipertahankan dan default diubah
  menjadi `false` di `config.yaml`.
- `jarvis.integrations.hermes.bridge.is_enabled()` menjadi guard sentral
  default-false. Resolusi executable, availability, `_run`, boot probe,
  async thread, action legacy, dan mutation messaging berhenti sebelum
  `shutil.which`, thread, file mutation, atau `subprocess.run` saat disabled.
- `core.hermes` dikeluarkan dari daftar boot default agar integrasi yang
  sengaja dipensiunkan tidak muncul sebagai warning/degraded. Check legacy
  tetap tersedia dan melaporkan status disabled sebagai kondisi sehat.
- Read path `messaging_service.list_platforms()` juga digate: saat disabled
  panel menerima payload `disabled` tanpa membaca `~/.hermes/.env`, config,
  atau gateway state.
- Tool `hermes_agent`, eager import `hermes_action`, dan cabang eksekusinya
  dihapus dari Gemini Live default schema/runtime.
- Default Browse Hub yang sebelumnya menunjuk
  `hermes-agent-main/{skills,optional-skills}` dikosongkan di config dan
  `skill_hub.py`. Runtime tidak lagi membaca/menyalin dari repo referensi;
  skill lokal yang sudah ada tidak dihapus atau ditulis ulang.
- File bridge/action dan intent compatibility lama sengaja tidak dihapus
  untuk menghindari diff besar. Jalur itu inert secara default dan memberi
  pesan jelas agar memakai agent native Jarvis.
- Tidak ada file di `hermes-agent-main/` yang diedit, dijalankan, atau
  dimasukkan ke runtime.

### File Fase 1

**Dibuat:**

- `jarvis/agent/router.py`
- `jarvis/agent/voice_gate.py`
- `tests/test_agent_router.py`
- `tests/test_voice_route_gate.py`
- `tests/test_voice_routing_integration.py`
- `tests/test_mk50_routing_seams.py`
- `tests/test_hermes_disabled.py`

**Diubah:**

- `main.py` — seam voice/dashboard dan pelepasan tool schema Hermes; tidak ada
  perubahan mekanisme atau identitas suara.
- `jarvis/ui/window.py` — seam perilaku typed dan suppression voice post-hoc;
  tidak ada perubahan visual/layout.
- `jarvis/agent/adapters/telegram.py` — pemilihan lane sebelum dispatch.
- `jarvis/agent/skill_hub.py` — hanya menonaktifkan sumber runtime Hermes
  bawaan; loader/registry/skill lokal tetap utuh.
- `jarvis/agent/__init__.py` — dokumentasi degrade diperbarui: provider kosong
  dilaporkan jujur dan tidak pernah fallback ke Hermes CLI.
- `config.yaml`, `actions/hermes_action.py`, `jarvis/core/boot.py`, dan
  `jarvis/integrations/hermes/{bridge,async_dispatch,messaging_service}.py` —
  feature flag/guards de-Hermes.
- `tests/test_hermes_integration.py` dan `tests/test_messaging_service.py` —
  jalur compatibility positif harus opt-in eksplisit.

**FROZEN yang sengaja tidak disentuh:** `ui.py`, `core/stt.py`, `core/tts.py`,
`core/voice_listener.py`, `jarvis/core/wake.py`, `jarvis/ui/theme.py`,
`jarvis/ui/orb.py`, seluruh aset/animasi orb, ActionPanel, ContentStage, dan
layout dasar. `main.py`/`window.py` hanya disentuh pada seam perilaku yang
diizinkan §1; tidak ada redesign UI pada fase ini.

### Verifikasi Fase 1

- [x] Kontrak `Tier`/`Route` lengkap; `classify` tidak pernah raise.
- [x] Rules T0/T1/T2, context T3/T4, dan contoh YouTube wajib teruji.
- [x] Gemini fallback hanya untuk ambigu; JSON gagal/provider kosong/timeout
  menjadi T2.
- [x] Teks desktop ringan mempertahankan intent lama; heavy hanya native agent.
- [x] Voice tool tidak dieksekusi dari transkrip parsial; final light berjalan
  sekali, final heavy native sekali, timeout T2, dan cancellation tidak aksi.
- [x] Simulasi urutan event Gemini Live pada `_receive_audio` membuktikan
  FunctionCall `open_app` tertahan sampai final, heavy tidak menyentuh legacy
  tool, light melepas tool sekali, timeout heavy, dan cancellation nol aksi.
- [x] Dashboard dan Telegram ringan tidak memanggil agent; heavy memanggil
  wrapper agent native yang sudah ada.
- [x] Telegram T0 tidak memakai LLM; light request yang memerlukan tool
  degrade jujur sampai adapter action-capable Fase 8 tersedia.
- [x] Intent lama `HERMES_TASK` pada lane T1 tidak dapat menaikkan kembali
  route menjadi agent/Hermes; native direct-send hanya berjalan bila adapter
  Telegram memang aktif, selain itu memberi pesan jelas.
- [x] `hermes.enabled: false`; sentinel memastikan disabled Hermes tidak
  menyentuh executable, subprocess, thread, boot probe, atau mutation config.
- [x] Schema Gemini Live default tidak memuat `hermes_agent`.
- [x] `hermes-agent-main/` bukan lagi default runtime source untuk Skill Hub.
- [x] `py_compile` lulus untuk seluruh file Fase 1 terkait.
- [x] Regresi gabungan router, seam, voice gate, Hermes/messaging, window,
  browser routing/agent, circuit/health, settings, MCP, dan Skill Hub pada
  exact final tree: **197 passed**. Regresi agent core/provider sebelumnya
  juga lulus, tetapi tidak diulang pada final run karena test curator menulis
  timestamp runtime tracked; state tersebut tetap dipulihkan ke HEAD.
- [x] Side effect test pada `.curator_state.json` dikembalikan byte-identik ke
  HEAD dan tidak masuk perubahan Fase 1.
- [x] `git diff --check` bersih; file FROZEN visual/voice mechanics tidak
  berubah.

### Sengaja ditunda sesuai urutan §13

- Kontrak ACK + LAPORAN dua fase dan pembuktian browser YouTube end-to-end
  adalah Fase 2. Callback agent lama tetap dipakai, tetapi belum diklaim
  memenuhi §4/§5.
- Pemilihan provider/model light-vs-heavy dari section `routing:` adalah
  Fase 3; Fase 1 baru memilih lane/tier.
- Tool Telegram lengkap, allowlist verification end-to-end, voice note, dan
  UI Messaging adalah Fase 8. Fase 1 hanya memastikan semua task melewati
  Router dan tidak memaksa task ringan ke agent.
- Retirement intent/UI Hermes lama direncanakan setelah adapter pengganti
  native selesai; sekarang guard default-off menjadi defense-in-depth.

---

## Fase 2 — Bug YouTube + interaktivitas (2026-07-20)

### Alur YouTube berbasis bukti

- Perintah wajib `buka dan putar youtube deddy corbuzier terbaru` tetap
  diklasifikasikan T2 oleh Router Fase 1, lalu `task_contracts.py` memberi
  kontrak eksekusi yang hanya mengizinkan tool browser aman dan tool todo.
- Browser menavigasi pencarian YouTube yang sudah diurutkan menurut tanggal,
  mengambil snapshot terstruktur (`rank`, `ref`, `title`, `channel`, `age`,
  `href`, `channel_id`, `channel_href`, `verified`). Kandidat verified dengan
  nama channel persis diprioritaskan; tanpa badge, identitas channel harus
  tunggal/tidak ambigu. Rank pertama dari channel resmi menjadi video terbaru.
  Tool desktop `open_app`, `computer_type`, tool YouTube legacy, console, dan
  CDP tidak tersedia bagi kontrak ini.
- `browser_snapshot` menjadi prasyarat runtime untuk click/type/media. Ref
  terikat pada session pemilik dan invalid setelah navigasi/scroll; referensi
  stale atau lintas-session ditolak. Browser memakai paling banyak satu host,
  context, dan page Playwright aktif; context dipertahankan sampai batas
  idle `agent.browser.idle_close_s`, lalu dibuat ulang pada pemakaian berikut.
  Lease session menolak task browser lain sebelum menyentuh page dan dilepas
  pada sukses, gagal, atau timeout; sub-agent mewarisi owner task induk.
- Sesudah click, kontrak meminta bukti `youtube_watch` terstruktur. `video_id`,
  exact `channel_name`, serta `channel_id`/`channel_href` harus cocok dengan
  hasil terpilih; kemunculan nama pada body/rekomendasi tidak cukup.
  `browser_media(action="play")` juga wajib membawa video-id target, menolak
  iklan/pre-roll atau player-id lain, lalu membuktikan elemen tidak
  paused/ended, cukup siap, dan waktu putar benar-benar maju.
- Consent/cookie yang berupa DOM ditangani melalui snapshot + ref; tool
  `browser_dialog` hanya untuk dialog JavaScript sesuai API nyata.
- Final model ditahan untuk tugas terkontrak. Jarvis hanya boleh melaporkan
  sukses setelah trace tool membuktikan urutan navigate → snapshot → pilihan
  channel → watch snapshot → playback. Klaim model tanpa bukti menjadi
  laporan gagal yang jujur.
- Kode nyata memakai tool Playwright Python `browser_*`; tidak dibuat bridge
  TypeScript, tidak memakai embedded ContentStage/Tabbit, dan tidak mengubah
  registry/loop. `agent.browser.headless` diubah menjadi `false` agar playback
  benar-benar tampil di browser; ini toggle perilaku nyata, bukan kosmetik.

### ACK dan laporan dua fase

- `interaction.py` memilih template ACK Indonesia/Inggris secara bervariasi,
  membaca sapaan persona aktual dari `core/prompt.txt`, dan membuat laporan
  sukses/gagal yang konkret serta aman untuk diucapkan. Path persona pada
  master spec bersifat saran; repo nyata tidak memiliki
  `jarvis/agent/core/prompt.txt`.
- `dispatch.dispatch_async` tetap membungkus agent loop yang ada. ACK dikirim
  setelah availability/deduplication lulus tetapi sebelum worker dimulai;
  callback terminal tepat satu kali. Provider/integrasi kosong memberi pesan
  jelas tanpa ACK palsu, crash, atau klaim sukses.
- Typed desktop dan voice memakai pipeline TTS yang sudah ada hanya melalui
  seam panggilan; mekanisme audio tidak diubah. Dashboard dan Telegram
  mengirim ACK sebelum worker lalu laporan konkret pada channel asal.
- `agent.ack_phrase` lama tetap menjadi kandidat aktif dan template baru di
  `agent.interaction.ack_templates` benar-benar memengaruhi output.

### File Fase 2

**Dibuat:**

- `jarvis/agent/interaction.py`
- `jarvis/agent/interactive_dispatch.py`
- `jarvis/agent/task_contracts.py`
- `tests/test_phase2_interactivity.py`
- `tests/test_phase2_youtube.py`
- `tests/test_phase2_browser_lease.py`
- `tests/test_phase2_dispatch.py`
- `tests/test_phase2_ingress.py`

**Diubah:**

- `jarvis/agent/dispatch.py` — lifecycle ACK/laporan, validasi bukti tugas
  terkontrak, dan release lease terminal tanpa menulis ulang
  loop/session/registry.
- `jarvis/agent/tools/browser.py` — snapshot terstruktur, ownership ref,
  context tunggal ber-lease, identitas watch, dan verifikasi playback target.
- `jarvis/agent/tools/delegate.py` — satu seam additive agar sub-agent
  mewarisi browser lease owner induk; mekanisme delegasi/loop tidak ditulis
  ulang.
- `jarvis/agent/adapters/telegram.py` — lifecycle T2 pada boundary yang sudah
  ada; fitur Telegram Fase 8 tidak dikerjakan lebih awal.
- `main.py` dan `jarvis/ui/window.py` — hanya seam perilaku voice,
  dashboard, dan typed untuk menyampaikan ACK/laporan.
- `config.yaml` — template ACK dan browser non-headless; tidak ada secret.
- `tests/test_mk50_routing_seams.py` dan
  `tests/test_voice_routing_integration.py` — ekspektasi lifecycle serta
  pencegahan tool YouTube legacy.
- `MIGRATION_NOTES.md` — catatan fase ini.

**FROZEN yang sengaja tidak disentuh:** `ui.py`, `core/stt.py`, `core/tts.py`,
`core/voice_listener.py`, `jarvis/core/wake.py`, `core/prompt.txt`,
`jarvis/ui/theme.py`, `jarvis/ui/orb.py`, seluruh aset/animasi orb, layout
dasar, ActionPanel, dan ContentStage. Perubahan `main.py`/`window.py` hanya
pada seam routing/callback; cara suara diproduksi dan tampilan tidak diubah.
Referensi `hermes-agent-main/` tidak diedit, dijalankan, atau diintegrasikan.

### Verifikasi Fase 2 (§5.5)

- [x] Perintah YouTube wajib → Router = T2.
- [x] Jalur tugas hanya membuka/menggerakkan browser; tidak mengetik ke
  window acak dan tidak mengekspos `open_app` + `computer_type`.
- [x] Fixture hasil berperingkat membuktikan peniru exact-name tanpa badge
  dilewati, identitas channel `Deddy Corbuzier` cocok dari search ke watch,
  dan kandidat resmi terbaru menang.
- [x] ACK dikirim sebelum kerja; laporan sukses baru dikirim setelah bukti
  playback, sedangkan setiap kegagalan memberi sebab yang jujur.
- [x] Snapshot wajib sebelum click/type/play; ref lintas-session/stale ditolak;
  lease mencegah interleaving page dan dilepas pada semua terminal outcome.
- [x] Cleanup snapshot/dialog atomik; job release berada di belakang job page
  aktif; race idle-close tidak menerima job stale ke context berikutnya.
- [x] Body mention, video-id/channel-id mismatch, player-id lain, dan
  iklan/pre-roll tidak dapat menghasilkan laporan sukses.
- [x] Lifecycle teruji pada typed desktop, voice, dashboard, dan Telegram.
- [x] Suite inti Fase 2 + Router/voice seam: **134 passed**.
- [x] Regresi lintas agent core, router, voice, window, browser, guard Hermes,
  messaging, circuit/health, settings, MCP, skill usage/memory pada exact tree:
  **307 passed**.
- [x] `py_compile` dan `git diff --check` lulus; timestamp curator hasil test
  dipulihkan ke HEAD dan tidak masuk perubahan.

Verifikasi seleksi/channel/playback menggunakan fixture browser deterministik
dan trace `ToolResult` aktual. Smoke test ke situs YouTube live tidak dijalankan
karena bergantung jaringan dan kondisi halaman eksternal; runtime sengaja
degrade jujur bila snapshot, consent, channel, atau playback tidak dapat
dibuktikan.

### Sengaja ditunda sesuai urutan §13

- Pemilihan provider/model per lane tetap Fase 3.
- Locale web Indonesia tetap Fase 4; ContentStage/Tabbit tetap Fase 5.
- Secrets/OAuth tidak diubah sebelum Fase 6.
- Fitur Telegram lengkap, voice-note STT, dan UI Messaging tetap Fase 8.

---

## Fase 3 — Model routing per lane (2026-07-20)

### Resolusi model per profile

- Ditambahkan `jarvis/agent/model_routing.py` di atas registry provider yang
  sudah ada (`providers.py` + `llm_client.py`) — tidak ada registry/klien
  baru. Router Fase 1 tetap satu-satunya penentu lane; modul ini hanya
  menerjemahkan `model_profile` menjadi klien nyata.
- Section `routing:` ditambahkan di `config.yaml` (§3.1): `light.provider:
  gemini` (+ `light.model` opsional) dan `heavy.provider/model/fallback`.
- Kandidat lane berat, urut: (1) `routing.heavy.provider` eksplisit —
  override `routing.heavy.model` hanya berlaku untuk kandidat ini; (2)
  provider aktif Settings BILA berbeda dari provider light — mekanisme
  pemilihan yang sudah ada tetap dihormati, tetapi Gemini light TIDAK pernah
  dipromosikan otomatis ke berat (§0 keputusan 3); (3) daftar
  `routing.heavy.fallback` (default `[openrouter, local]`). Kandidat yang
  belum terkonfigurasi dilewati dengan log; `routing.heavy.provider` yang
  menunjuk provider light tetap dihormati karena eksplisit, dengan warning
  satu kali.
- `agent_loop.run()` menerima `model_profile` (default `"heavy"` — semua
  entry loop nyata adalah Lane B: dispatch, delegate/sub-agent, cron).
  Resolusi kosong → loop TIDAK jalan dan menyampaikan pesan §3.2
  language-aware ("Model untuk tugas berat belum diatur — silakan hubungkan
  provider berat di Settings"), lalu `RunResult(ok=False)`; tidak crash,
  tidak diam, tidak diam-diam memakai Gemini.
- Failover dalam-run (§3.1): bila chat gagal dengan 402/payment/credit/
  quota/429/timeout (retry transient internal `llm_client` sudah tandas),
  loop beralih ke kandidat berat berikutnya yang siap — sekali per provider
  per run, dicatat di log + progress adapter. Rantai habis → jalur kegagalan
  jujur yang lama.
- `dispatch.available()` kini mengukur kesiapan **lane berat**
  (`model_routing.heavy_ready()`), bukan provider aktif; dispatch adalah
  pintu Lane B. `dispatch.is_active(task)` ditambahkan untuk pesan refusal.
- `interaction.unavailable_reason()` menjadi cause-aware tanpa mengubah
  signature/seam: agent disabled / heavy belum diatur (pesan §3.2) / tugas
  sama masih berjalan / fallback generik. Seluruh ingress (typed, voice,
  dashboard, Telegram) otomatis menyuarakan alasan yang benar karena semua
  refusal sudah lewat fungsi ini sejak Fase 2.
- Provider `openrouter` ditambahkan ke `DEFAULTS` (openai_compat,
  `OPENROUTER_API_KEY`) sebagai kandidat fallback §3.1/§9.3; `.env.example`
  mendokumentasikan variabelnya. Kredensial tetap lewat
  providers.json/keyring/env — tidak ada jalur plaintext baru; migrasi
  penuh ke secrets_store tetap Fase 6.

### Side-task §3.3 → lane ringan

- **Kompresi konteks:** loop tidak lagi memakai klien beratnya untuk
  `context.compact` — kini `model_routing.compression_client()`: override
  slot `auxiliary.compression.*` menang (toggle nyata), selain itu selalu
  lane ringan. Slot `compression` di `auxiliary.SLOTS` ditandai wired.
- **Embedding:** `memory_store._embed` di-pin ke `light_client()`.
  Kolisi spec vs kode: §3.3 minta embedding ke model ringan, catatan §4.2 di
  `auxiliary.py` melarang wiring karena ganti model merusak dimensi vektor.
  Resolusi: lane ringan default = `gemini` = provider yang selama ini
  dipakai embedding, jadi vektor tersimpan tetap kompatibel; pin ini justru
  menghentikan embedding ikut berpindah saat provider aktif/berat diganti.
  Mengubah `routing.light.provider` tetap berisiko dimensi (kelas risiko
  yang sama dengan mengganti provider aktif sebelumnya) — dicatat, tidak
  diperparah.
- **Classifier Router:** sudah ter-pin ke Gemini sejak Fase 1
  (`router._call_gemini_classifier`) — tidak diubah.
- **Judul sesi:** generator judul sesi TIDAK ada di kode nyata (slot
  `title_gen` auxiliary masih unwired, menunggu fitur pemakainya) — item
  §3.3 ini nihil objek; dilaporkan apa adanya, tidak dikarang.

### File Fase 3

**Dibuat:** `jarvis/agent/model_routing.py`,
`tests/test_phase3_model_routing.py`.

**Diubah:** `config.yaml` (section `routing:`), `jarvis/agent/loop.py`
(profile + degrade + failover + kompaksi ringan), `jarvis/agent/dispatch.py`
(`available()` heavy-aware, `is_active`, profile eksplisit),
`jarvis/agent/interaction.py` (refusal cause-aware),
`jarvis/agent/memory_store.py` (embed → light),
`jarvis/agent/auxiliary.py` (slot compression wired),
`jarvis/agent/providers.py` (DEFAULTS openrouter), `.env.example`,
`tests/test_agent_core.py` (2 test loop → kontrak heavy deterministik),
`tests/test_phase2_dispatch.py` (fake `agent_loop.run` menerima
`model_profile`).

**FROZEN yang tidak disentuh:** `main.py`, `ui.py`, `core/stt.py`,
`core/tts.py`, `core/voice_listener.py`, `core/prompt.txt`,
`jarvis/core/wake.py`, seluruh `jarvis/ui/` (termasuk `theme.py`, `orb.py`,
`window.py`), aset/animasi, ActionPanel, ContentStage. Fase ini murni
routing model di `jarvis/agent/` + config; tidak ada perubahan seam UI/voice.

### Verifikasi Fase 3 (§3.2 + §13)

- [x] Section `routing.light/heavy` ada di `config.yaml` dan terbaca
  (test membuktikan nilai nyata file, bukan mock).
- [x] `model_profile="heavy"` → klien dari resolusi `routing.heavy`;
  urutan kandidat, dedup, skip-unconfigured, dan model-override teruji.
- [x] Provider aktif == provider light → TIDAK menjadi kandidat berat
  (§0 kep. 3); provider aktif non-light tetap dihormati (kode nyata menang).
- [x] Toggle nyata: mengisi `routing.heavy.provider` mengubah
  `heavy_ready()` False → True pada test yang sama.
- [x] Provider berat kosong → `dispatch.available()` False; loop degrade
  dengan pesan §3.2 (id + en) via adapter; `unavailable_reason` menyuarakan
  pesan yang sama di semua ingress; tidak pernah crash/diam.
- [x] Failover dalam-run: 402/kredit/quota/timeout → provider berikutnya;
  pola non-finansial (mis. schema error) TIDAK memicu failover; rantai habis
  → gagal jujur.
- [x] Side-task §3.3: kompaksi memakai klien ringan (dibuktikan di dalam run
  loop dengan klien berat berbeda), override auxiliary tetap menang,
  embedding memakai `light_client()`.
- [x] Spot-check mesin nyata: `heavy_candidates=['openrouter','local']`,
  resolve → `local` (providers.json), `dispatch.available()` True — Gemini
  tidak lagi menjadi model tugas berat di runtime nyata.
- [x] Suite Fase 3: **24 passed**. Regresi penuh `tests/`: **597 passed**,
  0 gagal (1 fake test Fase 2 disesuaikan signature-nya, bukan perilaku).
- [x] `py_compile`, parse YAML config, dan `git diff --check` lulus;
  side-effect `.curator_state.json` dari test dipulihkan ke HEAD.

### Sengaja ditunda sesuai urutan §13

- Section `providers:` top-level (§9.3 metadata + capability) dan pemilihan
  provider berat lewat UI Settings adalah Fase 6; Fase 3 membaca registry
  provider yang sudah ada.
- OAuth OpenAI/Anthropic/OpenRouter, migrasi credential plaintext
  providers.json → secrets_store: Fase 6.
- `locale` config + berita Indonesia: Fase 4.

---

## Fase 4 — Web lokal Indonesia (2026-07-20)

### Resolver locale (§6.3)

- Ditambahkan `jarvis/core/locale.py`: prioritas **config eksplisit**
  (`locale.region/language/timezone/news_market` — section baru di
  `config.yaml`, diisi nilai §6.2 `ID/id/Asia/Jakarta/id-ID`) → **bahasa
  perintah** (reuse detektor deterministik Fase 2
  `interaction.detect_language`, dengan fallback heuristik lokal bila import
  gagal) → **Silent Language Memory XLVIII** (`identity.language` di
  `memory/long_term.json` via `memory.memory_manager.load_memory` — mekanisme
  nyata XLVIII, bukan konsep baru) → **fallback `id-ID`**. Tidak pernah
  raise; `source` direkam untuk debug.
- Helper: `ddg_region()` (format ddgs `id-id`/`us-en` — diverifikasi ke
  source paket `ddgs 9.14.4` terpasang: parameter `region` nyata di
  `_search_sync`, default `us-en`), `accept_language()` (header
  `web_extract`), `news_query()` + `is_generic_news()` (augmentasi §6.2:
  query berita **generik** diganti frasa lokal penuh; query dengan **subjek
  spesifik** tidak diubah — penargetan cukup lewat `region`, subjek user
  tidak terdistorsi).

### Injeksi ke jalur web nyata (§6.2/§6.4)

- **Tool agent** `jarvis/agent/tools/web.py`: `web_search` meneruskan
  `region=` ke `ddgs.news()` dan `ddgs.text()`; mode `news` mengaugmentasi
  query generik; format hasil sudah memuat judul + sumber + waktu.
  `web_extract` menambah header `Accept-Language` locale pada fallback
  `requests` (trafilatura `fetch_url` tidak menerima header — API nyata
  dihormati, tidak dikarang).
- **Action legacy** `actions/web_search.py` (jalur suara Gemini Live — akar
  gejala §6.1): `_ddg_search`/`_ddg_news` menyuntik region via
  `_ddg_kwargs()`; `_news()` tidak lagi membungkus dengan bahasa Inggris
  hardcode ("latest news today"/"top world news today") — query generik
  (termasuk query briefing hardcoded dari `main.py:1465` yang FROZEN)
  menjadi "berita terbaru Indonesia hari ini", subjek spesifik dibungkus
  sesuai bahasa locale; baris berita kini membawa `date` dan
  `_format_news` menampilkan sumber + waktu. Resolver locale gagal →
  perilaku lama tanpa region (degrade jujur, pencarian tidak pernah gagal
  karena locale).
- `_gemini_headlines` di action adalah **dead code** (tanpa pemanggil) —
  tidak disentuh. Jalur typed `Intent.SEARCH_WEB → run_search` adalah
  navigasi browser embedded, bukan tool web §6.2; nasib panel browser
  ditentukan Fase 5 — tidak diubah sekarang.

### File Fase 4

**Dibuat:** `jarvis/core/locale.py`, `tests/test_phase4_locale.py`.

**Diubah:** `config.yaml` (section `locale:`),
`jarvis/agent/tools/web.py`, `actions/web_search.py`.

**FROZEN yang tidak disentuh:** `main.py` (query briefing hardcoded-nya
dilokalkan dari dalam action, bukan dengan mengedit main.py), `ui.py`,
`core/stt.py`, `core/tts.py`, `core/voice_listener.py`, `core/prompt.txt`,
`jarvis/core/wake.py`, seluruh `jarvis/ui/`, aset/animasi. Tidak ada
perubahan UI/voice/seam pada fase ini.

### Verifikasi Fase 4 (§6.5)

- [x] Section `locale` ada di `config.yaml` dan terbaca (test membaca file
  nyata).
- [x] Prioritas §6.3 teruji: config eksplisit → bahasa perintah →
  Silent Language Memory → fallback `id-ID`; resolver tidak pernah raise
  (termasuk saat `config.get` melempar).
- [x] Query berita → ddgs dipanggil dengan `region="id-id"` dan query
  generik teraugmentasi lokal, di **kedua** jalur (tool agent + action
  suara); dibuktikan dengan menangkap argumen panggilan ddgs (stub, tanpa
  network).
- [x] **Mengubah `locale.region` → hasil ikut berubah:** region efektif dan
  argumen ddgs mengikuti config (`id-id` → `de-de`/`us-en`) pada test
  toggle.
- [x] Tidak ada region hardcode di tool: injeksi hanya dari resolver;
  resolver mati → tanpa region (perilaku lama), tercatat jujur.
- [x] Hasil berita menampilkan judul + sumber + waktu (tool & action).
- [x] Query briefing "top world news today" (dari `main.py` FROZEN) →
  otomatis menjadi frasa lokal di action; subjek spesifik ("berita terbaru
  Manchester United") tidak terdistorsi.
- [x] Suite Fase 4: **21 passed**. Regresi penuh `tests/`: **618 passed**,
  0 gagal. `py_compile` + parse YAML + `git diff --check` lulus; side-effect
  curator dipulihkan ke HEAD.
- [ ] *(ditunda)* Kartu berita di ContentStage panel **info**: `InfoPanel`
  belum ada — dibangun Fase 5 (§7.2); item §6.5 ini diselesaikan di sana.
- Catatan jujur: smoke test **live** ke DuckDuckGo tidak dapat dijalankan
  dari lingkungan kerja ini (TCP 10060 — jaringan ke duckduckgo.com tidak
  dapat dihubungi dari shell; dua kali dicoba). Injeksi region/query
  dibuktikan deterministik di level argumen API; validasi visual hasil live
  tinggal menjalankan Jarvis di mesin user dengan jaringan normal.

### Sengaja ditunda sesuai urutan §13

- `InfoPanel` + kartu berita/cuaca di ContentStage: Fase 5.
- Kartu cuaca ber-locale (§8.1) ikut panel Home Assistant: Fase 5.

---

## Fase 5 — ContentStage + Tabbit + Home Assistant + vision lazy (2026-07-20)

### Buang Tabbit & panel browser (§7.1)

- **Dihapus dari repo:** `jarvis/browser/skill_memory.py`,
  `config/tabbit_skills.json` (dua file yang dinamai spec), plus jalur
  Tabbit yang import-nya menjadi mati: `frame_agent.py`, `tabbit_embed.py`,
  `tabbit_resolver.py`, dan test-nya (`test_skill_memory`,
  `test_frame_agent`, `test_tabbit_embed`).
- **window.py (wiring seam yang diizinkan §1):** `EmbeddedBrowser` tidak
  dibuat/didaftarkan lagi (`self.browser = None`); `run_search`, `open_url`,
  `open_browser_agent` kini membuka **browser sistem** (`webbrowser.open`) —
  validasi skema URL (allowlist https/http) dipertahankan;
  jalur in-frame/provider lama dibuang. Helper JS yang masih dipakai
  `ReplyFlow` degrade jujur dengan hasil `no-view`.
- **Boot lebih ramping:** import `jarvis.browser.embed` (QtWebEngine) di
  `jarvis/main.py` dihapus — QtWebEngine tidak dimuat saat boot, dibuktikan
  test subprocess. File `embed.py`/`agent_view.py`/`agent.py`/`extract.py`/
  `reply.py` tetap di disk sebagai kode inert (pola minim-diff de-Hermes).
- **Koreksi kontrak §7.2:** registry MainWindow kini **tepat tiga nama**:
  `vision`, `info`, `home`. Panel `content`, `capabilities`, `messaging`,
  `settings`, browser summary, dan `browser_agent` tidak lagi menjadi child
  ContentStage. Hasil legacy `show_content` dipetakan ke kartu `InfoPanel`;
  Settings provider tetap memakai sheet non-ContentStage. Tombol lama
  Capabilities/Messaging memberi pesan status yang nyata, bukan toggle/no-op.
- Seluruh konfigurasi/provider/download khusus Tabbit dan cabang routing
  khususnya dihapus. Wrapper CLI browser generik tetap ada sebagai tool agent
  dengan konfigurasi `browser.agent_cli`, sesuai §7.1; ia tidak dimount ke UI.

### Panel baru (§7.2) + ikon (§7.3)

- `jarvis/ui/info_panel.py` — **InfoPanel** (registrasi `"info"`): kartu
  berita/cuaca/pencarian dengan judul + isi + **sumber + timestamp**, masuk
  via BUS `info.card` (marshal UI thread oleh BUS). Produser nyata: tool dan
  action `web_search` untuk mode news **serta search**, `weather_report`, dan
  facade legacy `show_content`. Kartu baru menampilkan panel hanya bila stage
  kosong/info; vision/home tidak direbut.
- `jarvis/ui/home_panel.py` — **HomePanel** (registrasi `"home"`, §8) di
  atas helper tool HA yang sudah ada (`home_assistant._url/_token/_get/
  _post` — tanpa klien duplikat): CCTV `camera.*` via **snapshot proxy
  berkala** (`/api/camera_proxy/<entity>`, 10 dtk; stream QtWebEngine
  sengaja tidak dipakai karena §7 baru membuang QtWebEngine dari boot —
  fallback snapshot diizinkan §8.2), lampu `light.*` (toggle + slider
  brightness → `POST /api/services/light/...`), kartu cuaca `weather.*`
  ber-`locale` (§6). Semua I/O di thread worker + sinyal Qt; refresh cache
  5 menit + tombol muat ulang; timer hanya jalan saat panel terlihat. Klik
  snapshot membuka tampilan besar; POST lampu diikuti GET ulang untuk
  memverifikasi state server. Tanpa `HA_URL`/`HA_TOKEN` → empty-state jujur;
  HA error → status jujur. Pembukaan panel memakai `ContentStatus.LOADING`
  sampai data atau empty-state siap.
- `actionpanel.py` — ikon `home` ("⌂") pola GlyphButton + sinyal
  `home_clicked`; `config.yaml action_panel.icons` memuat `home`;
  window wiring `_toggle_home_panel()`.

### Lazy vision (efisiensi #7)

- Kode nyata **sudah** lazy: cv2/mediapipe/ultralytics diimpor di dalam
  worker `multiprocessing` dan `VisionSystem()` tidak spawn process pada
  konstruksi (hanya `start()`/arm). Fase ini menambah **test pengunci**
  (subprocess): konstruksi VisionSystem dan import `jarvis.main` tidak
  memuat cv2/mediapipe/ultralytics/QtWebEngine.

### File Fase 5

**Dibuat:** `jarvis/ui/info_panel.py`, `jarvis/ui/home_panel.py`,
`tests/test_phase5_stage_home.py`.

**Dihapus:** `jarvis/browser/{skill_memory,frame_agent,tabbit_embed,
tabbit_resolver}.py`, `config/tabbit_skills.json`,
`tests/{test_skill_memory,test_frame_agent,test_tabbit_embed}.py`.

**Diubah:** `jarvis/ui/window.py` (registry tepat tiga, reroute browser/hasil,
loading Home, status panel legacy), `jarvis/ui/stage.py` (summary browser
dibuang + registry diagnostics), `jarvis/ui/actionpanel.py` (sinyal/glyph Home
serta status jujur), `jarvis/main.py` (tanpa import QtWebEngine), `config.yaml`
(hapus konfigurasi Tabbit + `browser.agent_cli` generik),
`jarvis/core/router.py`, `jarvis/agent/router.py`, `jarvis/browser/agent.py`
(hapus cabang provider lama), `jarvis/ui/home_panel.py` (loading, enlarge,
refresh state), `jarvis/agent/tools/web.py`, `actions/web_search.py`, dan
`actions/weather_report.py` (publisher `info.card`), test terkait:
`test_browser_routing_p0.py` (ditulis ulang ke kontrak §7),
`test_window_integration.py`, `test_browser_agent.py`,
`test_camera_and_devices.py` (blok Tabbit dibuang).

**FROZEN yang tidak disentuh:** root `main.py`, `ui.py`, `core/stt.py`,
`core/tts.py`, `core/voice_listener.py`, `core/prompt.txt`,
`jarvis/core/wake.py`, `jarvis/ui/theme.py`, `jarvis/ui/orb.py`,
aset/animasi orb, layout dasar. `window.py`/`actionpanel.py` hanya pada
wiring/ikon yang §1 izinkan eksplisit.

### Verifikasi Fase 5 (§8.3 + §7 + §6.5)

- [x] ContentStage pada MainWindow memiliki registry **eksak**
  `vision`/`info`/`home`; tidak ada content/browser/messaging/settings lain.
- [x] Panel Home tampil lewat ikon ActionPanel dan melewati state `LOADING`
  sampai data/empty-state siap.
- [x] CCTV: label kamera dibangun dari entity `camera.*`; snapshot ditarik
  dari endpoint proxy HA dan klik membuka tampilan besar.
- [x] Toggle lampu memanggil `POST /api/services/light/turn_on|turn_off`
  dengan `entity_id` benar; brightness membawa payload `brightness`; POST
  sukses diikuti `GET /api/states` untuk memverifikasi state server.
- [x] Kartu cuaca dari entity `weather.*` menampilkan region `locale` (§6).
- [x] Tanpa kredensial HA → empty-state jujur, tidak crash; HA error →
  status "tidak merespons", tidak diam.
- [x] Kartu berita, hasil pencarian, cuaca, dan hasil facade legacy tampil di
  panel **info** dengan sumber + timestamp.
- [x] Perintah URL/pencarian ringan (typed & voice, jalur identik) membuka
  browser sistem; skema di luar allowlist tetap ditolak.
- [x] Tidak ada string/config/cabang runtime Tabbit; wrapper browser CLI
  generik tetap tool agent dan tidak menjadi panel.
- [x] Lazy vision terkunci test subprocess (tanpa cv2/mediapipe/
  ultralytics/QtWebEngine saat boot/konstruksi).
- [x] Suite inti koreksi Fase 5: **102 passed**. Regresi penuh `tests/`:
  **580 passed**, 0 gagal.
- [x] Parse AST semua Python berubah, parse YAML, dan `git diff --check`
  lulus; side-effect curator dipulihkan ke HEAD.
- Catatan jujur: verifikasi terhadap **instance Home Assistant hidup**
  (feed CCTV nyata, lampu fisik berubah state) tidak dapat dijalankan dari
  lingkungan kerja ini — tidak ada HA_URL/HA_TOKEN di mesin dev. Kontrak
  request/payload dibuktikan deterministik; validasi live tinggal
  menjalankan Jarvis dengan kredensial HA Anda.

### Sengaja ditunda sesuai urutan §13

- Implementasi Messaging native di Settings: Fase 8 (§11.7). Sejak koreksi
  Fase 5, Messaging sudah tidak berada di ContentStage.
- Rencana pensiun `ui.py` + CI hash FROZEN: Fase 9.

---

## Fase 6 — Secrets + OAuth + telemetri (2026-07-20)

### Secret store berlapis dan migrasi plaintext (§9.1–§9.2)

- `jarvis/core/secrets_store.py` kini memilih backend dengan urutan
  **keyring OS → Windows DPAPI → file Fernet terenkripsi**. Operasi keyring
  yang gagal turun ke backend terenkripsi berikutnya; jika semuanya tidak
  tersedia, write gagal secara eksplisit dan credential tidak ditulis
  plaintext.
- Fallback memakai `~/.jarvis/secrets.dat`; Fernet membuat
  `~/.jarvis/.keyfile`. Direktori/file diperketat ke 0700/0600 pada POSIX dan
  DACL user proses pada Windows. Backend aktif ditampilkan di Settings.
- `jarvis/core/secret_migration.py` menjalankan migrasi satu-arah saat startup.
  Sumber lama baru disanitasi setelah `set` **dan readback** berhasil. Migrasi
  aktual mesin dev: backend **DPAPI**, **6 migrated**, **0 pending**;
  `providers.json`, `api_keys.json`, dan `youtube_oauth.json` masing-masing
  tersisa **0 field credential plaintext**. File-file ini tetap di-ignore dan
  tidak masuk commit.
- Pembaca/penulis credential aktif dan legacy yang tidak FROZEN dibungkus ke
  `secrets_store`: provider agent, Gemini text/voice adapter, dashboard,
  Settings, action legacy, Home Assistant, Spotify, YouTube OAuth, Google
  notification token, dan `memory.config_manager`. Root `main.py` tetap
  FROZEN; `jarvis/main.py` hanya mengganti fungsi pengambil API key pada
  instance legacy saat runtime.
- `.gitignore` mencakup `.env`, `config/api_keys.json`, provider/OAuth legacy,
  `google_token.json`, token Spotify, serta mirror `.jarvis/.keyfile` dan
  `.jarvis/secrets.dat`. Store normal di home memang berada di luar worktree.

### OAuth OpenAI + Anthropic dan provider berat (§9.3)

- `jarvis/integrations/oauth_loopback.py` menyediakan authorization-code
  PKCE lewat **browser eksternal** + callback localhost, timeout, validasi
  path, dan CSRF `state`; QtWebEngine tidak dipakai.
- `openai_oauth.py` sekarang adalah adapter chat Codex Responses (SSE + tool
  calls), login/refresh/logout PKCE, rotasi refresh token, dan penyimpanan
  terenkripsi. Capability-nya tepat `[chat]`; jalur image OAuth lama dibuang.
- `anthropic_oauth.py` menambah login/refresh/logout Claude OAuth serta kwargs
  bearer/header SDK yang diverifikasi terhadap referensi READ-ONLY. Referensi
  Hermes hanya dibaca, tidak diedit, dijalankan, atau dimasukkan runtime.
- API OpenAI diverifikasi ke implementasi Codex resmi:
  <https://github.com/openai/codex/blob/main/codex-rs/login/src/server.rs>.
  Dukungan callback localhost Anthropic diverifikasi ke changelog resmi:
  <https://code.claude.com/docs/en/changelog>. Uji otomatis memalsukan server
  provider/token exchange; consent akun live tidak dijalankan karena
  memerlukan browser dan akun user.
- Settings menampilkan kedua akun OAuth, status/backend, connect/disconnect,
  serta hanya menawarkan provider `chat` yang benar-benar enabled untuk
  `routing.heavy.provider`. Pilihan itu mengubah config nyata dan dibuktikan
  dipakai resolusi T2. Provider image hanya muncul bila benar-benar memiliki
  capability `image`.
- Penyesuaian kode-nyata: registry yang sudah ada memakai
  `config/providers.json`, jadi metadata provider tetap di sana (tanpa token)
  alih-alih membuat registry kedua di top-level `config.yaml`. Nama existing
  `openai` dipertahankan, tidak dipaksa menjadi contoh `openai_api` di spec.

### Telemetri tool dan keputusan retrieval

- `jarvis/agent/tool_usage.py` kini mengagregasi sukses secara incremental,
  merotasi `tools.jsonl` harian atau pada 5 MiB, dan menyimpan lifetime rollup
  lokal di `tools_rollup.json`. `registry.py` hanya dibungkus untuk delegasi
  persistence; kontrak registry/loop/skills/memory tidak ditulis ulang.
- Repo nyata hanya mempunyai **1 `SKILL.md`**. Retrieval skill tidak
  diimplementasikan karena ambang kebutuhan sekitar 40 pada spec belum
  tercapai; pemuatan skill existing tidak diubah.

### File Fase 6

**Dibuat:** `jarvis/core/secret_migration.py`,
`jarvis/integrations/anthropic_oauth.py`,
`jarvis/integrations/oauth_loopback.py`,
`tests/test_phase6_secrets_oauth.py`.

**Diubah:** `.gitignore`, `requirements.txt`, `config.yaml`,
`jarvis/core/{secrets_store,config,llm,health,notify_hub,settings_service}.py`,
`jarvis/integrations/openai_oauth.py`,
`jarvis/integrations/comments/youtube_oauth.py`,
`jarvis/agent/{providers,llm_client,registry,tool_usage}.py`,
`jarvis/agent/tools/{home_assistant,image_gen,spotify}.py`, `jarvis/main.py`,
`jarvis/ui/{actionpanel,panels,settings_providers,window}.py`,
`core/settings_ui.py`, `dashboard/server.py`, `memory/config_manager.py`,
`scripts/youtube_oauth_setup.py`, action legacy `code_helper`,
`computer_control`, `computer_settings`, `desktop`, `dev_agent`,
`file_processor`, `flight_finder`, `screen_processor`, `web_search`, dan
`youtube_video`, serta test provider/OAuth/image/telemetri terkait.

**FROZEN yang sengaja tidak disentuh:** root `main.py`, `ui.py`,
`core/stt.py`, `core/tts.py`, `core/voice_listener.py`, `core/prompt.txt`,
`jarvis/core/wake.py`, `jarvis/ui/theme.py`, `jarvis/ui/orb.py`, aset/animasi
orb, dan layout dasar. Perubahan file UI non-FROZEN hanya perilaku Settings,
status jujur, dan wiring provider yang diwajibkan §9.

### Verifikasi Fase 6 (§9.4)

- [x] Tanpa keyring, fallback Fernet menyimpan ciphertext; secret uji tidak
  terdapat pada `secrets.dat` dan readback berhasil.
- [x] Settings menampilkan backend penyimpanan aktif (`DPAPI` di mesin dev).
- [x] Flow OpenAI dan Anthropic: browser eksternal → loopback PKCE/state →
  token exchange → encrypted store → provider enabled, dibuktikan test
  deterministik; live consent akun tidak diklaim.
- [x] Provider berat yang dipilih di Settings benar-benar dipakai resolusi
  tugas T2; provider tanpa credential tidak ditandai enabled.
- [x] `secrets.dat` dan direktori store aktual lolos verifikasi DACL ketat;
  fallback Fernet menguji permission `.keyfile`/`secrets.dat`/direktori.
  Seluruh path secret diwajibkan ter-cover `.gitignore`.
- [x] Migrasi plaintext aktual selesai dengan readback dan tanpa pending;
  sumber legacy tidak lagi memuat field secret.
- [x] Rotasi size/daily, rollup, dan agregasi incremental `tools.jsonl`
  teruji; registry hanya dibungkus.
- [x] Suite fokus Fase 6: **71 passed**. Regresi penuh `tests/`:
  **582 passed**, 0 gagal (4 warning deprecation Pillow existing).
- [x] Retrieval skill dievaluasi dan sengaja tidak dibuat: hanya 1 skill,
  bukan >~40.

### Sengaja ditunda sesuai urutan §13

- OAuth Google dan tool Calendar/YouTube Data/Gmail/Drive tetap Fase 7.
- Messaging native dan credential Telegram tetap Fase 8.
- Root `ui.py` masih mempunyai wizard plaintext lama, tetapi file itu FROZEN
  dan bukan entry aktif. Usulan Fase 9: pensiunkan entry legacy sesuai spec;
  jangan mengubahnya di Fase 6.

---

## Fase 7 — Google Cloud Connector (2026-07-20)

### Satu OAuth, scope aktual, dan secret hygiene (§10.1–§10.3)

- `jarvis/integrations/google_auth.py` menjadi satu-satunya OAuth aktif untuk
  Calendar, YouTube Data, Gmail, dan Drive. Ia memakai authorization-code
  PKCE browser eksternal + callback `http://127.0.0.1:<port>/`, menyatukan
  scope API yang sedang enabled, menyimpan client ID/client secret/token dan
  scope yang benar-benar diberikan hanya di `secrets_store`, serta melakukan
  refresh token secara terkunci.
- Toggle read/write di `providers.google.apis.*` adalah metadata non-secret.
  Toggle dan granted scope bersama-sama menentukan tool yang ditemukan
  registry dan schema Gemini Live sesi berikutnya. Calendar create, Gmail
  send, dan YouTube comments/write tidak muncul tanpa toggle **dan** scope
  write; perubahan grup Tools `google_cloud` juga menekan schema/jalur T1.
- Penyesuaian terhadap dokumentasi provider terkini: Google installed app
  tidak mendukung incremental authorization. Karena itu perubahan API/scope
  meminta **Connect ulang dengan gabungan scope aktif**, bukan memakai
  `include_granted_scopes`. Endpoint authorize/token, loopback, PKCE S256,
  dan signature client library diverifikasi ke dokumentasi/implementasi
  resmi Google; YouTube comments memakai `youtube.force-ssl` yang memang
  disyaratkan endpoint `comments.insert`.
  Referensi: <https://developers.google.com/identity/protocols/oauth2/native-app>
  dan <https://developers.google.com/youtube/v3/docs/comments/insert>.
- Adapter YouTube comments/live-chat lama kini membaca OAuth Google terpadu;
  skrip `authorize` terpisah dihentikan secara eksplisit agar tidak membuat
  token kedua. API key publik YouTube tetap secret terpisah untuk jalur legacy
  read-only.

### Tool dan routing (§10.4–§10.6)

- Tool native yang ditambahkan: `gcal_events`, `gcal_create`, `gcal_next`;
  `yt_subscriptions`, `yt_latest`, `yt_search_data`, `yt_my_stats`;
  `gmail_list`, `gmail_read`, `gmail_send`; `gdrive_search`, `gdrive_read`.
  Operasi write selalu membutuhkan konfirmasi registry.
- Perintah typed ringan “agenda hari ini”, “video terbaru langgananku”, dan
  “email baru” dipetakan deterministik setelah tier router menetapkan T1,
  lalu menjalankan registry langsung dan membacakan hasil. Jalur voice memakai
  schema registry yang sama pada Gemini Live; hanya T0/T1 dieksekusi oleh Live,
  sementara request mutasi tetap dialihkan ke agent native oleh gate existing.
  Playback YouTube browser tidak diubah dan tetap T2 terpisah.
- Settings Google Cloud menyediakan client OAuth encrypted, connect/logout,
  status backend/scope, dan toggle API/write. Schema Live dibuat saat sesi
  dimulai, sehingga UI secara jujur meminta reconnect voice sesudah perubahan.
- NotificationHub Calendar/YouTube/Gmail dibungkus ke credential Google yang
  sama. Tanpa provider/credential, registry menyembunyikan tool dan startup
  tetap aman; permintaan langsung memberi instruksi setup yang jelas.

### File Fase 7

**Dibuat:** `jarvis/integrations/{google_auth,google_api,google_direct,
google_voice}.py`, `jarvis/agent/tools/{google_calendar,google_youtube,gmail,
google_drive}.py`, `tests/test_phase7_google_connector.py`.

**Diubah:** `config.yaml`, `requirements.txt`, `readme.md`,
`docs/YOUTUBE_API_SETUP.md`, `jarvis/integrations/oauth_loopback.py`,
`jarvis/integrations/comments/youtube_oauth.py`,
`jarvis/integrations/youtube_capability.py`, `jarvis/agent/{base,registry,
toolgroups}.py`, `jarvis/core/{notify_hub,settings_service}.py`,
`jarvis/main.py`, `jarvis/ui/{panels,window}.py`, dan
`scripts/youtube_oauth_setup.py`.

**FROZEN yang sengaja tidak disentuh:** root `main.py`, `ui.py`,
`core/stt.py`, `core/tts.py`, `core/voice_listener.py`, `core/prompt.txt`,
`jarvis/core/wake.py`, `jarvis/ui/theme.py`, `jarvis/ui/orb.py`, aset/animasi
orb, serta layout dasar. Perubahan UI hanya isi/wiring Settings dan seam
routing perilaku T1 pada `window.py`.

### Verifikasi Fase 7 (§10.7)

- [x] Calendar saja enabled + token Calendar readonly menghasilkan hanya
  `gcal_events`/`gcal_next`; tool Gmail/YouTube/Drive diam dan schema voice
  identik dengan registry aktif.
- [x] “Agenda hari ini” mengembalikan teks acara dan jalur T1 siap dibacakan.
- [x] “Video terbaru langgananku” memakai subscriptions/channels/uploads/
  playlistItems YouTube Data API, berlabel `youtube_data_api`, bukan browser.
- [x] “Email baru” mengembalikan jumlah/subjek Gmail unread untuk dibacakan.
- [x] OAuth client secret, access/refresh token, dan granted scopes tidak
  ditulis ke `config.yaml`; test memverifikasi payload tersimpan hanya melalui
  mock encrypted `secrets_store`.
- [x] Toggle + actual write scope mengaktifkan `gcal_create`/`gmail_send`;
  tanpa salah satunya tool tetap read-only. Write tool butuh konfirmasi.
- [x] Provider kosong: registry/schema Google kosong, startup dan Settings
  offscreen tetap aman, pesan setup eksplisit.
- [x] Suite fokus Fase 7: **8 passed**; regresi terdampak: **66 passed**;
  regresi penuh `tests/`: **590 passed**, 0 gagal (4 warning deprecation
  Pillow existing). `compileall`, parse YAML, `git diff --check`, dan smoke
  Settings offscreen lulus; side-effect curator dipulihkan ke HEAD.
- **Batas verifikasi:** consent akun Google dan panggilan live ke project/API
  nyata tidak dapat diautomasi tanpa akun user. Flow/endpoint/scope dan payload
  API diverifikasi deterministik; validasi live tinggal Connect dari Settings
  pada project Google Cloud milik user. Ini bukan fallback credential atau
  klaim palsu.

### Sengaja ditunda sesuai urutan §13

- Startup optimizations, CI hash FROZEN, pensiun `ui.py`, dan final E2E:
  Fase 9.

---

## Fase 8 — Telegram Control native + UI Messaging (2026-07-21)

### Adapter, keamanan, dan lifecycle (§11.2–§11.5)

- Fondasi `jarvis/agent/adapters/telegram.py` yang sudah ada dibungkus dan
  diselesaikan; tidak dibuat registry/loop/memory/skills kedua. Long-polling
  `python-telegram-bot` tetap satu background service dalam proses Jarvis.
- `jarvis/integrations/telegram_control.py` menjadi boundary konfigurasi:
  token dan allowlist hanya dibaca dari key namespaced
  `jarvis/telegram/{bot_token,allowed_ids}` melalui `secrets_store`. YAML hanya
  menyimpan master toggle yang benar-benar start/stop service dan batas ukuran
  voice note. Bot tidak dapat start tanpa toggle + token + minimal satu ID.
- Migrasi satu-kali dari `TG_BOT_TOKEN`/`TG_ALLOWED_IDS` lama menulis dan
  memverifikasi encrypted readback sebelum menghapus key lama dan baris
  Telegram dari `.env`; runtime adapter tidak punya fallback plaintext.
  `.env.example` tidak lagi meminta token Telegram.
- Semua handler command, callback, teks, dan voice memanggil allowlist gate
  sebagai langkah pertama. User di luar allowlist di-log ID-nya dan diabaikan
  total tanpa balasan.
- Command native tersedia: `/status`, `/stop`, `/todo`, `/memory`, `/cron`
  dengan pause/resume/run, `/screen`, `/skills`, `/session` + reset, dan
  `/confirm`. Konfirmasi registry memakai inline `✅ Lanjut` / `❌ Batal` dan
  timeout existing 300 detik.

### Router, laporan, dan voice note (§11.2/§11.6)

- Teks/hasil STT selalu masuk `classify_execution(..., {"source":
  "telegram"})`, seam tier yang sama dengan typed/voice. T0/T1 menjalankan
  tepat satu aksi/tool melalui `telegram_light.py` tanpa agent loop; Google
  Calendar/YouTube Data/Gmail memakai mapping + registry Fase 7. Integrasi/tool
  kosong memberi alasan setup yang jelas.
- T2+ tetap memakai `dispatch.dispatch_async` + `TelegramAdapter`. ACK dikirim
  segera, progress ditrottle dengan edit pesan yang sama, dan final/error
  mengganti ACK yang sama. Output lebih dari 4000 karakter menjadi `.md`;
  screenshot/image dikirim sebagai foto.
- `jarvis_voice.py` hanya mendecode OGG/Opus via PyAV ke mono float32 16 kHz,
  lalu memanggil `core.stt.WhisperSTT` yang FROZEN. File voice sementara
  dibatasi ukuran dan dihapus setelah transkripsi; dependency/STT kosong
  menghasilkan pesan eksplisit tanpa crash.
- Signature SDK Telegram (`Application.builder`, handler async, `Bot.get_me`,
  edit/document/photo) diperiksa terhadap `python-telegram-bot` 22.6 yang
  terpasang. Pola auth-first/edit/document juga dibandingkan secara READ-ONLY
  dengan `hermes-agent-main/plugins/platforms/telegram/adapter.py`; referensi
  tidak diedit, dijalankan, atau diimpor runtime.

### Settings Messaging (§11.7)

- Ikon Messaging sekarang membuka `MessagingSettingsSheet`, bukan
  ContentStage atau panel Hermes lama. Sheet memakai `QVBoxLayout`,
  `QFormLayout`, dan `QHBoxLayout`; field token bermasker, badge Saved,
  jumlah ID tersimpan, master toggle yang terkunci tanpa kredensial, status
  dot, label backend encrypted, Save/Test/Hapus/Tutup.
- Save/readback memakai `secrets_store`; Test Connection memakai SDK Bot API
  dan menampilkan nama bot. Toggle dan perubahan credential diterapkan ke
  lifecycle service tanpa restart aplikasi. Error SDK disanitasi ke tipe
  exception agar URL yang mungkin memuat token tidak pernah masuk UI/log.
- ContentStage tetap tepat `vision`/`info`/`home`; perubahan `window.py` hanya
  wiring sheet dan reposition seam. Render offscreen 700×390 mempunyai
  `sizeHint` tinggi 339 dan pemeriksaan visual tidak menemukan overlap.

### File Fase 8

**Dibuat:** `jarvis/integrations/telegram_control.py`,
`jarvis/agent/adapters/{telegram_light,jarvis_voice}.py`,
`jarvis/ui/settings_messaging.py`, dan
`tests/test_phase8_telegram_control.py`.

**Diubah:** `.env.example`, `config.yaml`, `requirements.txt`,
`jarvis/agent/adapters/telegram.py`, `jarvis/main.py`,
`jarvis/ui/{actionpanel,window}.py`, dan
`tests/test_mk50_routing_seams.py`.

**FROZEN yang sengaja tidak disentuh:** root `main.py`, `ui.py`,
`core/stt.py`, `core/tts.py`, `core/voice_listener.py`, `core/prompt.txt`,
`jarvis/core/wake.py`, `jarvis/ui/theme.py`, `jarvis/ui/orb.py`, aset/animasi
orb, dan layout dasar. STT hanya diimpor oleh wrapper baru; perubahan UI
existing terbatas pada tooltip dan wiring Settings Messaging.

### Verifikasi Fase 8 (§11.8)

- [x] Token + minimal satu ID tersimpan encrypted mengaktifkan master toggle;
  SDK `get_me()` mengembalikan nama bot dan status Connected pada test
  deterministik.
- [x] Teks bebas user allowlist melewati Router yang sama, menjalankan T0/T1
  native atau agent T2+, lalu membalas hasil.
- [x] User di luar allowlist diabaikan total tanpa reply dan tanpa mencapai
  Router/action.
- [x] Voice note didownload terbatas, masuk wrapper STT FROZEN, lalu teksnya
  kembali ke `_handle_task`/Router.
- [x] Tugas berat menghasilkan ACK sebelum kerja dan laporan akhir mengedit
  message ID yang sama; output panjang diuji menjadi Markdown.
- [x] `/screen`, `/todo`, `/stop`, dan `/confirm` diuji fungsional; seluruh
  command/callback terdaftar dengan auth-first.
- [x] Settings Messaging memakai layouts, mask/badge/toggle/status, dan smoke
  offscreen membuktikan field/tombol tidak overlap.
- [x] Modul runtime Telegram baru tidak memiliki import/pemanggilan Hermes.
  Token/IDs tidak ada di YAML/.env example; seluruh `.env`,
  `config/api_keys.json`, `.jarvis/.keyfile`, dan `.jarvis/secrets.dat`
  ter-cover `.gitignore`.
- [x] Suite fokus Fase 8: **14 passed**. Regresi penuh `tests/`:
  **604 passed**, 0 gagal (4 warning deprecation Pillow existing). Parse YAML,
  `py_compile`, `git diff --check`, audit FROZEN, dan render Settings offscreen
  lulus; side-effect curator dipulihkan ke HEAD.
- **Batas verifikasi:** tidak ada bot token/user ID nyata yang disediakan pada
  sesi ini, sehingga koneksi live Telegram tidak diklaim. Flow SDK, gate,
  lifecycle, handler, dan nama-bot diverifikasi deterministik; validasi live
  tinggal Save → aktifkan toggle → Test Connection dari Settings milik user.

### Sengaja ditunda sesuai urutan §13

- Hanya Fase 9: startup/efisiensi, CI hash FROZEN, pensiun entry UI legacy,
  dan final E2E (§12–§14). Tidak ada bagian Fase 9 dikerjakan di fase ini.

---

## Fase 9 — Finalisasi (2026-07-21)

### CI hash FROZEN (§12 #8)

- `config/frozen_manifest.json` merekam SHA-256 untuk 10 file identity-critical:
  root `main.py`/`ui.py`, STT/TTS/voice listener/persona, wake, theme, orb, dan
  ikon Jarvis. Baseline adalah commit akhir Fase 8 (`094b696`).
- `scripts/verify_frozen.py` hanya membaca dan memverifikasi manifest. Tidak ada
  opsi update otomatis. File teks dihitung sebagai byte canonical-LF agar
  checkout Windows/Linux tidak menimbulkan false positive; file biner dihitung
  byte mentah. File hilang, traversal path, mode salah, atau hash berbeda
  menghasilkan exit code 1 dengan nama file yang jelas.
- Workflow `.github/workflows/frozen-integrity.yml` berjalan pada push dan pull
  request dengan permission `contents: read`, Python 3.11, lalu menjalankan
  verifier tanpa dependency runtime Jarvis.

### Rencana pensiun UI ganda (§12 #2)

- Audit kode nyata menemukan rantai aktif
  `jarvis.main._start_voice_pipeline → main.JarvisLive → from ui import JarvisUI`.
  Jadi root `ui.py` **belum aman dihapus**: penghapusan sekarang akan merusak
  startup voice dan melanggar FROZEN.
- `docs/UI_LEGACY_RETIREMENT_PLAN.md` mendokumentasikan pemisahan dependency,
  contract/shadow test, shim satu release, acceptance perangkat nyata, rollback,
  serta kewajiban persetujuan exception FROZEN. Fase ini hanya membuat rencana;
  tidak melakukan refactor atau penghapusan UI legacy.

### Dokumentasi dan file Fase 9

**Dibuat:** `.github/workflows/frozen-integrity.yml`,
`config/frozen_manifest.json`, `scripts/verify_frozen.py`,
`docs/UI_LEGACY_RETIREMENT_PLAN.md`, dan
`tests/test_phase9_finalization.py`.

**Diubah:** `readme.md` dan `MIGRATION_NOTES.md`.

**FROZEN yang sengaja tidak disentuh:** root `main.py`, `ui.py`,
`core/stt.py`, `core/tts.py`, `core/voice_listener.py`, `core/prompt.txt`,
`jarvis/core/wake.py`, `jarvis/ui/theme.py`, `jarvis/ui/orb.py`,
`config/jarvis.ico`, aset/animasi orb, dan layout dasar. Tidak ada kode
fungsional routing, registry, loop, skills, memory, voice, atau UI yang diubah.

README final sekarang menyebut entry aktif `python -m jarvis.main`, mode
diagnostik, router per tier, konfigurasi provider, secret store, Google Cloud,
Telegram, integrasi opsional, honest degradation, dan perintah verifikasi.

### Checklist verifikasi akhir (§14)

- [x] Voice dan tema identik: `git diff` untuk seluruh 10 target kosong dan
  verifier FROZEN lulus.
- [x] Hermes mati pada jalur runtime normal: `hermes.enabled:false`; ingress
  aktif selalu memanggil compatibility boundary dengan `allow_agent=False`;
  test membuktikan bridge/CLI/thread/config Hermes tidak disentuh saat disabled.
- [x] Tugas ringan (termasuk Google read) tidak masuk agent loop dan memakai
  lane ringan; klasifikasi dan seam diuji deterministik.
- [x] Tugas berat otomatis masuk agent loop/model heavy dan degrade jujur ketika
  provider berat tidak siap.
- [x] Alur “buka dan putar YouTube … terbaru” mewajibkan resolve channel,
  bukti video terbaru, snapshot sebelum click, lalu verifikasi playback pada
  contract test; tidak memakai `open_app` + blind typing.
- [x] Berita terbaru memakai locale Indonesia/bahasa Indonesia dan dikirim ke
  panel `info` pada test deterministik.
- [x] Setiap tugas berat memiliki ACK awal dan laporan akhir, termasuk error
  jujur, pada UI/voice/Telegram adapter.
- [x] ContentStage mendaftarkan tepat `vision` / `info` / `home`; browser dan
  Tabbit tidak terdaftar.
- [x] Panel Home Assistant memiliki CCTV, toggle lampu, cuaca, serta status
  unavailable yang jujur dan teruji tanpa hardware.
- [x] Secret store keyring/fallback terenkripsi, migrasi plaintext, label backend
  Settings, dan error path teruji.
- [x] OAuth OpenAI/Anthropic serta pemilihan provider berat teruji dengan fake
  server/browser-loopback; secret tidak masuk YAML.
- [x] Google Connector satu-OAuth, gate API/scope/write, Calendar/YouTube/Gmail/
  Drive, dan jalur read yang dibacakan teruji deterministik.
- [x] Telegram allowlist, teks, voice note, ACK/report, command, callback, dan UI
  Settings teruji; user di luar allowlist tidak mencapai Router.
- [x] Integrasi opsional tanpa kredensial tetap inert dan memberi setup/status
  yang jelas; startup contract tidak crash.
- [x] `.env`, `config/api_keys.json`, `.jarvis/.keyfile`, dan
  `.jarvis/secrets.dat` tercakup `.gitignore`.
- [x] `MIGRATION_NOTES.md` lengkap sampai Fase 9 dan TITIK LANJUT final.

### Hasil regresi Fase 9

- Verifier FROZEN: **10/10 file lulus**.
- Test fokus finalizer: **6 passed**.
- Matriks checklist lintas Fase 0–9: **226 passed**.
- Suite penuh `tests/`: **610 passed**, 0 gagal; 4 warning deprecation Pillow
  existing. Side-effect curator dari test dipulihkan ke HEAD.
- `git diff --check` lulus dan diff seluruh target FROZEN kosong.
- **Batas verifikasi live:** tidak ada OAuth/account eksternal, bot token,
  browser login, perangkat Home Assistant, kamera, atau microphone milik user
  yang diberikan pada sesi ini. Karena itu koneksi Google/Telegram/HA, pemutaran
  YouTube nyata, berita live, input kamera, serta output audio perangkat tidak
  diklaim live. Contract, failure/degrade path, routing, schema, dan integritas
  byte diuji; smoke perangkat nyata tetap aksi penerimaan user.

### Keputusan final

- Seluruh item efisiensi §12 telah ditutup sesuai fase. Untuk UI ganda, hasil
  yang diwajibkan spec adalah **rencana pensiun setelah parity**; kode nyata
  menunjukkan parity dependency belum tercapai sehingga file FROZEN ditahan.
- Tidak ada fase berikutnya dalam §13. Perubahan pasca-MK50 harus dimulai hanya
  atas arahan baru dan tetap menghormati exception process FROZEN.

---

## Arsip pra-master-spec (non-otoritatif)

Bagian di bawah berasal dari pekerjaan sebelum
`JARVIS_MK50_MASTER_SPEC.md`. Status fase, keputusan Hermes, dan klaim
arsitektur di bawah tidak berlaku untuk urutan Fase 0–9 yang baru.

### Baseline Inventory lama (2026-07-16)

### Dua generasi dalam satu repo
| Generasi | Entry | UI | Status |
|---|---|---|---|
| Mark XLVIII (legacy) | `main.py` (`JarvisLive`, Gemini Live audio + tool dispatch) | `ui.py` (PyQt6 HUD) | **FROZEN** — masih dipakai sebagai voice pipeline oleh Mark XLIX |
| Mark XLIX/L (aktif) | `jarvis/main.py` (`python -m jarvis.main`) | `jarvis/ui/` (orb, stage, actionpanel, overlays) | Target integrasi |

### Titik penting
- **Voice**: `main.py::JarvisLive` (Gemini Live, voice Charon) + `core/stt.py`, `core/tts.py`, `core/voice_listener.py` → **FROZEN**. `jarvis/main.py::_start_voice_pipeline` memanggilnya apa adanya.
- **UI**: `jarvis/ui/*` + legacy `ui.py` → **FROZEN secara visual**. Perubahan hanya yang diminta user secara eksplisit (menu provider di settings, popup kalori di frame kamera) dan additive.
- **Python ↔ tool**: semua in-process Python. Tidak ada bridge JS/TS. Browser embedded = QtWebEngine; Tabbit via CDP + agent-browser CLI.
- **Komunikasi antar-modul**: `jarvis/core/bus.py` (BUS publish/subscribe, marshal ke UI thread), Qt signals.
- **Konfigurasi LLM**: `config.yaml` (`llm:`) + `config/api_keys.json` (kunci Gemini; JANGAN pernah di-commit/log). Secrets lain: env (`.env`) + `jarvis/core/secrets_store.py` (keyring, opsional).
- **Router perintah**: `jarvis/core/router.py` — `Intent.HERMES_TASK` → `jarvis/ui/window.py::run_hermes` → `jarvis/integrations/hermes/bridge.py` (subprocess Hermes CLI eksternal) + `async_dispatch.py`.
- **Memori eksisting**: `jarvis/core/memory.py` (episodic SQLite + semantic FAISS + procedural macros) — dipertahankan; agent memakai store sendiri per spec §4.
- **Vision**: `jarvis/vision/process.py` (child process, kamera tunggal) → JPEG via BUS `vision.frame` → `jarvis/ui/overlays.py::VisionPanel`. Snapshot on-demand: `VisionSystem.latest_frame_jpeg()`.
- **Kamera legacy**: `core/camera_vision.py` (dipakai ui.py lama) — tidak disentuh.
- **Settings gear**: `jarvis/ui/actionpanel.py::SettingsSheet` (ikon ⚙ di ActionPanel) — saat ini hanya field API key Gemini.
- **Dependency terpasang** (dipakai, tidak perlu install baru): `openai 2.24`, `anthropic 0.87`, `google-genai 2.11`, `python-telegram-bot 22.8`, `ddgs 9.14`, `trafilatura 2.1`, `croniter 6.0`, `playwright 1.61`, `mss`, `pydantic 2`, `keyring? (opsional, guarded)`.
- **Python**: 3.11.11. Repo BUKAN git repository → tidak ada commit per fase; verifikasi FROZEN via inventaris hash (lihat bawah).

### Deviasi dari jarvis.md (kenyataan menang)
1. Spec menyarankan folder `core/` baru — **bentrok** dengan `core/` legacy. Agent core ditaruh di **`jarvis/agent/`** (package baru, additive).
2. Spec menyarankan browser bridge TS/Playwright-server — repo sudah punya Playwright **Python** + embedded browser + Tabbit CDP. Browser tools agent memakai Playwright Python langsung (lebih sederhana, tanpa bridge baru).
3. Referensi Hermes sudah ada di `hermes-agent-main/` (bukan `_ref/hermes-agent`) — dipakai read-only.
4. Repo bukan git repo → checklist "git diff --stat kosong" diganti verifikasi manual: file FROZEN tidak pernah dibuka untuk ditulis kecuali daftar "File Disentuh" di bawah.
5. Integrasi Hermes CLI lama **tetap ada** sebagai fallback; agent native jadi jalur utama `HERMES_TASK`.

### File FROZEN (tidak boleh diubah)
`main.py`, `ui.py`, `patch_ui.py`, `core/stt.py`, `core/tts.py`, `core/voice_listener.py`, `core/reactor.py`, `core/camera_vision.py`, `core/prompt.txt`, seluruh `jarvis/ui/*` (kecuali seam minimal yang diminta user — lihat "File Disentuh"), aset `config/jarvis.ico`, `dashboard/static/*`, model `yolov8*`.

### Permintaan user (2026-07-16) yang MENGAMENDEMEN spec
1. Implementasikan seluruh kemampuan hermes-agent secara **native** di Jarvis.
2. Ikon gear/settings → menu **multi-provider API key** (Gemini, OpenAI, Anthropic, **local OpenAI-compatible**, custom) yang menopang kemampuan agent.
3. **Vision kalori makanan**: analisis via kamera, hasil **pop-up di dalam frame kamera**.

---

## File Baru (semua additive)

```
jarvis/agent/                     # agent core native (pengganti Hermes CLI)
  __init__.py
  base.py                         # Tool + ToolResult (kontrak §3)
  registry.py                     # auto-discovery tool
  providers.py                    # registry provider LLM (config/providers.json)
  llm_client.py                   # klien unified: openai-compat | anthropic | gemini
  schema.py                       # Tool → JSON schema per provider
  loop.py                         # agentic loop (§6)
  session.py                      # state sesi + cancel + transcript
  context.py                      # kompaksi context window
  dispatch.py                     # ACK instan + worker thread (kontrak async_dispatch)
  memory_store.py                 # memori agent §4 (SQLite FTS5 + vektor)
  reflect.py                      # self-learning reflector §4.4
  cron.py                         # scheduler cron (croniter) persist SQLite
  skills.py                       # loader skill markdown (frontmatter, lazy body)
  prompts/system.md               # system prompt §7
  tools/ (file_ops, terminal, code_exec, web, todo, clarify, memory_tools,
          session_tools, vision, computer, browser, delegate, cron_tools,
          skill_tools, image_gen, home_assistant, spotify, food)
  adapters/ (base.py, ui.py, telegram.py)
jarvis/vision/food_calories.py    # analisis kalori (vision LLM, JSON ketat)
jarvis/ui/settings_providers.py   # sheet settings multi-provider (menggantikan tampilan sheet lama via seam)
jarvis/ui/calorie_popup.py        # kartu pop-up kalori di dalam VisionPanel (eventFilter, tanpa edit overlays.py)
config/providers.json             # konfigurasi provider (dibuat runtime, tidak di-commit bila berisi kunci)
data/                             # runtime agent: agent.sqlite, logs/, generated/
tests/test_agent_core.py, tests/test_agent_memory.py, tests/test_agent_cron.py,
tests/test_food_calories.py, tests/test_providers.py
```

## File Disentuh (seam minimal, dibenarkan oleh permintaan user / additive)
| File | Perubahan | Alasan |
|---|---|---|
| `jarvis/ui/window.py` | (1) pakai `ProviderSettingsSheet` dari file baru menggantikan instansiasi `SettingsSheet`; (2) `run_hermes` → coba agent native dulu, fallback Hermes CLI; (3) handler aksi `calorie_analyze` + wiring popup kalori; semua ±30 baris, tanpa perubahan styling | Permintaan user #2, #3; seam agent |
| `jarvis/core/router.py` | + pola SYSTEM `calorie_analyze` (kalori makanan) | Permintaan user #3 |
| `jarvis/main.py` | + blok opsional start Telegram adapter + cron scheduler (try/except, gaya sama dengan relay) | Kemampuan Hermes (Telegram, cron) |
| `config.yaml` | + section `agent:` (additive di akhir file) | Konfigurasi agent |
| `.env.example` | + var agent/Telegram/HA/Spotify | Dokumentasi |

`jarvis/ui/actionpanel.py` TIDAK diubah — `SettingsSheet` lama tetap ada; sheet baru hidup di file baru.

## Progress Log
- [x] Fase 0 — Discovery + baseline (dokumen ini)
- [x] Fase 1 — Fondasi (providers, llm_client, base, registry, loop, dispatch)
- [x] Fase 2 — Tool inti (file, terminal, code, todo, clarify)
- [x] Fase 3 — Memori + self-learning (memory_store, reflect, session_search)
- [x] Fase 4 — Adapter (UI, Telegram + whitelist)
- [x] Fase 5 — Browser tools (Playwright Python, 12 tool, snapshot ber-ref)
- [x] Fase 6 — Web + vision + kalori makanan (popup di frame kamera)
- [x] Fase 7 — Computer use (6 tool, pyautogui + mss)
- [x] Fase 8 — Skills + delegation (loader lazy, sub-agent no-recursion)
- [x] Fase 9 — Cron (croniter + SQLite, konsolidasi memori mingguan)
- [x] Fase 10 — Integrasi (HA 3, Spotify 9 + OAuth PKCE, image gen)
- [x] Fase 11 — Settings provider UI + finalisasi + tests

## Verifikasi (2026-07-16)
- **52 tool** terdaftar via auto-discovery; schema OpenAI valid untuk semua.
- Provider aktif resolve: gemini (kunci lama config/api_keys.json terbaca); `dispatch.available()` True.
- **Tests: 327 passed** (286 lama + 41 baru), 0 gagal. File baru: test_agent_core, test_agent_memory, test_agent_cron, test_providers, test_food_calories, test_calorie_router.
- Agent loop end-to-end mencapai Gemini nyata; menangani 503 (retry 2x → lapor) dengan benar. Jalur sukses terbukti via test fake-LLM (`test_loop_completes_with_fake_llm`).
- **FROZEN utuh**: mtime `main.py`, `ui.py`, `core/tts.py`, `core/stt.py`, `core/camera_vision.py`, `core/prompt.txt`, `jarvis/ui/overlays.py`, `jarvis/ui/actionpanel.py` semuanya < 2026-07-16 (tak tersentuh). Hanya seam yang diizinkan diedit: window.py, router.py, main.py, config.yaml, .env.example.
- UI impor bersih; `ProviderSettingsSheet`, `CalorieOverlay`, `_agent_ask_active` terpasang; persona loader membaca core/prompt.txt (2870 char) apa adanya.
- Integrasi opsional (Telegram/HA/Spotify) `available()` = False tanpa kredensial → nonaktif senyap, Jarvis tetap start.

## Cara pakai (ringkas)
1. **Provider**: klik ikon gear ⚙ → pilih provider (Gemini/OpenAI/Anthropic/Local/Custom) → isi base URL + API key + model → SIMPAN → JADIKAN AKTIF (tombol TEST untuk ping). Local = LM Studio/Ollama/llama.cpp/vLLM (isi base URL mis. `http://localhost:1234/v1` + model).
2. **Agent**: perintah multi-step ("suruh jarvis riset X", "buatkan script Y", "jadwalkan Z") otomatis masuk agent native (fallback Hermes CLI bila `agent.enabled=false`).
3. **Telegram**: isi `TG_BOT_TOKEN` + `TG_ALLOWED_IDS` di `.env` → restart. User non-whitelist diabaikan total.
4. **Kalori**: ucapkan/ketik "berapa kalori makanan ini" / "analisis kalori" → kamera terbuka, hasil pop-up di dalam frame + suara.
