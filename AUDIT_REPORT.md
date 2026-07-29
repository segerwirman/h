# AUDIT_REPORT — J.A.R.V.I.S (Mark XLVIII → Mark XLIX → MK50 Hybrid)

| | |
|---|---|
| **Repo** | `github.com/segerwirman/h` (branch `main`, 1 commit) |
| **Tanggal audit** | 2026-07-27 |
| **Audit sebelumnya** | `AUDIT_REPORT.md` (2026-07-17) — dokumen ini **menggantikan**-nya |
| **Bahasa** | Python 98.2%, HTML 1.8% |
| **Lisensi hulu** | CC BY-NC 4.0 (Mark XLVIII © FatihMakes) — atribusi wajib dipertahankan |

---

## 1. Metodologi & Batasan Audit — baca ini dulu

> **REVISI 2 — 2026-07-27 (putaran kedua, clone lokal).**
> Putaran pertama dilakukan **dari luar lewat web GitHub** dan tidak bisa membaca
> `jarvis/`, `actions/`, `core/`, `tests/`, `dashboard/`, `ui.py`, maupun paruh
> kedua `main.py`. **Seluruh zona itu kini sudah dibaca langsung di clone lokal.**
> Beberapa temuan naik ke `[TERBUKTI]`; **beberapa dibantah**, termasuk salah satu
> temuan KRITIS.
>
> **Bukti kode lengkap (kutipan + `file:baris`) ada di
> [`docs/AUDIT_FINDINGS_CODE.md`](docs/AUDIT_FINDINGS_CODE.md).** Dokumen ini
> tetap dapat dibaca tanpa membuka kode.

### Status pembacaan

| Zona | Putaran 1 (web) | Putaran 2 (lokal) |
|---|---|---|
| `config.yaml`, `.gitignore`, `patch_ui.py`, `mw.txt` | ✅ penuh | ✅ dikonfirmasi |
| `main.py` | ⚠️ ~1000/1865 baris | ✅ **penuh (1865)** |
| `ui.py` | ❌ tak terbaca | ✅ **struktur + zona relevan (2621)** |
| `jarvis/agent/` (47 modul) | ❌ | ✅ **dibaca** |
| `jarvis/agent/tools/` (23 modul) | ❌ | ✅ **dibaca + hitung AST** |
| `jarvis/ui/`, `jarvis/core/`, `jarvis/vision/`, `jarvis/nlp/`, `jarvis/browser/`, `jarvis/integrations/` | ❌ | ✅ **dibaca** |
| `actions/` (20 modul) | ❌ | ✅ **dipetakan penuh** |
| `core/` (10 modul + `prompt.txt`) | ❌ | ✅ **dibaca** |
| `dashboard/server.py` | ❌ | ✅ **17 rute dienumerasi** |
| `tests/` (99 berkas) | ❌ | ✅ **dijalankan + dikategorikan** |
| `scripts/`, `docs/`, `memory/`, `config/` | ❌ | ✅ struktur (isi kredensial **tidak** dibuka) |

### Metode putaran 2

Pembacaan kode langsung + verifikasi eksekusi:

- `pytest tests/ -q` dijalankan sungguhan → **859 lulus**
- `python scripts/verify_frozen.py` dijalankan → **OK, 10 berkas**
- Jumlah tool dihitung ulang lewat **AST**, bukan grep
- `heavy_ready()` / `dispatch.available()` diperiksa **saat runtime**
- Isi `memory/long_term.json` vs `data/agent.sqlite` dibandingkan **langsung**

**Aturan penandaan.** `[TERBUKTI]` = kodenya dibaca, ada `file:baris`.
`[DIBANTAH]` = klaim lama diperiksa dan **salah**. `[TURUNAN]` seharusnya sudah
tidak tersisa; bila masih ada, itu bug di laporan ini.

> ⚠️ **Skrip `audit_dead_code.sh` di §7.4 BERBAHAYA bila diikuti harfiah.**
> Ia akan menandai 13 modul `jarvis/agent/tools/` sebagai "YATIM" padahal
> semuanya hidup lewat auto-discovery `pkgutil` di `jarvis/agent/registry.py:42`.
> Lihat N-24.

---

## 2. Ringkasan Eksekutif

Repo ini **bukan proyek kecil yang berantakan**. Ini proyek yang cukup ambisius
dan sebagian besar sudah matang, tetapi sedang berada di tengah **migrasi tiga
generasi yang belum ditutup**. Itu sumber dari hampir semua masalahnya.

**Tiga generasi hidup bersamaan di satu working tree:**

| Gen | Entry point | UI | Otak | Status nyata |
|---|---|---|---|---|
| **Mark XLVIII** | `main.py` | `ui.py` (HUD padat) | Gemini Live + `actions/*` | FROZEN — tapi **masih dieksekusi** sebagai pipeline suara |
| **Mark XLIX** | `python -m jarvis.main` | `jarvis/ui/*` (orb sinematik) | membungkus `main.py` | UI aktif |
| **MK50** | idem | idem | `jarvis/agent/*` (52 tool) | Otak aktif |

Konsekuensinya: **dua UI, dua sistem tool, dua sistem memori, dua sistem
konfigurasi** berjalan berdampingan. Itu bukan kekacauan estetis — itu berarti
model bahasa bisa memilih jalur yang lebih lemah untuk tugas yang sama.

**Tiga temuan paling penting — setelah putaran 2 semuanya berubah:**

1. **🔴 [S1] BARU — ini sekarang temuan paling serius di repo.**
   Tool `execute_code` menjalankan python/bash/**powershell** arbitrer
   **tanpa konfirmasi apa pun**, dan input-nya 100 % dari LLM. Digabung dengan
   `web_extract` yang menelan konten web tak tepercaya, ini rantai
   **prompt-injection → RCE** yang lengkap dan bisa diverifikasi hari ini.
   Perbaikannya **satu baris**. Lihat §5.0.

2. **🔴 [H-1b] Bug memori terpisah — TERKONFIRMASI, dengan bukti isi database.**
   Fakta yang Anda ucapkan tersimpan di `memory/long_term.json`; agent membaca
   `data/agent.sqlite`. Tidak ada jembatan. Pemeriksaan langsung: 5 fakta di
   JSON, 55 baris di sqlite, **irisan nol**. Dugaan putaran 1 benar.

3. **✅ [C-1] DIBANTAH — masalah "Jarvis hilang saat bekerja" tidak seperti yang
   dikira.** Agent **tidak** single-flight (registrinya `dict`, tiap tugas dapat
   thread sendiri); yang ditolak hanya kalimat yang **identik persis**. Mic tetap
   hidup selama agent bekerja. Penekanan output berlangsung **satu giliran, ~2,5
   detik** — bukan 900 detik. Yang benar-benar rusak jauh lebih kecil dan lebih
   mudah diperbaiki: hasil tugas bisa **memotong Jarvis di tengah kalimat**
   (N-1), dan **tidak ada cara membatalkan tugas dari suara atau UI** (N-2).

**Kabar baiknya:** fondasi untuk memperbaiki ketiganya **sudah ada di repo**.
`jarvis/agent/session.py` punya cancel, `jarvis/core/bus.py` punya pub/sub,
`ContentStage` punya registrasi panel, `config.yaml` bahkan sudah
mendefinisikan state orb `EXECUTING` dengan `progress_ring: true`. Yang hilang
adalah **lapisan orkestrasi tugas** di antaranya. Spesifikasinya ada di §8.

---

## 3. Peta Arsitektur Nyata

```
                       python -m jarvis.main
                                │
            ┌───────────────────┴────────────────────┐
            │        jarvis/main.py  (boot)          │
            │  urutan kritis: import QtWebEngine     │
            │  SEBELUM QApplication (main.py:20)     │
            └───────────────────┬────────────────────┘
                                │
        ┌───────────────┬───────┴────────┬──────────────────┐
        ▼               ▼                ▼                  ▼
 ┌────────────┐  ┌─────────────┐  ┌────────────┐   ┌────────────────┐
 │ LANE SUARA │  │  LANE UI    │  │ LANE VISI  │   │  LANE AGENT    │
 │ (legacy)   │  │ (Mark XLIX) │  │ (proses    │   │    (MK50)      │
 │            │  │             │  │  terpisah) │   │                │
 │ main.py    │  │ jarvis/ui/  │  │jarvis/     │   │ jarvis/agent/  │
 │ JarvisLive │  │  orb.py     │  │ vision/    │   │  loop.py       │
 │            │  │  stage.py   │  │  process.py│   │  registry.py   │
 │ Gemini     │  │  window.py  │  │  yolo.py   │   │  session.py    │
 │ Live API   │  │  overlays   │  │  gestures  │   │  dispatch.py   │
 │ (Charon)   │  │  actionpanel│  │            │   │  memory_store  │
 │            │  │             │  │ multiproc  │   │  cron / skills │
 │ TOOL_DECL  │  │             │  │ spawn      │   │  reflect       │
 │ 20 tool    │  │             │  │            │   │  52 tool       │
 │ → actions/ │  │             │  │            │   │  → agent/tools │
 └─────┬──────┘  └──────┬──────┘  └─────┬──────┘   └───────┬────────┘
       │                │                │                  │
       └────────────────┴────────────────┴──────────────────┘
                                │
                    jarvis/core/bus.py  (BUS pub/sub → marshal ke Qt thread)
```

### 3.1 Alur satu giliran suara `[TERBUKTI dari main.py]`

```
1.  Mic (sounddevice, 16 kHz mono) ──stream──▶ Gemini Live session
2.  _build_config() menyusun system_instruction dari TIGA sumber:
       [CURRENT DATE & TIME]  +  format_memory_for_prompt(load_memory())
                              +  core/prompt.txt
3.  Model membalas AUDIO (24 kHz) atau memanggil tool
4.  _execute_tool(fc) → dispatch ke actions/*.py
       • dibungkus asyncio.wait_for(TOOL_TIMEOUT_S=60s)
       • tool hang tidak bisa membekukan receive-loop
       • gagal → speak_error() → user diberi tahu, bukan diam
5.  FunctionResponse dikirim balik → model menjawab dengan suara
6.  Audio dipotong ~50 ms (2400 byte) → ESC bisa memotong dalam <100 ms
7.  PipelineStateMachine: IDLE→LISTENING→TRANSCRIBING→PROCESSING→SPEAKING
       + watchdog per state, correlation request_id per perintah
```

**Detail yang bagus dan layak dipuji:**

- `screen_process` mengembalikan `[VISION_ACTIVE]` yang **menyuruh model bicara
  dulu** ("Looking at your screen now") sebelum gambar dikirim di pesan
  berikutnya. Itu menghilangkan keheningan canggung — trik UX yang benar.
- Cooldown vision 4 detik + flag `_vision_busy` mencegah *echo loop*: Jarvis
  mendengar suaranya sendiri lalu memicu `screen_process` kedua.
- `save_memory` dipanggil **diam-diam** (`"silent": True`) dan tidak pernah
  diumumkan ke user.
- Monkey-patch `subprocess.Popen` di baris paling atas file memaksa
  `CREATE_NO_WINDOW` pada **setiap** child process. Tidak ada kedipan CMD.

### 3.2 Alur tugas agent `[TERBUKTI dari main.py::_dispatch_native_agent]`

```
Perintah multi-langkah  →  Intent.HERMES_TASK  →  window.run_hermes()
                                                        │
                        agent_dispatch.dispatch_async(task, on_ack, on_done, on_error)
                                                        │
      ┌─────────────────────────────────────────────────┤
      │  _on_ack   → delivery_lifecycle.acknowledged()  → speak() ke sesi Live
      │  _on_done  → delivery_lifecycle.success(naturalize=True) → speak()
      │  _on_error → delivery_lifecycle.failure()       → speak()
      └─────────────────────────────────────────────────┘
                                                        │
                             ▼ SELAMA INI BERJALAN:
                  _native_agent_tool_responses(calls, status)
                  ──▶ "Acknowledge suppressed Live tool calls
                       WITHOUT executing them"
```

Baris terakhir itu adalah inti masalahnya. Komentar aslinya di `main.py`:

> `# VoiceToolGate akan menyampaikan notice ini setelah boundary turn aman,`
> `# saat output Gemini lama tidak lagi ditekan.`

dan nilai balik fungsinya:

> `return True, "Tugas dialihkan satu kali ke agent native Jarvis."`

**Terjemahan ke bahasa manusia:** saat agent bekerja, tool-call Gemini
di-*acknowledge tapi tidak dieksekusi*, dan output lamanya "ditekan". Satu
tugas, sekali jalan. Jarvis secara efektif berhenti menjadi asisten sampai
tugas itu selesai.

---

## 4. Inventaris Konfigurasi `[TERBUKTI — config.yaml 777 baris]`

`config.yaml` sebenarnya **file terbaik di repo ini**. Klaim di headernya
("Source code contains zero magic numbers") tampaknya dipegang serius. Isinya:

| Section | Isi | Catatan |
|---|---|---|
| `theme`, `themes` | 3 preset (cyan_gold, stealth_dark, alert_red) | lengkap dgn log_colors |
| `orb` | state machine visual: IDLE/LISTENING/THINKING/SPEAKING/**EXECUTING**/ERROR | ⭐ lihat §8 |
| `ui.action_panel` | 12 ikon: vision, upload, spotify, home, awareness, focus_mode, palette, timeline, capabilities, messaging, gateway_ops, settings | titik ekstensi UI |
| `hotkeys` | F1–F11 + ESC, dgn tanda `do-not-regress` | disiplin bagus |
| `llm` | live `gemini-2.5-flash-native-audio-preview-12-2025`, text `gemini-3.5-flash` | |
| `routing` | lane light / conversation / heavy + `fallback: [openrouter, local]` | arsitektur dewasa |
| `wake` | double-clap: kalibrasi ambient, crest factor, spectral ratio, debounce | jauh di atas rata-rata |
| `voice.barge_in` | interupsi berbasis RMS mic + `tts_grace_ms` anti-echo | |
| `vision` | YOLO v8 (600 kelas OIV7), profil fast/balanced/accurate, backend TensorRT→CUDA→DirectML→ONNX→CPU | |
| `gestures` | pinch, swipe, palm-hold emergency stop, filter One-Euro | |
| `awareness` | screen awareness + **denylist privasi** + retensi 24 jam | ⚙️ `enabled: false` |
| `memory` | dedup 30s, kompaksi, retensi 180 hari/20k baris, retrieval berbobot | |
| `agent` | 50 iterasi, timeout 900s, context 128k, threshold 0.7, workspace sandbox | |
| `auxiliary` | 9 slot model per side-task (vision, reflect, compression, …) | `embedding` ditandai TERKUNCI |
| `curator` | lifecycle skill: stale 14 hari → archive 45 hari | `enabled: true` |
| `mcp` | daftar server MCP stdio | kosong |
| `dashboard` | **loopback-only**, LAN opt-in + wajib TLS + read-only | ✅ default aman |
| `release_controls` | feature flag: naturalizer, plugins, gateway, deterministic_delivery | pola rollout dewasa |
| `locale` | region ID, `Asia/Jakarta`, `news_market: id-ID` | |

**Yang mengejutkan (positif):** `awareness` — modul kesadaran layar ambient —
**sudah dibangun**, lengkap dengan denylist (`password`, `incognito`,
`1password`, …), perceptual-hash change detection, adaptive sampling 2–30 detik,
dan retensi 200 snapshot / 24 jam. Ini persis fitur "JARVIS selalu mengawasi"
yang saya sarankan sebelumnya — ternyata tinggal dinyalakan, bukan dibangun.

---

## 5. Temuan — diurutkan berdasarkan tingkat keparahan

### 5.0 🔴 KRITIS — KEAMANAN (blok baru, putaran 2)

> Putaran 1 mengaudit keamanan **dari dokumen**. Putaran 2 mengauditnya
> **dari kode**, dan hasilnya jauh lebih serius. Model ancamannya bukan
> penyerang jaringan — ini asisten lokal dengan akses terminal + desktop +
> berkas, digerakkan LLM yang **menelan konten web tak tepercaya**.
> **Musuh utamanya prompt injection.**

#### S1 — `execute_code` menjalankan kode arbitrer tanpa konfirmasi `[TERBUKTI]` 🔴

`jarvis/agent/tools/code_exec.py:34-40` mendeklarasikan kelas `ExecuteCode`
**tanpa `requires_confirmation` dan tanpa override `needs_confirmation()`**.
Default basis `jarvis/agent/base.py:55` adalah `False`, sehingga
`jarvis/agent/registry.py:143` menghitung `needs = False` dan tool berjalan
**tanpa satu pun prompt**. Bahasa yang diterima termasuk `powershell`
(`code_exec.py:23`). "Sandbox"-nya hanya menetapkan `cwd` (`code_exec.py:51`) —
tidak ada pemisahan user, container, maupun pembatasan filesystem.

Rantai lengkapnya terbukti di repo: `web_extract` menarik URL apa pun tanpa
validasi dan mengembalikan 16.000 karakter ke konteks model; dispatch lokal
mengirim `context=None` (`main.py:782-788`), sehingga `registry.py:110`
**melewati seluruh blok policy**; lalu `execute_code` jalan. Ditambah
monkey-patch `CREATE_NO_WINDOW` global (`main.py:13-22`), **eksekusinya tak
terlihat di layar**.

**Perbaikan: satu baris** — `requires_confirmation = True`.

#### S2 — `file_search`/`file_list` menembus sandbox `[TERBUKTI]` 🟠

`jarvis/agent/tools/file_ops.py:159-163` dan `:213-216` menerima `path` absolut
apa pun **tanpa memanggil `_inside_sandbox` sama sekali**, dan `read_only = True`
berarti tidak pernah ada konfirmasi. Daftar-lewat (`file_ops.py:16-17`) tidak
memuat `config`, `.ssh`, maupun `.aws`.

Satu tool-call tersuntik — `file_search(pattern=".", path="<home>/.ssh")` —
mengalirkan hingga 60 baris × 200 karakter material kredensial langsung ke
konteks LLM, tanpa prompt dan tanpa jejak. **Perbaikan: dua baris.**

#### S6 — sandbox `workspace_root` hanya anjuran `[TERBUKTI]` 🟠

`_inside_sandbox` **hanya dipanggil dari tiga override `needs_confirmation`**
(`file_ops.py:54`, `:90`, `:124`) — **tak pernah dari `run()`**. Batas keamanan
sepenuhnya berada di prompt UX, bukan di fungsi I/O. Diperparah fail-open di
`registry.py:141-145`: bila pengecekan melempar, fallback-nya `False` →
penulisan diteruskan tanpa prompt.

> **S3–S13 lainnya** (command injection `open_app.py`, blacklist `terminal`,
> `pip install` pilihan LLM, `exec()` di sandbox bocor, SSRF, token dashboard
> abadi, `_ensure_network_access` yang meminta UAC dan menurunkan Public→Private)
> ada lengkap dengan bukti di
> [`docs/AUDIT_FINDINGS_CODE.md`](docs/AUDIT_FINDINGS_CODE.md) §8.

**Yang bersih:** nol `os.system`, nol `pickle`, nol `eval()` sejati, nol nilai
rahasia yang ter-log, traversal dashboard ditangani benar, dan
`jarvis/core/dashboard_security.py` gagal-tertutup dengan sangat baik.

---

### 🔴 KRITIS — ASLI (putaran 1)

#### C-1 — ~~Agent single-flight & lane suara diblokir~~ `[DIBANTAH]`

> **Status: DIBANTAH pada putaran 2.** Klaim ini lahir dari salah baca dua hal
> sekaligus, dan konsekuensinya besar: **§8 dirancang untuk memperbaiki masalah
> yang sebagian besar tidak ada.**

Yang diperiksa dan ternyata salah:

| Klaim putaran 1 | Kenyataan |
|---|---|
| "Hanya satu tugas latar pada satu waktu" | `dispatch.py:24-25` — registrinya `dict[str, TaskHandle]`, tiap tugas dapat thread sendiri (`:295`). Yang ditolak **hanya teks tugas identik** (`:66-67`, `:217-221`). Sudah ada `active_count()`, `active_tasks()`, `cancel_all()` (`:99-114`). |
| "VoiceToolGate menekan output" | `voice_gate.py:1-7` — ia **ordering gate**, menahan `FunctionCall` sampai transkripsi final agar perintah separuh-ucap tidak dieksekusi. Ia tidak menekan apa pun. |
| "Jendela mati bisa 15 menit" | Penekanan sebenarnya adalah variabel lokal `suppress_live_output` (`main.py:1058`), **direset di batas giliran** (`main.py:1076`) atau oleh timer **2,5 detik** (`main.py:86-88`). `agent.task_timeout_s: 900` tidak ada hubungannya. |
| "Jarvis berhenti responsif" | `_listen_audio` (`main.py:1008-1046`) task asyncio independen; gerbangnya hanya `_is_speaking`/`muted`/`_phone_active` — **tak satu pun disentuh agent**. |

**Diganti oleh C-1′ `[TERBUKTI]`:** konkurensi agent **sudah berfungsi**, tetapi
**tak terlihat dan tak terkendali** —

- **N-1** Hasil tugas dapat **memotong Jarvis di tengah kalimat**. `speak()`
  (`main.py:663-672`) mengirim `turn_complete=True` seketika tanpa antrean
  batas-giliran. *Ini satu-satunya bagian §8.4b yang benar-benar perlu dibangun.*
- **N-2** **Tidak ada jalur batal dari suara maupun UI.** Rantainya lengkap
  (`dispatch.py:62` → `session.py:81` → `loop.py:165`), tetapi satu-satunya
  pemanggil produksi adalah Telegram (`adapters/telegram.py:391`), itu pun
  `cancel_all()`. Cek pembatalan juga hanya di **awal iterasi** — tool yang lama
  berjalan tak bisa dipotong.
- **N-3** **Tidak ada batas jumlah tugas sama sekali.** Tidak ada semaphore,
  tidak ada `max_concurrent`.

#### C-2 — Tidak ada model data tugas; progres tak terlihat `[TERBUKTI]`

Dikonfirmasi, tetapi **dipersempit**. Kanal progres memang ada — `loop.py:187`,
`:265` memanggil `adapter.progress(...)` — namun ujungnya hanya baris log
(`jarvis/agent/adapters/ui.py:83-86`):

```python
    async def progress(self, text: str) -> None:
        win = self._win()
        if win is not None:
            win.write_log(f"SYS: {text}")
```

`str` masuk, baris log keluar. Tidak ada `Task` object, tidak ada id, tidak ada
event `agent.task.progress` di BUS — BUS hanya membawa sinyal terminal
(`dispatch.py:238`, `:271`, `:276`).

**Koreksi penting atas "yang ironis" di putaran 1:** state orb `EXECUTING`
**tidak mati** — ia di-set dari **tujuh titik produksi** di `jarvis/ui/window.py`
(`:804`, `:851`, `:889`, `:943`, `:964`, `:996`, `:1043`), dan progress ring
**sudah dirender penuh** (`jarvis/ui/orb.py:477-478`, `:664-674`). Yang hilang
**hanya sumber datanya**: `set_progress()` cuma dipanggil dari harness dev
(`orb.py:716`), jadi busur selalu digambar 0 %. Lihat N-4/N-5.

---

### 🟠 TINGGI

#### H-1 — Generasi arsitektur belum ditutup `[TERKONFIRMASI SEBAGIAN]`

Kerangkanya benar, **detailnya banyak yang salah**, dan satu koreksi besar:
**ini bukan tiga generasi, tapi empat.** `core/stt.py`, `core/tts.py`,
`core/llm_client.py`, `core/installer.py` semuanya berkepala `"MARK XL"` —
satu generasi **lebih tua** dari Mark XLVIII, dan tidak tercatat di §3.

| Domain | Klaim putaran 1 | Kenyataan (putaran 2) |
|---|---|---|
| Tool | `actions/` 20 modul vs 52 tool | **82 tool** agent (52 = jumlah tanpa kredensial), **21** deklarasi suara (bukan 20), **21–33** saat runtime. `actions/` = 8.996 baris vs tools = 4.361 — **jalur legacy dua kali lebih besar** |
| Duplikasi | "sistemik" | **Hanya 2 dari 20** modul benar-benar kembar. 10 tumpang tindih sebagian, **8 tanpa padanan MK50 sama sekali** |
| UI | "dua UI berjalan berdampingan" | **DIBANTAH** — hanya satu diinstansiasi (`jarvis/main.py:99`). `ui.py` **diimpor** (`main.py:38`) tapi `JarvisUI`-nya tak pernah dipakai di jalur MK50. Ini **beban impor mati**, bukan dua UI |
| Penjadwalan | "duplikasi" | **Bukan duplikasi** — `actions/reminder.py:147/203/253` memakai penjadwal **OS** sehingga **selamat dari restart**; `cron_create` hanya menyala selama proses hidup. Jaminan berbeda |

**⚠️ Yang terlewat sepenuhnya di putaran 1 — arah ketergantungan terbalik.**
`jarvis/agent/tools/` **tidak mengimpor apa pun** dari `actions/`. Tetapi kode
**MK50 lain justru bergantung padanya**:

```
jarvis/agent/adapters/telegram_light.py:38   from actions.open_app import open_app
jarvis/agent/adapters/telegram_light.py:89   from actions import computer_settings
jarvis/ui/window.py:587, :808                from actions.open_app import open_app
jarvis/ui/window.py:855                      from actions.computer_settings import computer_settings
```

**Konsekuensi:** "pensiunkan `actions/`" (§9 Prioritas 3) **jauh lebih mahal**
daripada yang tertulis. Menghapusnya hari ini menghilangkan peluncuran aplikasi,
volume/kecerahan/wifi, otomasi Steam/Epic, kirim IM, pencarian penerbangan, dan
pemrosesan PDF/office/audio/video.

**Divergensi keamanan nyata (N-15).** `jarvis/agent/tools/computer.py:15`
mengambil lease eksklusif `DESKTOP`; `actions/computer_control.py`,
`computer_settings.py`, dan `game_updater.py` menyetir pyautogui **tanpa lease**.
Perintah suara legacy dan `computer_click` agent bisa **berebut mouse** — persis
yang coba dicegah §8.2. Mekanismenya ada; jalur legacy tidak memakainya.

**Tabrakan nama nyata (N-14).** `web_search` adalah deklarasi legacy
(`main.py:145`) **dan** kelas tool MK50 (`tools/web.py:42`) — nama identik,
fitur berbeda, dan **keduanya bisa terlihat model yang sama** setelah
`google_voice.install()` (`jarvis/main.py:47`).

#### H-1b — Bug memori terpisah `[TERKONFIRMASI]` 🔴

Dugaan putaran 1 **benar**, dan sekarang terbukti sampai ke isi database.

`save_memory` suara → `main.py:829` → `memory/memory_manager.py:76` →
`memory/long_term.json`. Agent → `loop.py:64` → `memory_store.py:287` →
`data/agent.sqlite`.

**Tidak ada jembatan.** Kata `long_term` **tidak muncul sama sekali** di seluruh
`jarvis/agent/`. Tidak ada migrasi, tidak ada cron sinkronisasi (`cron.py:178`
hanya sqlite→sqlite). Handoff suara→agent juga tidak membawa memori:
`main.py:782-788` tidak pernah mengisi `context`, sehingga
`memory_access.py:17-18` mengembalikan scope `device-local`.

**Bukti empiris:** 5 fakta di JSON, 55 baris di sqlite, **irisan nol**.

**Dan ini berlaku dua arah** — fakta yang dipelajari agent tidak pernah masuk
`system_instruction` Gemini Live (`main.py:703`). Ditambah **lapis ketiga**
(`memory.sqlite`, `jarvis/core/memory.py:56`) yang hanya memberi makan timeline
UI dan **tidak masuk system prompt mana pun** (`episodic_log` kosong di disk).

Perbaikan minimal ada di lampiran §2i — **menyentuh `main.py` yang FROZEN**,
jadi butuh izin eksplisit.

#### H-2 — `patch_ui.py` adalah bahaya aktif `[TERBUKTI — saya baca 88 barisnya]`

```python
ui_file = r"e:\Jarvis\mark48\Mark-XLVIII-main\ui.py"
...
with open(ui_file, 'w', encoding='utf-8') as f:
    f.write(content)
```

- Path absolut ke direktori mesin **lain** (`e:\Jarvis\mark48\…`), bukan repo ini.
- **Menulis ulang `ui.py` di tempat** — file yang oleh `MIGRATION_NOTES.md`
  dinyatakan FROZEN.
- Mengimpor `core.social_manager` dan `core.social_ui` — modul yang tidak
  tercantum di manapun dalam dokumentasi arsitektur saat ini.
- Ditandai "FROZEN" di `MIGRATION_NOTES.md`, yang artinya *jangan sentuh* —
  padahal yang benar adalah **hapus**.

Satu `python patch_ui.py` yang tidak sengaja = UI legacy rusak atau, kalau path
kebetulan cocok, patch ganda yang korup.

#### H-3 — `mw.txt` = 37 KB kode mati `[TERBUKTI]`

751 baris, salinan mentah `class MainWindow` dari `ui.py`, disimpan sebagai
`.txt`. Tidak diimpor siapa pun. Bahayanya bukan ukurannya — bahayanya adalah
**ia akan menyimpang** dari `ui.py`, dan setiap `grep` (termasuk grep yang
dilakukan AI coding assistant) akan menemukan dua versi kebenaran.

#### H-4 — `config.yaml` menyediakan slot rahasia plaintext, dan **tidak** di-gitignore `[TERBUKTI]`

`.gitignore` sangat baik untuk `.env`, `config/api_keys.json`,
`config/providers.json`, keyring fallback, dsb. Tetapi `config.yaml`
**tidak** diabaikan — dan berisi field ini:

```yaml
notifications:
  instagram_token: ""      # Graph API token
  facebook_token:  ""
email:
  imap_user: ""            # komentar: "SECURITY: gunakan env"
  imap_password: ""        # komentar: "SECURITY: gunakan env"
integrations:
  spotify: { client_id: "" }
  home_assistant: { url: "" }
```

Filenya sendiri di tempat lain menyatakan *"secrets via keyring only"* dan
*"Kredensial tetap di Settings/keyring/env — BUKAN di file ini."* Konfigurasi
ini **membantah kebijakannya sendiri**. Saat ini kosong, jadi belum bocor —
tapi ini jebakan yang menunggu diisi.

**Perbaikan:** hapus keenam field itu. Baca hanya dari `secrets_store` / env.
Kalau field harus tetap ada untuk dokumentasi, ganti nilainya menjadi nama
secret (`imap_password_secret_name: "jarvis/email/imap"`), mengikuti pola yang
**sudah benar** dipakai di `integrations.youtube.api_key_secret_name`.

#### H-5 — Bridge Hermes `[TERKONFIRMASI SEBAGIAN — lebih baik dari dugaan, tapi belum aman dihapus]`

**Kabar baik:** gerbangnya **lengkap dan gagal-tertutup**, jauh lebih rapi dari
dugaan putaran 1. `bridge.py:35-42` memakai `is True` (nilai truthy tapi bukan
`True` tidak mengaktifkan), dan **setiap** batas eksekusi dijaga — termasuk
`bridge.py:117-118` tepat sebelum satu-satunya `subprocess.run`. Komentar
`bridge.py:115-116` menyatakannya sebagai security boundary yang disengaja, dan
`tests/test_hermes_disabled.py:48-72` membuktikannya dengan meracuni cache.
**Tidak ada impor saat boot**, dan `CircuitBreaker` bukan efek samping impor.
`main.py` dan `ui.py` root: **nol** referensi hermes.

**Koreksi:** `actions/hermes_action.py` **tidak** "masih diimpor" — `actions/`
tidak punya `__init__.py`, dan `main.py:43-61` tidak mengimpornya.

**Koreksi kedua:** `hermes-agent-main/` **ada di disk lokal — 151 MB, 6.442
berkas**. Jadi PARITY tidak merujuk sesuatu yang hilang; ia merujuk sesuatu yang
**hanya-lokal dan tidak tereproduksi**. Runtime tidak pernah membacanya, dan itu
ditegakkan (`skill_hub.py:18` blocklist).

**Yang MASIH berjalan meski `enabled: false` (N-21):**

1. **Regex router jalan tanpa syarat** — tidak ada pemeriksaan flag di
   `jarvis/core/router.py` sama sekali. `Intent.HERMES_TASK` masih dipancarkan
   (`:179`, `:192`, `:244`) dan dikonsumsi (`window.py:721-725`). Jadi
   **`run_hermes()` adalah fungsi hidup**. Dengan `allow_agent=False` ia hanya
   bisa mengirim Telegram native atau menolak keras — impor bridge di `:927-928`
   tak terjangkau. ⚠️ Efek samping: perintah yang cocok pola itu **ditolak
   diam-diam** bila bot native tidak jalan.
2. **Toggle Settings masih bisa mempersenjatai ulang bridge tanpa restart**
   (`settings_service.py:297-306` → `config_write.py:57` `config.reload()`).
   Panelnya kebetulan tidak diinstansiasi di produksi, tapi menyunting
   `config.yaml` dengan tangan tetap mempersenjatai penuh.
3. **`scripts/verify_hermes.py` tanpa penjaga flag** (`:28`).

**Verdict: TIDAK aman dihapus sebagai satu operasi** — 4 penghambat (jalur
Telegram native yang hidup, registrasi `boot.py:149`, 67 asersi tes, dan
`MessagingPanel`). **Aman dihapus hari ini: `scripts/verify_hermes.py`** —
menghapusnya justru *mengurangi* risiko. Urutan pensiun bertahap ada di
lampiran §5f.

**Catatan penting soal nama:** `jarvis/nlp/agent.py::HermesAgent` **bukan
bridge** — ia orkestrator ReAct mandiri, **diinstansiasi di setiap boot**
(`jarvis/main.py:86-88` → `assistant.py:40`), dengan `can_handle` lantai 0.65.
Menghapusnya menghilangkan handler yang bekerja.

---

### 🟡 SEDANG

#### M-1 — `setup.py` bukan file packaging `[TERBUKTI dari readme.md]`

README mendeskripsikan `setup.py` sebagai *"First-run configuration wizard"*.
Tetapi `setup.py` di root adalah **nama yang direservasi setuptools**. Siapa pun
yang menjalankan `pip install .` atau `python setup.py` akan memicu wizard
konfigurasi, bukan instalasi. Rename → `scripts/first_run_wizard.py`.

#### M-2 — Dua file requirements, tanpa pyproject `[TERBUKTI]`

`requirements.txt` (Mark XLVIII) + `requirements-xlix.txt`. README bahkan
mengakui *"Some OS-specific dependencies are not bundled … If you hit a
ModuleNotFoundError, install the missing package"* — itu bukan manajemen
dependensi, itu menyerah. Konsolidasi ke `pyproject.toml` dengan extras
(`[voice]`, `[vision]`, `[agent]`, `[dev]`).

#### M-3 — README menyesatkan `[TERBUKTI]`

README saat ini adalah README **Mark XLVIII milik FatihMakes**, tidak diubah.
Ia menyuruh `git clone https://github.com/FatihMakes/Mark-XLVIII.git`, dan tidak
menyebut sama sekali: `python -m jarvis.main`, agent 52-tool, gesture, YOLO,
cron, skill, Telegram, curator, MCP, atau `config.yaml`. Sekitar 60% kemampuan
sistem tidak terdokumentasi. → Diganti oleh `README.md` baru.

#### M-4 — Enam dokumen spesifikasi menumpuk di root `[TERBUKTI]`

`AUDIT_REPORT.md`, `JARVIS_HERMES_PARITY_v2.md`, `MARK-XLIX.md`,
`MIGRATION_NOTES.md`, `Tutorial.MD`, `jarvis.md` — semuanya di root, sebagian
sudah kedaluwarsa. Audit 17 Juli mendeskripsikan kondisi *sebelum* MK50 selesai;
membacanya sekarang menghasilkan kesimpulan yang salah. Perhatikan juga
`Tutorial.MD` memakai ekstensi kapital sementara yang lain `.md` — di
filesystem case-sensitive (Linux/CI) ini menggigit.

#### M-5 — `image_generation` kemungkinan besar salah konfigurasi `[TERBUKTI]`

```yaml
image_generation:
  provider: openai_oauth
  model: gpt-image-2
```

`JARVIS_HERMES_PARITY_v2.md §7.3.1` — dokumen di repo ini sendiri —
memperingatkan bahwa akses `gpt-image-2` lewat OAuth ChatGPT **"Belum
terverifikasi"**, dan bahwa rate limit berbasis *usage tier* mengindikasikan
jalur API key berbayar. Konfigurasi aktif memilih justru jalur yang belum
terverifikasi itu. Kemungkinan gagal saat runtime dengan pesan yang
membingungkan.

#### M-6 — Injeksi JS balasan memakai selector terlalu umum `[TERBUKTI]`

```javascript
document.querySelector('[contenteditable="true"]') || document.querySelector('textarea')
document.querySelector('[aria-label*="Send"], [aria-label*="Kirim"]') || document.querySelector('button[type="submit"]')
```

Ini akan mengetik ke **elemen contenteditable pertama** dan menekan **tombol
submit pertama** di halaman apa pun. Di aplikasi web modern dengan banyak
composer (Gmail + chat widget + komentar), risiko salah kirim nyata. Mitigasi
yang ada (`auto_send: false`, `confirmation_required: true`) hanya berlaku di
jalur YouTube; JS-nya sendiri tidak punya pengaman.

**Perbaikan:** selector per-platform eksplisit + langkah *dry-run* yang
mengembalikan teks elemen target untuk dikonfirmasi sebelum klik.

#### M-7 — Riwayat git kosong `[TERBUKTI]`, klaim tes `[DIBANTAH]`

Repo memang punya **1 commit** (`dc41ef9`). Tapi dua klaim turunannya salah:

- **"327 tests passed tidak dapat diverifikasi"** → **DIBANTAH.** Suite
  dijalankan: **859 lulus, 0 gagal, 0 error, 0 skip, 38 detik.** Angka 327 di
  `MIGRATION_NOTES.md:1473` **usang, bukan salah** — dokumennya tidak pernah
  diperbarui. Kualitasnya juga bagus: **nol smoke test**, ~98,4 % tes perilaku
  nyata, hanya 14 tes (1,6 %) yang sekadar menjaga artefak statis.
- **"FROZEN utuh tidak dapat diverifikasi"** → **DIBANTAH.**
  `python scripts/verify_frozen.py` → `FROZEN integrity: OK (10 files)`.

**Tapi ada temuan baru (N-7):** `baseline_commit` di manifest adalah `094b696`,
yang **tidak ada di riwayat repo**:

```
$ git cat-file -t 094b696
fatal: Not a valid object name 094b696
```

Hash isi tetap cocok sehingga integritas berkas terjaga — tetapi acuan
"disetujui terhadap apa" menggantung.

**Lubang cakupan tes yang nyata (N-6):** `dispatch.cancel_all()` **tidak pernah
benar-benar dieksekusi tes mana pun** — kedua tes yang menyebutnya justru
me-*monkeypatch*-nya (`test_gateway_telegram_migration.py:102`,
`test_phase8_telegram_control.py:426`). Seluruh rantai pembatalan yang dipicu
user tidak tercakup; `rg "cancelled=True" tests/` → nol hasil. Ini persis jalur
yang N-2 andalkan.

Tidak ada `.github/workflows/` — masih berlaku.

---

### 🟢 RENDAH (tetap perlu dibereskan)

| ID | Temuan | Bukti |
|---|---|---|
| L-1 | Semua warning Python dibungkam global (`showwarning` di-no-op + `filterwarnings("ignore")`) di baris pertama `main.py`. Di tengah migrasi besar, ini menyembunyikan justru sinyal yang paling Anda butuhkan. | TERBUKTI |
| L-2 | `shutdown_jarvis` memakai `os._exit(0)` setelah `time.sleep(1)` — melewati seluruh cleanup: SQLite tidak di-flush, kamera tidak di-release, thread tidak di-join. | TERBUKTI |
| L-3 | Monkey-patch `Popen` global membuang `startupinfo` (`kw.pop("startupinfo", None)`). Library pihak ketiga yang sah mengirimkannya akan berubah perilaku secara senyap. | TERBUKTI |
| L-4 | `qt.conf` di root tanpa dokumentasi. Kalau bukan untuk bundling PyInstaller, ia bisa mengarahkan Qt ke path plugin yang salah. | TURUNAN |
| L-5 | `boot.morning_briefing_enabled: false` — fitur yang dipromosikan besar-besaran di README ternyata mati secara default. | TERBUKTI |
| L-6 | `TOOL_TIMEOUT_S=60` (lane suara) vs `agent.task_timeout_s=900` — perbedaan 15× yang tidak didokumentasikan; mudah disalahpahami sebagai bug. | TERBUKTI |

---

## 6. Yang Dikerjakan dengan Sangat Baik

Audit yang cuma mengeluh adalah audit yang buruk. Ini bagian yang sebaiknya
**tidak diubah**:

- **Bounded everything.** Setiap tahap eksternal punya timeout: tool 60s,
  response watchdog, TTS watchdog, circuit breaker, exponential backoff
  3→6→12→60s. Jarvis tidak pernah diam tanpa penjelasan.
- **Visi di proses terpisah** (`multiprocessing` spawn). Crash YOLO/MediaPipe
  tidak bisa menjatuhkan UI. Keputusan arsitektur yang benar.
- **Setiap subsistem opsional.** Kredensial hilang → `available()` False →
  modul mati senyap, Jarvis tetap start. Tidak ada hard-crash.
- **Dashboard aman secara default.** Loopback-only, LAN opt-in eksplisit,
  wajib TLS untuk LAN, `lan_read_only: true`, rate limit auth 10/menit.
- **`.gitignore` teliti** — termasuk mirror worktree portabel
  (`**/.jarvis/secrets.dat`), sesuatu yang biasanya terlewat.
- **Config-driven murni.** 777 baris tunable, nol magic number di kode
  (klaim yang tampaknya dipegang).
- **Wake-word double-clap** dengan crest factor + spectral ratio + adaptive
  noise floor + echo suppression saat TTS. Ini pekerjaan DSP serius, bukan
  threshold amplitudo naif.
- **Disiplin `do-not-regress`** ditulis langsung di konfigurasi untuk hotkey
  F4/F11/ESC dan model/voice. Bentuk dokumentasi-sebagai-kontrak yang jarang.

---

## 7. Daftar File: Hapus, Pindahkan, Pertahankan

> ⚠️ **Semua tabel di bawah wajib diverifikasi dengan skrip §7.4 sebelum
> `git rm`.** Saya tidak bisa membaca isi `jarvis/` dan `actions/`.

### 7.1 🗑️ Hapus sekarang — aman, terbukti mati

| File | Ukuran | Alasan | Risiko hapus |
|---|---|---|---|
| `mw.txt` | 37 KB | Salinan mentah `class MainWindow` dari `ui.py`. Tidak diimpor. Akan menyimpang dari sumbernya. | **Nol** |
| `patch_ui.py` | 3,5 KB | Skrip sekali-pakai, path absolut mesin lain, **menulis ulang `ui.py`**, mengimpor modul tak terdokumentasi. Aktif berbahaya. | **Nol** (justru menghilangkan risiko) |

```bash
git rm mw.txt patch_ui.py
```

### 7.2 📦 Pindahkan ke `docs/` — jangan hapus, ada nilai historis

| Dari | Ke | Alasan |
|---|---|---|
| `AUDIT_REPORT.md` (lama) | `docs/history/AUDIT_2026-07-17.md` | Snapshot pra-MK50; menyesatkan bila dibaca sebagai kondisi terkini |
| `JARVIS_HERMES_PARITY_v2.md` | `docs/history/HERMES_PARITY_v2.md` | Merujuk `hermes-agent-main/` yang di-gitignore → tak bisa diakses pembaca |
| `MARK-XLIX.md` | `docs/MARK-XLIX.md` | Masih berguna (hotkey, gesture, catatan arsitektur) |
| `MIGRATION_NOTES.md` | `docs/MIGRATION_NOTES.md` | Log kerja aktif |
| `jarvis.md` | `docs/history/SPEC_MK50.md` | Spesifikasi asal |
| `Tutorial.MD` | `docs/TUTORIAL.md` | **Sekalian perbaiki kapitalisasi** — `.MD` menggigit di filesystem case-sensitive |

Sisakan di root hanya: `README.md`, `AUDIT_REPORT.md` (yang ini), `LICENSE`.

### 7.3 🔍 Kandidat hapus — WAJIB verifikasi dulu

| Target | Alasan curiga | Perintah verifikasi |
|---|---|---|
| `jarvis/integrations/hermes/**` | `hermes.enabled: false`, ditandai deprecated MK50 §0.1 | `grep -rn "integrations.hermes\|HermesBridge" --include=*.py .` |
| `actions/hermes_action.py` | idem | `grep -rn "hermes_action" --include=*.py .` |
| `requirements-xlix.txt` | Duplikasi; harus jadi extras di `pyproject.toml` | manual diff dgn `requirements.txt` |
| `qt.conf` | Tak terdokumentasi | `grep -rn "qt.conf\|QT_PLUGIN_PATH" .` |
| ~~`core/social_manager.py`, `core/social_ui.py`~~ | ❌ **KLAIM SALAH — JANGAN HAPUS.** Keduanya diimpor `ui.py:19-20`, bukan hanya `patch_ui.py`. `ui.py` hidup lewat `main.py:38`, dan **keduanya FROZEN**. Menghapus → `ImportError` di jalur suara produksi | sudah diverifikasi — tidak perlu dicek lagi |
| `actions/*` yang punya kembaran di `jarvis/agent/tools/*` | Duplikasi H-1 | **JANGAN hapus sekarang** — `main.py` legacy masih memakainya. Baru setelah §8 Fase 4. |

### 7.4 Skrip verifikasi — ⚠️ JANGAN DIIKUTI HARFIAH

> **PERINGATAN (putaran 2).** Skrip di bawah **berbahaya bila hasilnya dituruti
> tanpa berpikir.** Pemeriksaan "file tak pernah diimpor" akan menandai **13
> modul di `jarvis/agent/tools/`** sebagai `YATIM` — `clarify.py`, `code_exec.py`,
> `cron_tools.py`, `file_ops.py`, `food.py`, `google_drive.py`,
> `session_tools.py`, `spotify.py`, `todo.py`, `vision.py`, dan lainnya.
>
> **Semuanya HIDUP** lewat auto-discovery `pkgutil` di
> `jarvis/agent/registry.py:42-47`. Menghapus salah satunya **menghilangkan
> kapabilitas agent secara diam-diam, tanpa `ImportError` sebagai peringatan.**
>
> Hasil audit yang sudah diverifikasi ada di §7.6 — pakai itu, bukan skrip ini.

```bash
#!/usr/bin/env bash
# scripts/audit_dead_code.sh — jalankan dari root repo
set -u
echo "═══ 1. File tak pernah diimpor ═══"
for f in $(find . -name "*.py" -not -path "./.git/*" -not -path "*/__pycache__/*"); do
  mod=$(basename "$f" .py)
  [ "$mod" = "__init__" ] && continue
  hits=$(grep -rn --include="*.py" -E "(^|[^.\w])(import|from)\s+[\w.]*\b${mod}\b" . \
         | grep -v "^${f}:" | wc -l)
  [ "$hits" -eq 0 ] && echo "  YATIM: $f"
done

echo "═══ 2. Path absolut hardcoded (bug portabilitas) ═══"
grep -rn --include="*.py" -E '["'"'"']([a-zA-Z]:\\|/home/|/Users/)' . || echo "  bersih"

echo "═══ 3. Jalur Hermes yang masih hidup ═══"
grep -rn --include="*.py" -iE "hermes" . | grep -v "^\./docs/" || echo "  bersih"

echo "═══ 4. Tool duplikat: actions/ vs jarvis/agent/tools/ ═══"
comm -12 <(ls actions/*.py 2>/dev/null | xargs -n1 basename | sort) \
         <(ls jarvis/agent/tools/*.py 2>/dev/null | xargs -n1 basename | sort)

echo "═══ 5. Rahasia plaintext di file yang TIDAK di-gitignore ═══"
git ls-files -z | xargs -0 grep -lniE "(password|token|api_key|secret)\s*[:=]\s*['\"][^'\"]{8,}" \
  2>/dev/null || echo "  bersih"

echo "═══ 6. File besar > 60 KB (kandidat pecah) ═══"
find . -type f -size +60k -not -path "./.git/*" -printf "  %k KB  %p\n" | sort -rn
```

### 7.6 ✅ Hasil verifikasi nyata — pakai ini

**Aman dihapus (terbukti nol referensi, sudah disilangkan dengan keempat
mekanisme pemuatan dinamis) — total 2.644 baris:**

| Berkas | Baris | Bukti |
|---|---:|---|
| `patch_ui.py` | 88 | Nol hit kode; menulis ke path **di luar pohon** (`:4`) |
| `mw.txt` | 750 | Nol hit kode; bukan modul |
| **`core/llm_client.py`** | 586 | **Relik "MARK XL"**, nol importer. Semua hit `llm_client` menunjuk `jarvis/agent/llm_client.py` yang **berbeda dan hidup** |
| **`core/installer.py`** | 138 | **Relik "MARK XL"**, hanya docstring-nya sendiri yang cocok |
| `scripts/verify_hermes.py` | 102 | Nol importer; satu-satunya pemanggil bridge **tanpa penjaga flag** |
| `actions/youtube_video.py.bak` | 680 | `.bak` — tak bisa diimpor |
| `jarvis/agent/tools/google_youtube.py.bak` | 202 | `.bak` di dalam folder auto-discovery; `pkgutil` hanya memuat `.py`, jadi **tidak** dimuat — tapi membayangi nama modul hidup di setiap grep/IDE |
| `create_jarvis_profile.py.bak` | 98 | Sintaks **rusak** di `:50` (`680Kilau,`) |

**Kode mati di dalam berkas hidup (N-17):** `actions/screen_processor.py:397`
`screen_process()`, `:445` `warmup_session()`, dan kelas `_VisionSession`
(`:208`) tak terjangkau — `main.py:870` mengimplementasikan ulang tool itu
inline, dan `main.py:50` hanya mengimpor `_capture_camera, _capture_screen`.

**⚠️ RAGU — jangan hapus tanpa keputusan Anda:**

- **`jarvis/core/notify_hub.py`** (191) — nol referensi, tapi docstringnya
  menyebut *"NotificationHub (Mark L Change 1)"*. Ini **fitur dibangun tapi
  belum disambung**, bukan bangkai.
- **`jarvis/integrations/youtube_capability.py`** (111) — nol referensi, tapi
  isinya **invarian keamanan** ("API key tidak cukup untuk memposting balasan").
  Menghapusnya membuang penjaga.
- **17 modul "matang tapi belum tersambung"** — masing-masing punya tepat satu
  importer, dan itu **tes**. Termasuk `plugins/*`, `gateway/platforms/*`,
  `runtime/evaluation.py` (yang bahkan punya runbook di
  `docs/EVALUATION_RUNBOOK.md`). **Jangan hapus massal.**
- `qt.conf` — Qt memuatnya **berdasarkan konvensi nama**, bukan impor.
  Ketiadaan referensi **tidak membuktikan apa pun**. Butuh uji DPI.
- `setup.py` — **ganti nama, jangan hapus** (M-1 masih berlaku).

### 7.5 ✋ Jangan sentuh

`core/prompt.txt` (persona — milik Anda), `config.yaml` (kecuali hapus 6 field
rahasia di H-4), `memory/`, `dashboard/`, `tests/`, `scripts/`,
`jarvis/ui/theme.py` (design token), `.gitignore`.

---

## 8. SPESIFIKASI FITUR — Task Deck & Agent Konkuren

> Ini menjawab permintaan utama Anda: **melihat tugas yang berjalan di latar,
> dan tetap bisa bicara dengan Jarvis saat itu terjadi.**

> ### ⚠️ BACA DULU — §8 ditulis di atas premis yang sebagian DIBANTAH
>
> Spesifikasi ini dirancang untuk memperbaiki C-1 ("agent single-flight, lane
> suara diblokir 900 detik"). **C-1 sudah dibantah.** Banyak yang §8 usulkan
> untuk dibangun **ternyata sudah ada**:
>
> | §8 mengusulkan | Kenyataan |
> |---|---|
> | §8.3 "ganti single-flight" di `dispatch.py` | **Sudah multi-flight.** `_active` adalah `dict`, tiap tugas dapat thread sendiri (`dispatch.py:24-25`, `:295`) |
> | §8.4a "cabut gate di `main.py`" | **Tidak ada gate untuk dicabut.** Penekanan hanya satu giliran, ~2,5 detik |
> | §8.2 `Task.cancel` event | **Sudah ada** — `dispatch.py:62` → `session.py:81` → `loop.py:165` |
> | §8.5 arc progres di orb | **Renderer sudah lengkap** (`orb.py:664-674`); hanya sumber data yang hilang |
>
> **Yang benar-benar masih perlu dibangun jauh lebih sedikit:**
>
> 1. **Antrean batas-giliran** supaya hasil tugas tidak memotong ucapan (§8.4b,
>    N-1) — ini bagian §8 yang paling tepat sasaran.
> 2. **Jalur batal dari suara & UI** (N-2) — rantainya ada, permukaannya tidak.
> 3. **Event progres numerik** di BUS (N-4) — ~30–60 baris, nol di renderer.
> 4. **Batas jumlah tugas** (N-3) — saat ini tidak ada sama sekali.
> 5. **Model data `Task`** (C-2) — ini tetap valid dan tetap dibutuhkan untuk
>    daftar/UI.
>
> Sisanya (§8.2 `TaskRegistry` penuh, §8.3 dispatch baru) **berisiko menduplikasi
> mekanisme yang sudah bekerja.** Jangan dikerjakan sebelum §8 direvisi.
>
> **Catatan FROZEN:** §8.4 menyentuh `main.py`, §8.5 menyentuh `jarvis/ui/orb.py`,
> §8.4d menyentuh `core/prompt.txt` — **ketiganya di manifest FROZEN.**

### 8.1 Prinsip

1. **Lane suara tidak boleh pernah diblokir.** Tugas latar berjalan di thread
   lain; sesi Live tetap mendengar dan menjawab. Selalu.
2. **Setiap tugas punya identitas.** Id, judul, status, progres, hasil. Kalau
   tidak bisa disebutkan namanya, tidak bisa ditampilkan atau dibatalkan.
3. **Konkuren, tapi tidak ceroboh.** Dua agent tidak boleh sama-sama menyetir
   mouse. Sumber daya eksklusif diserialkan, sisanya paralel.
4. **Additive.** Tidak ada refactor `ui.py`/`main.py`. Semua lewat seam yang
   sudah ada: `BUS`, `ContentStage.register()`, `ActionPanel` icons.

### 8.2 Model data — file baru `jarvis/agent/tasks.py`

```python
"""Registry tugas latar. Satu sumber kebenaran untuk UI, suara, dan agent."""

from dataclasses import dataclass, field
from enum import Enum
import threading, time, uuid

class TaskStatus(str, Enum):
    QUEUED    = "queued"      # menunggu slot / resource
    RUNNING   = "running"
    WAITING   = "waiting"     # butuh konfirmasi user
    DONE      = "done"
    FAILED    = "failed"
    CANCELLED = "cancelled"

@dataclass
class Task:
    id: str = field(default_factory=lambda: f"T-{uuid.uuid4().hex[:4]}")
    title: str = ""                    # ringkas, layak diucapkan
    prompt: str = ""                   # perintah asli lengkap
    status: TaskStatus = TaskStatus.QUEUED
    step: str = ""                     # "browser_navigate → tokopedia.com"
    iteration: int = 0
    max_iterations: int = 50
    resources: frozenset = frozenset() # {"desktop"}, {"camera"}, {"browser"}
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: str = ""
    error: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)

    @property
    def progress(self) -> float:        # 0.0–1.0, kasar tapi jujur
        if self.status in (TaskStatus.DONE, TaskStatus.FAILED,
                           TaskStatus.CANCELLED):
            return 1.0
        return min(0.95, self.iteration / max(1, self.max_iterations))

    @property
    def elapsed(self) -> float:
        return (self.finished_at or time.time()) - (self.started_at or time.time())
```

`TaskRegistry` — thread-safe, mem-publish ke `jarvis/core/bus.py`:

```python
class TaskRegistry:
    def __init__(self, bus, max_concurrent=3, queue_max=20):
        self._lock = threading.RLock()
        self._tasks: dict[str, Task] = {}
        self._bus = bus
        self._sem = threading.BoundedSemaphore(max_concurrent)
        self._resource_locks: dict[str, threading.Lock] = {}

    def submit(self, prompt, title=None, resources=frozenset()) -> Task: ...
    def update(self, task_id, **fields) -> None:   # → BUS "task.updated"
    def cancel(self, task_id) -> bool:             # set cancel event
    def active(self) -> list[Task]:                # QUEUED | RUNNING | WAITING
    def snapshot(self) -> list[Task]:              # untuk render UI
```

**Kunci sumber daya (mencegah dua agent berebut mouse):**

```python
EXCLUSIVE = {"desktop", "camera", "browser_context"}
# task read-only (web_search, memory_read, file_read) → resources=frozenset()
#   → jalan paralel penuh
# task yang menyetir pyautogui → resources={"desktop"}
#   → antre, satu per satu
```

Peta tool → resource ditaruh di `jarvis/agent/toolgroups.py` (file yang
sudah direncanakan di PARITY §5.4 — sekalian dibuat sekarang).

### 8.3 Dispatch multi-flight

Ganti single-flight di `jarvis/agent/dispatch.py`:

```python
def dispatch_async(prompt, *, adapter=None, on_ack, on_progress,
                   on_done, on_error) -> Task | None:
    task = REGISTRY.submit(prompt, title=_summarize_title(prompt))
    if task is None:                       # antrean penuh
        return None
    on_ack(f"Baik, saya kerjakan — {task.title}. Silakan lanjut, "
           f"saya laporkan kalau selesai.")
    threading.Thread(target=_run, args=(task,), daemon=True,
                     name=f"agent-{task.id}").start()
    return task                            # ← kembali SEKARANG, bukan nanti
```

Di dalam `jarvis/agent/loop.py`, tambahkan tiga hook (masing-masing ±3 baris):

```python
for i in range(max_iterations):
    if task.cancel.is_set():
        return ToolResult.cancelled()                       # ① batal kooperatif
    REGISTRY.update(task.id, iteration=i, step="berpikir…")  # ② progres
    ...
    for call in tool_calls:
        REGISTRY.update(task.id, step=f"{call.name} → {call.short_args()}")
        if task.cancel.is_set():
            break                                            # ③ batal sebelum tool
```

### 8.4 Membuat Jarvis tetap interaktif — perubahan di `main.py`

Ini bagian yang memperbaiki C-1. Tiga perubahan:

**(a) Cabut gate.** `_native_agent_tool_responses` yang menekan tool-call Live
selama agent bekerja **dihapus**. Sesi Live tetap penuh fungsi. Agent adalah
*konsumen* dari registry, bukan pemilik sesi.

**(b) Antrean batas-giliran, bukan penekanan.** Hasil tugas tidak pernah
diinjeksikan di tengah Jarvis bicara — ia diantre dan di-flush saat
`turn_complete`:

```python
class JarvisLive:
    def __init__(self, ui):
        ...
        self._task_notices: deque[str] = deque()

    def _on_task_finished(self, task: Task):
        """Dipanggil dari thread agent. Tidak pernah menyela."""
        self._task_notices.append(
            f"[TASK_DONE id={task.id}] {task.title}\n{task.result[:1200]}\n"
            f"Sampaikan hasilnya dalam SATU kalimat singkat, lalu langsung "
            f"kembali ke topik yang sedang dibicarakan user."
        )

    async def _on_turn_complete(self):
        while self._task_notices:
            await self.session.send_client_content(
                turns={"parts": [{"text": self._task_notices.popleft()}]},
                turn_complete=True)
```

**(c) Empat tool baru** ditambahkan ke `TOOL_DECLARATIONS` — supaya model bisa
*berbicara tentang* pekerjaan yang sedang berjalan:

```python
{"name": "task_start",  "description":
    "Mulai tugas latar panjang (riset, bangun proyek, otomasi browser). "
    "Kembali SEKETIKA dengan id. WAJIB dipakai untuk apa pun yang >5 detik. "
    "Jangan pernah bilang 'tunggu sebentar' lalu diam.",
 "parameters": {"type":"OBJECT","properties":{
     "task":{"type":"STRING"},"title":{"type":"STRING"}},
     "required":["task"]}},

{"name": "task_status", "description":
    "Daftar tugas yang sedang berjalan + progres. Pakai saat user bertanya "
    "'sudah sampai mana', 'masih lama?', 'lagi ngapain?'.",
 "parameters": {"type":"OBJECT","properties":{"id":{"type":"STRING"}}}},

{"name": "task_cancel", "description": "Batalkan tugas latar.",
 "parameters": {"type":"OBJECT","properties":{"id":{"type":"STRING"}},
                "required":["id"]}},

{"name": "task_result", "description": "Ambil hasil lengkap tugas yang selesai.",
 "parameters": {"type":"OBJECT","properties":{"id":{"type":"STRING"}},
                "required":["id"]}},
```

Keempatnya **non-blocking** (baca dari registry di memori), jadi aman dipanggil
kapan saja tanpa mengganggu latensi suara.

**(d) Aturan di `core/prompt.txt`** (tambahan, tidak mengubah persona):

```
[MULTI-TASKING]
- Apa pun yang butuh lebih dari ~5 detik → task_start, jangan dikerjakan inline.
- Setelah task_start, KONFIRMASI singkat lalu LANJUTKAN percakapan normal.
  Jangan pernah menggantung user dengan "tunggu sebentar" lalu diam.
- Kalau user memberi perintah baru saat ada tugas berjalan: kerjakan yang baru.
  Jangan antre, jangan tolak, jangan minta user menunggu.
- User bertanya "sudah sampai mana" → task_status, jawab dengan progres nyata.
- Tugas selesai di tengah obrolan → sampaikan SATU kalimat, lalu kembali ke
  topik yang sedang dibahas. Jangan bacakan seluruh hasil kecuali diminta.
- Maksimal 3 tugas bersamaan. Yang ke-4 → beri tahu user dan tawarkan antre.
```

### 8.5 UI — tiga lapis visibilitas

```
┌─────────────────────────────────────────────────────────────┐
│  header                                        12:04:31     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│                      ContentStage                           │
│              (Task Deck tampil di sini bila                 │
│               ikon tasks/timeline diklik)                   │
│                                                             │
│                                          ╭──────╮           │
│                                          │ ORB  │ ← docked, │
│                                          │ ◜◝   │   progres │
│                                          ╰──────╯   arc di  │
│                                                     halo    │
│  ┌── MINI STRIP (selalu terlihat, di atas ActionPanel) ──┐  │
│  │ ◐ T-a3 Riset harga GPU        62%  [✕]                │  │
│  │ ◐ T-7f Rapikan folder Unduhan 20%  [✕]                │  │
│  │ ⋯ +1 lagi                                             │  │
│  └───────────────────────────────────────────────────────┘  │
│  [👁][⬆][♫][🏠][◉][◎][🎨][⏱][🧩][💬][⚙][📋←BARU]           │
├─────────────────────────────────────────────────────────────┤
│  > ketik perintah…                                          │
└─────────────────────────────────────────────────────────────┘
```

**Lapis 1 — Mini strip** (`jarvis/ui/task_strip.py`, file baru)
Selalu terlihat saat ada tugas aktif, maksimum 3 chip. Tiap chip: spinner,
id, judul terpotong, persen, tombol ✕. Klik chip → buka Task Deck. Auto-hide
6 detik setelah semua selesai. Tinggi ~26 px, tidak menutupi apa pun.

**Lapis 2 — Task Deck** (`jarvis/ui/task_deck.py`, file baru)
Panel penuh, didaftarkan lewat pola yang **sudah ada**:

```python
stage.register("tasks", TaskDeckPanel(registry, bus))
action_panel.tasks_clicked.connect(lambda: stage.show("tasks"))
```

Isinya: daftar tugas (aktif di atas, selesai di bawah), tiap baris menampilkan
status, judul, langkah saat ini, progress bar, waktu berjalan, tombol
Batal/Lihat Hasil. Klik satu tugas → pane detail dengan jejak langkah lengkap
(dibaca dari `data/logs/tools.jsonl`, difilter per `task_id`).

**Lapis 3 — Orb** ⚠️ **BAGIAN INI PERLU DIPUTUSKAN ULANG (putaran 2)**

> Saran di bawah ditulis dengan asumsi state `EXECUTING` tidak dipakai.
> **Asumsi itu salah.** `jarvis/ui/window.py` sudah men-set `EXECUTING` di
> **tujuh titik produksi** (`:804`, `:851`, `:889`, `:943`, `:964`, `:996`,
> `:1043`), dan `jarvis/ui/orb.py:664-674` **sudah merender progress ring
> lengkap**. Yang hilang **hanya sumber data** — `set_progress()` cuma dipanggil
> dari harness dev (`orb.py:716`), jadi busur selalu 0 %.
>
> Estimasi kerja jadi **jauh lebih kecil**: ~30–60 baris (satu event
> `agent.task.progress` di BUS, satu produsen pecahan dari
> `iterations / max_iter`, satu subscriber di `window.py`) dan **nol baris di
> renderer**. Tapi `jarvis/ui/orb.py` **FROZEN**.
>
> Juga: kunci config `progress_ring` **tidak pernah dibaca kode mana pun**
> (N-5) — rendering digerbang murni oleh `state == EXECUTING`.
>
> **Keputusan Anda diperlukan** — lihat PERTANYAAN #3.

Saran asli putaran 1: jangan pindahkan orb ke `EXECUTING` saat tugas berjalan —
itu akan menghapus sinyal "saya sedang mendengarkan". Sebagai gantinya render
**arc progres** di cincin halo yang sudah ada (`halo_aperture`).

Prioritas state orb: `SPEAKING` > `LISTENING` > `THINKING` > `IDLE`.
Progres tugas = **lapisan tambahan**, bukan state. Ini pembeda penting antara
"Jarvis sibuk" dan "Jarvis tidak tersedia".

### 8.6 Tambahan `config.yaml`

```yaml
agent:
  max_concurrent_tasks: 3        # tugas paralel; >3 mulai berebut CPU/API quota
  queue_max: 20
  exclusive_resources: [desktop, camera, browser_context]
  orphan_policy: report          # report | resume | discard (tugas saat crash)

ui:
  task_deck:
    enabled: true
    mini_strip_max: 3
    mini_strip_height_px: 26
    autohide_after_done_ms: 6000
    progress_arc_in_halo: true   # false → pakai state EXECUTING klasik
    speak_on_complete: true      # false → hanya notifikasi visual
```

### 8.7 Urutan implementasi

| Fase | Isi | Bukti selesai |
|---|---|---|
| **1** | `tasks.py` + `TaskRegistry` + event BUS. Tanpa UI. | Test: 3 submit paralel, 1 cancel, resource lock menahan task `desktop` kedua |
| **2** | Hook progres di `loop.py` + dispatch multi-flight | `task_status` mengembalikan progres nyata yang naik |
| **3** | Cabut gate di `main.py` + antrean batas-giliran + 4 tool baru | **Uji manual: beri tugas 60 detik, lalu tanya "jam berapa sekarang" — Jarvis harus menjawab** |
| **4** | Mini strip + Task Deck + wiring ActionPanel | Tugas terlihat, bisa dibatalkan dari UI |
| **5** | Arc progres di halo orb | |
| **6** | Persistensi tugas yatim saat restart | Kill paksa saat tugas jalan → boot berikutnya melaporkannya |

**Uji penerimaan tunggal** (kalau hanya satu yang diuji, uji ini):

> Katakan *"Jarvis, riset lima laptop terbaik di bawah 15 juta"*. Sementara
> ia bekerja, katakan *"ngomong-ngomong, buka Spotify"*. Spotify harus terbuka
> **seketika**, tanpa menunggu riset selesai, dan chip riset harus tetap
> terlihat dengan progres yang bergerak.

---

## 9. Roadmap Lain (di luar Task Deck)

> **DIURUTKAN ULANG setelah putaran 2.** Prioritas 1 lama (sanitasi kosmetik)
> turun; keamanan naik ke puncak.

### Prioritas 0 — KEAMANAN (jam, bukan hari) 🔴 BARU

Empat perbaikan, semuanya kecil, semuanya di luar zona FROZEN:

1. `jarvis/agent/tools/code_exec.py` — tambahkan `requires_confirmation = True`
   (**1 baris**, menutup rantai KRITIS S1)
2. `jarvis/agent/tools/file_ops.py:161`, `:214` — panggil `_inside_sandbox(root)`
   di `FileSearch.run` dan `FileList.run` (**2 baris**, menutup S2)
3. `jarvis/agent/registry.py:143-145` — ubah fallback jadi `needs = True`
   (**1 baris**, mengubah kontrol keamanan gagal-terbuka jadi gagal-tertutup)
4. `actions/open_app.py:82`, `:96` — validasi `app_name` atau buang `shell=True`
   (menutup dua jalur command injection S3)

Menyusul: hapus `dashboard/server.py:103-311` `_ensure_network_access()` (kode
mati yang meminta UAC dan menurunkan Public→Private), dan tambahkan rate limit
di `/auto-login` (`server.py:550`, **1 baris**).

### Prioritas 1 — sanitasi (1–2 hari)
- Hapus berkas yang **sudah diverifikasi** di §7.6 — termasuk dua relik MARK XL
  (`core/llm_client.py`, `core/installer.py`) dan tiga `.bak`
- ⚠️ **JANGAN** hapus `core/social_*.py` — klaim §7.3 lama salah
- Pindahkan 6 dokumen ke `docs/` (§7.2)
- Hapus 6 field rahasia plaintext dari `config.yaml` (H-4 — masih berlaku,
  `config.yaml` masih ter-track git)
- Rename `setup.py` → `scripts/first_run_wizard.py` (M-1)
- Perbaiki `baseline_commit` di `config/frozen_manifest.json` (N-7)
- `git commit` per langkah — mulai punya riwayat

### Prioritas 2 — memori terpadu (H-1b) 🔴 naik dari Prioritas 3

Ini bug fungsional yang Anda rasakan setiap hari: fakta yang Anda ucapkan tidak
terlihat agent. Perbaikan minimalnya kecil (lampiran §2i) tetapi **menyentuh
`main.py` yang FROZEN** — butuh izin Anda dulu.

### Prioritas 3 — Task Deck (§8 **setelah direvisi**)

Baca kotak peringatan di awal §8. Cakupannya kini jauh lebih kecil: antrean
batas-giliran (N-1), permukaan batal (N-2), event progres (N-4), batas jumlah
tugas (N-3), model data `Task` (C-2).

### Prioritas 4 — konsolidasi (1–2 minggu)
- ⚠️ **Pensiunkan `actions/` jauh lebih mahal dari dugaan** — MK50 sendiri
  bergantung padanya di 5 titik, dan 8 modul tak punya padanan. Butuh
  reimplementasi dulu, bukan sekadar penghapusan
- **Satukan lease desktop** (N-15) — jalur legacy harus lewat `DESKTOP` juga
- Pensiunkan jalur Hermes **secara bertahap** dalam urutan di lampiran §5f —
  bukan satu penghapusan
- `pyproject.toml` + `.github/workflows/ci.yml` (lint + pytest + `verify_frozen`)
- Tes untuk `cancel_all()` (N-6) — jalur yang saat ini nol cakupan

### Prioritas 4 — "lebih seperti di film"
- **Nyalakan `awareness`** (`awareness.enabled: true`) dan sambungkan ke
  `ProactiveEngine`. Fondasinya sudah ada — privasi denylist, retensi,
  adaptive sampling. Ini yang mengubah Jarvis dari reaktif menjadi hadir.
- **Perluas pemicu proaktif** dari sekadar "diam 15 menit" menjadi kombinasi
  sinyal: CPU tinggi berkepanjangan, error di terminal yang terlihat,
  jam kerja biasa, cron yang akan jatuh tempo.
- **Nada adaptif di `core/prompt.txt`**: ringkas & tegas saat sistem kritis
  atau tugas gagal; santai saat obrolan biasa. Persis perbedaan nada JARVIS
  di lab vs saat Tony dalam bahaya.
- **Fallback model lokal** (Ollama/LM Studio) untuk perintah dasar saat offline.
  `routing.fallback` sudah menyebut `local` — tinggal diisi.

---

## 10. Checklist Verifikasi

```
SANITASI
[ ] mw.txt & patch_ui.py terhapus
[ ] scripts/audit_dead_code.sh bersih untuk path absolut hardcoded
[ ] Tidak ada field rahasia plaintext di file yang di-track git
[ ] Root hanya berisi README.md, AUDIT_REPORT.md, LICENSE + kode
[ ] python -m jarvis.main tetap boot normal setelah semua penghapusan
[ ] Suara Jarvis identik (voice Charon, core/prompt.txt tak berubah kecuali §8.4d)

TASK DECK
[ ] 3 tugas berjalan bersamaan tanpa saling merusak
[ ] Dua tugas ber-resource "desktop" TIDAK pernah jalan bersamaan
[ ] Perintah baru saat tugas berjalan → dijawab seketika  ← UJI UTAMA
[ ] task_status mengembalikan progres yang bergerak, bukan angka statis
[ ] Batal dari UI menghentikan tugas dalam <2 detik
[ ] Tugas selesai saat Jarvis bicara → notice diantre, tidak menyela
[ ] Kill paksa saat tugas jalan → boot berikutnya melaporkan tugas yatim
[ ] Orb tetap menampilkan LISTENING saat tugas berjalan
```

---

## 11. Catatan Lisensi

Repo ini turunan dari **Mark XLVIII © FatihMakes**, lisensi
**CC BY-NC 4.0** (atribusi, non-komersial). Kewajiban yang harus dipertahankan:

- Kredit ke FatihMakes tetap ada di README (sudah dilakukan di README baru)
- Tidak boleh dipakai komersial
- Karya turunan mewarisi lisensi yang sama

Nama "J.A.R.V.I.S" dan estetika arc-reactor berasal dari properti Marvel/Disney.
Untuk proyek personal ini tidak bermasalah; jangan dipublikasikan sebagai produk.

---

## 12. PERTANYAAN UNTUK USER

Hal-hal yang **tidak bisa saya putuskan sendiri**. Saya tidak menebak.

### 1. Zona FROZEN — tiga perbaikan penting menyentuhnya 🔴

Manifest melindungi 10 berkas, dan **verifikasi lolos** (`OK, 10 files`). Tapi
tiga perbaikan yang paling bernilai jatuh di dalamnya:

| Perbaikan | Berkas FROZEN | Kenapa perlu |
|---|---|---|
| Jembatan memori (H-1b) | `main.py` | Fakta suara tak terlihat agent |
| Antrean batas-giliran (N-1) | `main.py` | Hasil tugas memotong ucapan |
| Sumber data progress ring (N-4) | `jarvis/ui/orb.py` | Busur selalu 0 % |
| Section `[MULTI-TASKING]` (§8.4d) | `core/prompt.txt` | Aturan multi-tasking |

**Pertanyaan:** apakah Anda mengizinkan menyentuh berkas FROZEN ini — dan kalau
ya, apakah saya juga me-*rebaseline* `config/frozen_manifest.json`, atau Anda
yang melakukannya? Kalau tidak diizinkan, saya perlu tahu supaya bisa mencari
jalur aditif di luar berkas itu (mungkin ada, tapi lebih berbelit).

### 2. Prioritas keamanan — kerjakan sekarang atau tunggu?

S1 (`execute_code` tanpa konfirmasi) adalah temuan paling serius di repo, dan
perbaikannya **satu baris di luar zona FROZEN**. Bersama S2 dan fail-open
`registry.py`, totalnya **4 baris**.

**Pertanyaan:** mau saya kerjakan Prioritas 0 lebih dulu sebagai fase terpisah,
atau Anda ingin menyelesaikan sesuatu yang lain dulu?

Catatan jujur: `requires_confirmation = True` pada `execute_code` **akan
menambah prompt konfirmasi** saat agent menulis kode. Itu trade-off nyata pada
kenyamanan — Anda yang berhak memutuskan.

### 3. Orb `EXECUTING` — dua desain saling bertentangan

`AUDIT_REPORT.md §8.5` (putaran 1) menyarankan **jangan** memakai state
`EXECUTING` untuk tugas berjalan. Tetapi `jarvis/ui/window.py` **sudah**
memakainya di tujuh tempat, dan renderer-nya sudah lengkap.

**Pertanyaan:** mana yang benar menurut Anda —
(a) sambungkan data ke `EXECUTING` yang sudah ada (murah, ~30–60 baris, tapi
menyentuh `orb.py` FROZEN), atau
(b) ikuti saran §8.5 dan render arc di halo sebagai lapisan terpisah (lebih
mahal, tapi orb tetap menunjukkan LISTENING saat tugas berjalan)?

Saya condong ke **(b)** karena alasan §8.5 masih valid — Anda ingin tahu Jarvis
masih mendengarkan. Tapi ini murni keputusan produk.

### 4. `hermes-agent-main/` — 151 MB di working tree

Gitignored, jadi tidak masuk riwayat, tapi setiap clone/checkout membawanya dan
setiap pencarian tanpa scope menyentuhnya.

**Pertanyaan:** dipindahkan ke luar repo (mis. `../hermes-reference/`), atau
Anda masih memerlukannya di tempat sekarang?

### 5. Dua modul "dibangun tapi belum disambung"

`jarvis/core/notify_hub.py` (191 baris) dan
`jarvis/integrations/youtube_capability.py` (111 baris) **nol referensi**, tapi
keduanya jelas pekerjaan yang disengaja — yang kedua bahkan berisi invarian
keamanan.

**Pertanyaan:** ini fitur yang ditinggalkan (hapus), atau tahap berikutnya yang
belum sempat disambung (pertahankan)? Sama untuk 17 modul lain yang importer
tunggalnya adalah tes — termasuk `plugins/*` dan `gateway/platforms/*`.

### 6. Mode LAN dashboard tidak berfungsi

Karena `_mutation_allowed()` mengembalikan `False` untuk seluruh mode LAN,
`/login` dan `/api/device-login` sama-sama 403 — **tidak ada cara memperoleh
token di mode LAN**, sehingga setiap rute ter-autentikasi tak terjangkau.

**Pertanyaan:** mode LAN memang tidak dipakai (kalau begitu sebaiknya dihapus
supaya tidak ada yang "memperbaikinya" dengan melonggarkan `_mutation_allowed`
— yang justru akan memapar `/api/command` ke jaringan), atau Anda memang ingin
memakainya dan ini perlu diperbaiki dengan benar?

### 7. `core/tts.py` dan `core/voice_listener.py` — FROZEN tapi mati saat runtime

Keduanya hanya terjangkau lewat `MainWindow` di `ui.py`, yang **tidak pernah
diinstansiasi** di jalur `python -m jarvis.main`. Suara Jarvis datang dari
Gemini Live (`_play_audio`), bukan dari `core/tts.py`.

**Saya tidak menyentuhnya** — aturan Anda jelas soal pipeline suara. Tapi Anda
perlu tahu bahwa dua berkas yang dilindungi manifest ini sebenarnya tidak
dieksekusi di boot normal.

**Pertanyaan:** apakah ini disengaja (cadangan bila Gemini Live mati), atau
peninggalan yang sebaiknya dicatat sebagai tidak-aktif?

---

*Audit putaran 2 oleh Claude · 2026-07-27 · clone lokal, pembacaan kode langsung*
*Bukti kode lengkap: [`docs/AUDIT_FINDINGS_CODE.md`](docs/AUDIT_FINDINGS_CODE.md)*
*Tidak ada berkas kode yang diubah selama audit ini.*