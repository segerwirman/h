# Tutorial dan Audit Repo `mk50hybrid`

> Audit dilakukan pada 17 Juli 2026, branch `main`, commit `a61af5f`.
> Dokumen ini menjelaskan arsitektur, fitur, workflow, cara menjalankan, risiko keamanan, dan saran perbaikan. Source code tidak diubah.

## 1. Ringkasan eksekutif

`mk50hybrid` adalah asisten desktop JARVIS berbasis Python dan PyQt6. Aplikasi menggabungkan percakapan suara real-time Gemini Live, antarmuka desktop, browser tertanam, vision/camera, kontrol komputer, memori persisten, agent multi-tool, Telegram, cron, Relay.app, dashboard ponsel, serta bridge opsional ke Hermes Agent.

Repo ini merupakan sistem hibrida karena dua generasi implementasi masih berjalan bersama:

- Jalur legacy Mark XLVIII berada di `main.py`, `ui.py`, `core/`, `actions/`, dan `memory/`. `main.py` menangani audio Gemini Live dan mengeksekusi 22 deklarasi tool legacy.
- Jalur baru Mark XLIX/MK50 berada di paket `jarvis/`. Entry point resminya `python -m jarvis.main`; UI aktif ada di `jarvis/ui/window.py`, sedangkan agent native ada di `jarvis/agent/`.
- `jarvis/main.py` tetap mengimpor `JarvisLive` dari `main.py` di thread terpisah. Artinya, kode legacy bukan sekadar arsip: ia masih menjadi mesin suara utama.

Kesimpulan keamanan:

- Tidak ditemukan bukti bahwa repo ini sengaja dibuat sebagai spyware, malware, backdoor, cryptominer, ransomware, atau pencuri kredensial.
- Tidak ditemukan domain command-and-control yang mencurigakan, payload executable tersembunyi, obfuscation berat, keylogger, maupun kode yang diam-diam mengirim semua file/kredensial ke server asing.
- Pemindaian Microsoft Defender terhadap seluruh workspace selesai dengan hasil `found no threats`. Pemindaian memakai `-DisableRemediation`, sehingga tidak menghapus atau mengarantina apa pun.
- Walau bukan malware, aplikasi mempunyai kemampuan setara remote-administration tool: mendengar mikrofon, membaca kamera/layar, mengontrol mouse dan keyboard, menjalankan shell/kode, mengatur scheduler, membaca file, dan menerima perintah jarak jauh. Beberapa guardrail belum cukup kuat. Risiko operasional saat ini dinilai **tinggi** bila aplikasi dijalankan dengan semua integrasi aktif.

Jadi, jawaban yang paling akurat adalah: **tidak ada indikator malware yang ditemukan, tetapi repo belum layak dianggap aman untuk dijalankan dengan hak penuh pada komputer utama atau jaringan yang tidak dipercaya.**

## 2. Ruang lingkup dan metode audit

### 2.1 Cakupan

Audit manual mencakup 249 file yang dilacak Git:

| Kelompok | Jumlah |
|---|---:|
| File Python | 223 |
| Python produksi | 185 file / 41.781 baris |
| Python test | 38 file / 6.198 baris |
| Total Python | 47.979 baris |

Folder `hermes-agent-main/`, database, log, secrets lokal, cache, serta bobot model diabaikan Git. Folder Hermes diperlakukan sebagai repo referensi, bukan source utama JARVIS. Defender tetap memindai seluruh workspace, termasuk file yang diabaikan Git, tetapi source Hermes tidak diaudit manual baris demi baris dalam dokumen ini.

### 2.2 Pemeriksaan yang dilakukan

- Memetakan entry point, struktur modul, jalur boot, routing, tool registry, penyimpanan, dan integrasi.
- Menelusuri penggunaan `subprocess`, `shell=True`, `exec`, download, scheduler, firewall, registry, file deletion, kamera, mikrofon, screenshot, clipboard, token, dan endpoint jaringan.
- Memeriksa guardrail konfirmasi, sandbox path, timeout, whitelist Telegram, autentikasi webhook, dan redaksi log.
- Menginventarisasi file biner dan domain hardcoded.
- Memeriksa keberadaan secrets lokal tanpa mencetak nilainya.
- Menjalankan Microsoft Defender custom scan non-remediasi pada seluruh workspace.

### 2.3 Batasan

- Ini terutama audit statis. Tidak dilakukan packet capture atau pengujian penetrasi aktif terhadap dashboard.
- Kesegaran signature Defender tidak dapat dibaca karena `Get-MpComputerStatus` ditolak oleh permission sistem, walaupun proses scan sendiri berhasil.
- Hash aset lokal dicatat, tetapi provenance bobot model `.pt`/`.onnx` tidak dapat dibuktikan tanpa membandingkannya dengan sumber resmi.
- Dependency tidak diunduh atau diinstal ulang, sehingga paket PyPI aktual belum diaudit supply-chain-nya.
- Test suite tidak dijalankan karena interpreter Python yang ditemukan pada mesin audit menunjuk ke runtime yang tidak tersedia. Pemeriksaan source dan Defender tetap selesai.
- Hasil “tidak ditemukan malware” bukan bukti matematis bahwa tidak ada risiko; ia berarti tidak ada indikator malicious intent yang terlihat dalam scope pemeriksaan ini.

## 3. Arsitektur repo

### 3.1 Peta direktori

| Path | Fungsi |
|---|---|
| `jarvis/main.py` | Entry point Mark XLIX; membangun UI, NLP, vision, wake trigger, Relay, Telegram, cron, dan thread voice legacy. |
| `main.py` | Pipeline Gemini Live legacy: capture/play audio, tool calling, dashboard LAN, proactive mode, monitor sistem, reconnect. |
| `jarvis/ui/` | UI PyQt6 baru: window, orb, stage, panels, overlay, settings, timeline, command palette. |
| `ui.py` | UI legacy. Masih diimpor oleh `main.py` untuk run legacy langsung, tetapi bukan UI utama saat memakai `python -m jarvis.main`. |
| `jarvis/core/` | Config, event bus, boot check, router, state machine, logging, memory, awareness, health, focus mode, target resolver. |
| `jarvis/agent/` | Agent loop native, provider LLM, registry tool, session, memory, skills, cron, adapters UI/Telegram, MCP. |
| `jarvis/agent/tools/` | 67 tool yang ditemukan otomatis; jumlah runtime dapat berkurang bila dependency/kredensial tidak tersedia. |
| `jarvis/nlp/` | Chatbot, sentiment, terjemahan, ringkasan, dokumen, search, email, social monitoring, predictive text. |
| `jarvis/browser/` | Browser QtWebEngine, agent-browser CLI, Tabbit embed, DOM extraction, reply flow, dan skill browser. |
| `jarvis/vision/` | Process kamera terisolasi, YOLO, MediaPipe gesture, transform koordinat, device backend, food calories. |
| `jarvis/integrations/` | Hermes, Relay.app, OpenAI OAuth, YouTube, Instagram, Facebook, X, dan live comments. |
| `actions/` | Tool legacy untuk file, desktop, browser, pesan, reminder, game, web, YouTube, code helper, dan developer agent. |
| `dashboard/` | FastAPI dashboard LAN untuk ponsel: command, WebSocket, mic, file upload/download. |
| `core/` | STT/TTS, installer dependency, vision lama, prompt, dan client LLM lama. |
| `memory/` | Memori key-value legacy dan config API key. |
| `tests/` | 38 file test untuk agent, browser, vision, UI, Relay, OAuth, memory, cron, skills, dan settings. |
| `config.yaml` | Sumber konfigurasi utama, termasuk UI, router, vision, agent, integrasi, dan privacy settings. |

### 3.2 Entry point

Entry point yang direkomendasikan source adalah:

```powershell
python -m jarvis.main
```

Mode yang tersedia:

```powershell
# UI/NLP tanpa Gemini Live, dan tanpa dashboard legacy
python -m jarvis.main --no-voice

# Harness pengujian visual orb
python -m jarvis.main --orb-test

# Jalur legacy langsung; bukan pilihan utama untuk Mark XLIX
python main.py
```

Catatan konsistensi dokumentasi:

- `readme.md` masih menyebut Mark XLVIII.
- ~~`setup.py` mencetak Mark XXV dan hanya menginstal `requirements.txt`.~~
  **Sudah diperbaiki:** dipindah ke `scripts/first_run_wizard.py` (nama
  `setup.py` direservasi setuptools), kini memasang **kedua** requirements dan
  menyebut entry point yang benar `python -m jarvis.main`.
- Entry point resmi di source adalah Mark XLIX.
- Untuk instalasi lengkap, `requirements.txt` dan `requirements-xlix.txt` sama-sama dibutuhkan, tetapi keduanya belum mencantumkan seluruh import runtime.

## 4. Cara instalasi dan penggunaan

### 4.1 Prasyarat

- Python 3.11 atau 3.12.
- Windows 10/11, macOS, atau Linux. Beberapa fitur paling lengkap di Windows.
- Mikrofon dan speaker untuk mode suara.
- Webcam untuk vision/gesture.
- Gemini API key untuk voice legacy dan banyak fitur default.
- Koneksi internet untuk provider LLM, web search, Spotify, Google/YouTube, Meta, Relay, atau Telegram.

### 4.2 Instalasi dasar

Buat virtual environment terpisah agar dependency agent tidak bercampur dengan Python sistem:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-xlix.txt
python -m playwright install chromium
```

Manifest dependency saat ini belum lengkap. Berdasarkan import source, fitur tertentu juga membutuhkan paket seperti `pydantic`, `croniter`, `ddgs`, `python-telegram-bot`, `openai`, `anthropic`, `google-auth`, `google-api-python-client`, `keyring`, atau paket opsional media/STT/TTS. Jangan memasang paket yang hilang secara acak pada komputer produksi; sebaiknya maintainer menyusun lockfile terverifikasi terlebih dahulu.

### 4.3 Konfigurasi secrets

Repo memuat `.env` secara otomatis dari root. Gunakan `.env.example` sebagai daftar nama variabel, jangan menyalin nilai dari mesin lain. Variabel utama meliputi:

- `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`.
- `TG_BOT_TOKEN`, `TG_ALLOWED_IDS`, `TG_NOTIFY_CHAT_ID`.
- `HA_URL`, `HA_TOKEN`.
- `SPOTIFY_CLIENT_ID`, `SPOTIFY_REDIRECT_URI`.
- `RELAY_ENABLED`, `RELAY_WEBHOOK_SECRET`, `RELAY_WEBHOOK_HOST`, dan opsi Relay lainnya.
- `JARVIS_IMAP_HOST`, `JARVIS_IMAP_USER`, `JARVIS_IMAP_PASSWORD`.

Gemini legacy juga membaca `config/api_keys.json`. UI Settings dapat menulis `config/providers.json`. File-file tersebut diabaikan Git, tetapi tetap plaintext di disk; bagian keamanan menjelaskan risikonya.

### 4.4 Urutan start yang paling aman

1. Jalankan dahulu `python -m jarvis.main --no-voice`.
2. Periksa panel Settings dan Capabilities.
3. Biarkan `awareness.enabled: false`, `relay.enabled: false`, MCP kosong, dan Telegram tanpa token sampai benar-benar diperlukan.
4. Nonaktifkan tool group berbahaya untuk sesi agent baru:

```yaml
tools:
  disabled_groups:
    - terminal_processes
    - code_execution
    - computer_use
    - cron_jobs
    - home_assistant
    - mcp
```

5. Perlu diingat: toggle tersebut hanya menyaring tool agent native. Ia tidak mematikan action legacy yang dipanggil oleh Gemini Live di `main.py`.
6. Aktifkan full voice hanya setelah memahami bahwa audio mikrofon akan dikirim ke Gemini Live selama sesi aktif dan dashboard LAN legacy ikut dimulai.

### 4.5 Hotkey UI

| Hotkey | Fungsi |
|---|---|
| `F1` | System statistics overlay |
| `F2` | Activity log |
| `F3` | File upload/drop |
| `F4` | Mute/unmute mikrofon |
| `F5` | Context timeline |
| `F6` | Vision panel |
| `F7` | Focus mode |
| `F8` | Arm/disarm gesture control |
| `F9` | Command palette |
| `F11` | Fullscreen |
| `Escape` | Interrupt respons suara |

## 5. Workflow aplikasi

### 5.1 Boot workflow

```text
python -m jarvis.main
  -> load config.yaml + .env + structured logging
  -> register modul NLP
  -> start VisionSystem (opsional, process terpisah)
  -> bangun MainWindow PyQt6 + ContentStage + orb + panels
  -> start double-clap wake detector
  -> start Relay bila enabled
  -> start Telegram bila token + whitelist tersedia
  -> start CronScheduler
  -> BootSequence mengecek LLM/STT/TTS/vision/gesture/browser/system/Hermes
  -> bila bukan --no-voice: start JarvisLive legacy di thread daemon
  -> Qt event loop
```

Setiap subsystem dirancang degrade gracefully: import atau credential yang hilang semestinya menonaktifkan fitur terkait tanpa menjatuhkan UI.

### 5.2 Workflow perintah teks

```text
CommandBar
  -> MainWindow.handle_command()
  -> IntentRouter rules/regex
     -> SEARCH_WEB: browser internal + ekstraksi + streaming summary
     -> OPEN_URL: ContentStage browser
     -> OPEN_BROWSER_AGENT: Chromium internal atau Tabbit eksplisit
     -> OPEN_APP: actions.open_app
     -> SYSTEM: actions.computer_settings / vision / focus / target resolver
     -> HERMES_TASK: agent native; Hermes CLI menjadi fallback
     -> CHAT: Gemini Live hook bila aktif, SmartAssistant bila --no-voice
```

Router memakai fast-path regex. Fallback LLM hanya dipakai untuk perintah ambigu. Search, URL, system action, dan tugas berat dipisahkan sebelum percakapan bebas.

### 5.3 Workflow suara real-time

```text
sounddevice microphone (16 kHz PCM)
  -> Gemini Live session
  -> model mengirim audio/transcript atau function call
  -> JarvisLive._execute_tool()
  -> action legacy di actions/
  -> hasil tool dikirim kembali ke Gemini
  -> Gemini menghasilkan audio 24 kHz
  -> queue playback -> speaker + transcript/UI
```

Pipeline mempunyai queue, timeout tool, response watchdog, interrupt/barge-in, reconnect dengan backoff, state machine, monitor hardware, proactive check-in, dan vision cooldown. Saat full voice aktif, dashboard FastAPI legacy juga dimulai.

### 5.4 Workflow agent native

```text
tugas berat / Telegram / cron
  -> dispatch_async() + ACK instan
  -> Session dibuat dan diarsipkan ke data/agent.sqlite
  -> system prompt = persona + memory + skill metadata + OS/waktu
  -> provider LLM memilih satu atau beberapa tool
  -> registry memvalidasi nama, konfirmasi, timeout, dan logging
  -> tool read-only dapat berjalan paralel; tool penulis serial
  -> hasil kembali ke LLM
  -> loop sampai jawaban final / max_iterations / timeout / cancel
  -> refleksi dan curator skill berjalan di background
```

Provider agent dapat berupa Gemini, OpenAI-compatible, Anthropic, local server, atau custom endpoint. Tool ditemukan otomatis dari `jarvis/agent/tools/`.

### 5.5 Workflow vision dan gesture

```text
camera process
  -> canonical coordinate transform
  -> YOLO object detection + ByteTrack
  -> MediaPipe hand landmarks
  -> GestureRecognizer
  -> frame/event queues
  -> UI VisionPanel + EventBus
```

Kontrol cursor hanya aktif setelah gesture di-arm. `pyautogui.FAILSAFE` aktif, dan palm-hold tiga detik menjadi emergency stop. Screen awareness terpisah dan default-nya `false`; bila aktif ia mengambil snapshot adaptif saat window/scene berubah, dengan denylist title dan retention cap.

### 5.6 Workflow browser

Ada tiga jalur browser:

1. `EmbeddedBrowser`: QtWebEngine di ContentStage untuk navigasi/search/summarization normal.
2. `BrowserAgentView` dan tool Playwright: Chromium agent untuk snapshot DOM, click, type, JavaScript, dan CDP.
3. Tabbit: aplikasi Chromium eksternal yang window-nya direparent ke ContentStage di Windows, kemudian dikendalikan melalui `agent-browser` dan CDP localhost. Aksi sukses dapat disimpan sebagai skill per domain.

Reply flow browser memakai state `IDLE -> COMPOSING -> CONFIRM -> SEND`. Pengiriman balasan dari flow ini membutuhkan konfirmasi `ya/kirim`.

### 5.7 Workflow upload dokumen/gambar

- PDF/DOCX/TXT/MD/CSV diekstrak secara lokal, lalu teksnya diringkas oleh LLM.
- File code dapat dibaca dengan nomor baris untuk tanya-jawab grounded.
- Gambar ditampilkan lokal, lalu byte gambar dikirim ke Gemini vision untuk deskripsi.
- Tool legacy `file_processor` juga menangani image, PDF, dokumen, data, JSON, code, audio, video, archive, dan PPTX.

Artinya, isi dokumen atau gambar yang diminta untuk diringkas/dianalisis dapat meninggalkan mesin menuju provider LLM.

### 5.8 Workflow remote

**Dashboard ponsel**

```text
FastAPI 0.0.0.0:8000
  -> pairing PIN/QR
  -> bearer token + session key
  -> REST/WebSocket command
  -> queue ke Gemini Live
  -> phone mic PCM ke Gemini Live
  -> upload/download file
```

**Telegram**

- Hanya aktif bila bot token dan `TG_ALLOWED_IDS` terisi.
- Semua handler memeriksa numeric user ID whitelist.
- Mendukung task bebas, status, stop, todo, memory search, cron, screenshot, skills, session, dan voice note.

**Relay.app**

- Default nonaktif dan bind ke `127.0.0.1`.
- Webhook tidak start tanpa shared secret.
- Mendukung constant-time token/HMAC verification, replay window, payload limit, dedup event ID, dan SQLite store.
- Jalur agent saat ini read-only; trigger mutation belum diaktifkan.

## 6. Fitur dan fungsi rinci

### 6.1 UI dan pengalaman pengguna

- Header status dan jam.
- Orb animasi dengan state booting, idle, listening, thinking, speaking, executing, muted.
- ContentStage untuk browser, vision, hasil konten, capabilities, messaging, dan settings.
- Bottom action panel untuk vision, upload, Spotify, awareness, focus, palette, timeline, capabilities, messaging, dan settings.
- System stats, activity log, file drop, notification stack, timeline, focus mode, command palette, dan provider settings.
- Predictive command completion dari history lokal.
- Target resolver untuk menutup window bernama dengan confidence, revalidation, dan audit log.
- Multi-monitor awareness serta normalisasi window controls.

### 6.2 Voice, audio, dan wake

- Gemini Live native audio streaming dengan voice `Charon`.
- Input/output transcript.
- Interrupt via Escape/button dan barge-in berdasarkan level mikrofon.
- Double-clap wake detector dengan calibration, spectral/transient filtering, debounce, dan cooldown.
- TTS alternatif di `core/tts.py`: Edge TTS, Kokoro, ElevenLabs.
- STT alternatif: Whisper dan Vosk.
- Reconnect exponential backoff dan timeout per tahap.

### 6.3 NLP

- Chatbot dengan rolling context.
- Sentiment lexicon Indonesia/Inggris untuk adaptasi nada.
- Terjemahan 12 bahasa.
- Ringkasan teks, halaman, dokumen, dan activity log.
- Analisis dokumen dengan chunk/retrieval serta citation markers.
- Online search.
- Predictive text.
- Email IMAP read-only/classification untuk urgent, promo, dan spam.
- Social RSS polling dengan backoff.
- Browser NLP module berbasis accessibility tree.
- Hermes-style mini agent lama, selain agent native yang lebih lengkap.

### 6.4 Agent dan 67 tool native

Tool dikelompokkan menjadi 19 capability groups:

| Grup | Tool utama |
|---|---|
| File Operations | `file_read`, `file_write`, `file_patch`, `file_search`, `file_list` |
| Terminal & Processes | `terminal`, `process_list`, `process_kill`, `process_spawn` |
| Browser Automation | navigate, snapshot, click, type, press, scroll, back, screenshot, images, console JS, dialog, raw CDP |
| Computer Use | screenshot, click, type, key, scroll, drag |
| Skills | list, view, create/update/delete |
| Web | DuckDuckGo search/news dan content extraction |
| Task Planning | todo read/write |
| Clarifying | pertanyaan interaktif ke user |
| Session Search | pencarian percakapan lama |
| Code Execution | Python, Node, Bash, PowerShell |
| Vision | analisis gambar melalui provider vision |
| Memory | write, search, update, forget |
| Delegation | sub-agent internal |
| Cron | create, list, update, pause, resume, run, delete |
| Home Assistant | list entity, state, call service |
| Image Generation | Gemini/OpenAI-compatible/OpenAI OAuth |
| Spotify | search, playback, volume, now playing, playlist, library |
| Food | analisis kalori dan makro dari foto |
| MCP | list server dan panggil tool MCP eksternal |

Tool yang membutuhkan credential memiliki availability gate dan tidak masuk registry bila belum siap.

### 6.5 Memory, session, dan skills

- Agent memory: episodic, semantic, procedural, reflective di `data/agent.sqlite`, dengan FTS5 dan embedding opsional.
- Session transcript dan hasil agent di database yang sama.
- Memory layer UI lama: episodic SQLite, semantic FAISS opsional, working memory, procedural macros.
- Legacy memory: JSON key-value untuk preference/context voice.
- Skills berupa `SKILL.md` dengan frontmatter; metadata masuk prompt, body dimuat saat dibutuhkan.
- Usage counter dan provenance “learned” disimpan sidecar JSON.
- Curator menandai skill agent sebagai stale dan memindahkannya ke archive; tidak menghapus permanen.
- Tabbit mempunyai skill memory terpisah per domain dengan dedup dan cap.

### 6.6 System, file, dan developer automation

- Buka aplikasi lintas OS.
- Volume, brightness, Wi-Fi, window/tab, desktop, lock, shutdown/restart.
- Mouse, keyboard, hotkey, clipboard, screenshot, dan screen element search.
- CRUD file/folder, trash, move/copy/rename, search, organize desktop.
- Set/download wallpaper.
- Code helper untuk write/edit/explain/run/optimize/debug.
- Developer agent untuk membuat project, memasang dependency, menjalankan, memperbaiki error, dan membuka VS Code.
- Game updater Steam/Epic, install/update/status, scheduler harian, serta shutdown setelah download.
- Reminder via Task Scheduler, LaunchAgent, systemd-run, atau `at`.
- Document/media processor dan flight finder.

### 6.7 Web, media, dan integrasi

- Search/news/research/price/compare melalui Gemini Grounding dan DuckDuckGo legacy.
- YouTube search, playback, transcript, summary, info, trending.
- Weather dan Google Flights.
- Spotify OAuth PKCE dan Web API.
- YouTube API key/OAuth untuk comments/live chat.
- Instagram/Facebook Graph API adapters.
- X adapter yang jujur terhadap keterbatasan public API.
- OpenAI/Codex device OAuth untuk image generation.
- Home Assistant REST.
- Hermes CLI bridge untuk messaging dan task ecosystem eksternal.
- MCP stdio servers yang dikonfigurasi user.

### 6.8 Observability dan reliability

- Structured logging ke file dan activity panel.
- EventBus thread-safe dengan marshal ke Qt UI thread.
- Voice pipeline state machine dan timeout recovery.
- Circuit breaker untuk layanan eksternal.
- Health checks dan boot checks.
- Tool call log dengan durasi dan status.
- Dedup task aktif, bounded queues, retries, backoff, dan graceful degradation.

## 7. Data, secrets, dan tujuan jaringan

### 7.1 Penyimpanan lokal

| Data | Lokasi |
|---|---|
| Konfigurasi | `config.yaml` |
| Gemini legacy key | `config/api_keys.json` |
| Provider settings dan API key | `config/providers.json` |
| Environment secrets | `.env` |
| YouTube OAuth | keyring dan `config/youtube_oauth.json` |
| Spotify tokens | `data/spotify_tokens.json` |
| Agent memory/session/cron | `data/agent.sqlite` |
| Tool logs | `data/logs/tools.jsonl` |
| UI memory | `memory.sqlite` dan optional index |
| Relay events | `relay_events.sqlite` |
| Browser session | `config/browser_session.json` |
| Command history | `config/command_history.json` |
| Screenshots/hasil generated | `data/generated/` dan `logs/screenshots/` |

Pada mesin audit terdapat API key dan OAuth token aktif dalam file lokal yang diabaikan Git. Nilainya tidak dibaca ke laporan. Ini bukan bukti pencurian, tetapi merupakan exposure bila folder disalin, dibackup tanpa enkripsi, atau dibaca malware lain.

### 7.2 Data yang dapat keluar dari mesin

| Data | Tujuan yang sah dalam desain |
|---|---|
| Audio mikrofon dan transcript | Gemini Live/Google |
| Screenshot, webcam, gambar makanan | Gemini atau provider vision aktif |
| Isi prompt, chat, memory yang diambil | Gemini/OpenAI/Anthropic/custom provider |
| Teks dokumen yang diringkas | Provider LLM |
| Query web | DuckDuckGo/Bing/Google atau URL target |
| Spotify library/playback | Spotify API |
| Kalender/YouTube/email | Google APIs dan IMAP server yang dikonfigurasi |
| Comment/reply | Google/YouTube atau Meta Graph API |
| Task/pesan remote | Telegram atau Hermes-supported platforms |
| Relay event | Relay endpoint yang dikonfigurasi |
| Home automation | Home Assistant URL yang dikonfigurasi |

Domain hardcoded yang relevan adalah layanan umum seperti Google, YouTube, OpenAI/ChatGPT, Spotify, Meta, DuckDuckGo, Bing, Steam, cdnjs, dan endpoint Tabbit. Tidak ditemukan domain acak yang tampak seperti C2.

## 8. Audit spyware, malware, dan bahaya lain

### 8.1 Verdict per kategori

| Indikator | Hasil |
|---|---|
| Backdoor/C2 tersembunyi | Tidak ditemukan |
| Credential stealer | Tidak ditemukan; ada penyimpanan secrets plaintext yang berisiko dicuri pihak lain |
| Keylogger | Tidak ditemukan. Kode mengirim input keyboard/mouse, bukan merekam semua keystroke |
| Spyware kamera/layar | Tidak ditemukan capture tersembunyi untuk exfiltration; capture memang fitur eksplisit. Full voice dan wake tetap memakai mikrofon, Telegram whitelist dapat meminta screenshot |
| Persistence tersembunyi | Tidak ditemukan persistence diam-diam. Reminder dan game updater sengaja membuat scheduled task/LaunchAgent/cron |
| Ransomware/destructive payload | Tidak ditemukan, tetapi tool mampu menulis/memindah file, kill process, shutdown, dan menjalankan shell |
| Cryptominer | Tidak ditemukan |
| Obfuscation/payload terenkripsi | Tidak ditemukan; `base64` dipakai untuk image/audio/OAuth, AES dipakai dashboard |
| Executable tracked | Hanya `config/jarvis.ico` dan vendor `crypto-js.min.js`; tidak ada `.exe`, `.dll`, `.sys`, `.bat`, atau `.ps1` yang dilacak Git |
| Antivirus | Microsoft Defender: no threats pada seluruh workspace |

Hash aset lokal saat audit:

```text
EA10C08932BE8207A10BFD247DD8398242A1730D3EA1C89DBD7FEBA8D855828D  config/jarvis.ico
769A555DE553BABC35A3338F344DD7AA16260C93CEA2C7DB290707C90484E7CC  dashboard/static/crypto-js.min.js
63111777DAD6016E8BE5E81A164F3CD2F6E4282C8E40A40D8446049EE3ACFE04  yolov8n.onnx
F59B3D833E2FF32E194B5BB8E08D211DC7C5BDF144B90D2C8412C47CCFC83B36  yolov8n.pt
4663086E1B8EDBC4202A9EC589B03195ED149EF8AA8BEEB4B503E0E35FF1731A  yolov8s-oiv7.pt
```

Bobot model berada di luar Git; hash di atas berguna untuk mendeteksi perubahan lokal selanjutnya, bukan membuktikan file berasal dari publisher resmi.

### 8.2 Temuan kritis

#### K-1 — `execute_code` bukan sandbox keamanan

`jarvis/agent/tools/code_exec.py` menyebut subprocess sebagai sandbox, tetapi code berjalan sebagai user yang menjalankan JARVIS. Working directory dibatasi ke `data/sandbox`, namun Python/Node/Bash/PowerShell tetap dapat membaca home directory, environment, network, token, atau menjalankan proses lain. Tool ini tidak selalu meminta konfirmasi.

Dampak: prompt injection atau keputusan model yang salah dapat berubah menjadi arbitrary code execution pada host.

#### K-2 — Terminal memakai blacklist yang mudah dilewati

`terminal` dan `process_spawn` menjalankan string dengan `shell=True`. Konfirmasi hanya muncul bila regex `_DANGEROUS` cocok. Perintah dapat diobfuscate, dipanggil lewat interpreter lain, memakai alias, script file, encoded PowerShell, atau command berbeda yang efeknya sama. Parameter `cwd` juga tidak divalidasi agar tetap di workspace.

Dampak: arbitrary command execution dan persistence dapat terjadi tanpa konfirmasi yang diharapkan.

#### K-3 — Dua jalur eksekusi mempunyai guardrail berbeda

Registry agent native memiliki timeout, konfirmasi, dan audit log. Dispatcher voice legacy di `main.py` langsung memanggil `actions/` berdasarkan function call Gemini. Ia tidak melewati registry native. Tool legacy mencakup file write/delete/move, generated-code execution, dependency install, message sending, desktop automation, game scheduling, dan proses lain.

Dampak: mematikan tool group di panel Capabilities tidak melindungi jalur Gemini Live legacy.

### 8.3 Temuan tinggi

#### T-1 — Dashboard LAN terlalu agresif dan default exposure-nya luas

Saat full voice aktif, `main.py` mencoba memulai dashboard. Server bind ke `0.0.0.0:8000`, dan helper otomatis mencoba:

- mengubah network profile Windows dari Public menjadi Private;
- menambah inbound firewall rule untuk port dan `python.exe`;
- meminta elevation/UAC;
- membuka firewall di macOS/Linux dengan mekanisme setara.

Tanpa certificate lokal, traffic memakai HTTP. PIN pairing enam karakter berlaku 10 menit dan endpoint login tidak mempunyai rate limit yang terlihat. Bearer token/query token, device token di localStorage, WebSocket mic, command, history, serta upload hingga 500 MB memperbesar attack surface.

AES-CBC yang dipakai hanya memberi kerahasiaan payload command, bukan authenticated encryption. Ia juga tidak melindungi token transport, metadata, atau semua endpoint seperti TLS.

#### T-2 — Secrets dan OAuth token disimpan plaintext

- `config/providers.json` menyimpan API key walaupun keyring tersedia.
- `config/api_keys.json` menyimpan Gemini/YouTube key.
- YouTube OAuth selalu mencoba menulis credential file selain keyring.
- Spotify refresh/access token disimpan di JSON.
- `.env` berisi secrets tanpa enforcement permission file.
- `google_token.json` dibaca oleh source tetapi belum tercantum di `.gitignore`.

File utama memang diabaikan Git, tetapi plaintext tetap dapat dibaca proses lain dengan hak user yang sama.

#### T-3 — Tool ber-side-effect belum konsisten meminta konfirmasi

Contoh tool native yang dapat melakukan perubahan tetapi tidak selalu meminta konfirmasi:

- browser click/type/JavaScript/raw CDP;
- computer click/type/key/drag;
- Home Assistant service call;
- cron create/update/run;
- memory forget;
- Spotify playlist mutation;
- MCP call, walaupun efek tool server eksternal tidak diketahui;
- code execution dan process spawn.

Cron memakai adapter non-interaktif sehingga tool yang benar-benar bertanda confirmation akan ditolak, tetapi tool side-effect tanpa flag tetap dapat berjalan otomatis.

#### T-4 — Prompt injection dapat melompati batas trust

Agent memasukkan hasil web, accessibility tree, memory, skill, MCP output, dan dokumen ke konteks LLM. Tidak terlihat trust-label/policy engine yang memisahkan “data tidak dipercaya” dari “instruksi”. Bila halaman web menyuruh model menjalankan terminal atau membaca file, model masih mempunyai schema tool tersebut dalam sesi yang sama.

#### T-5 — SSRF dan akses service lokal

`web_extract`, browser navigate, custom provider, Relay endpoint, dan beberapa URL lain tidak menerapkan validasi IP private/link-local/metadata. Agent dapat diarahkan membuka `localhost`, service LAN, atau cloud metadata endpoint bila host berjalan di lingkungan cloud.

#### T-6 — Persistence berprivilege tinggi dapat dibuat oleh fitur

Game updater Windows mencoba membuat scheduled task dengan `/RL HIGHEST /RU SYSTEM` sebelum fallback ke task biasa. macOS/Linux memakai LaunchAgent/crontab. Reminder juga membuat scheduler entries. Ini fitur yang terlihat dan user-triggered, bukan persistence malware, tetapi membutuhkan consent dan audit yang jauh lebih kuat.

### 8.4 Temuan menengah

#### M-1 — Logging dapat membocorkan data sensitif

`main.py` mencetak nama dan seluruh argumen tool serta nilai memory ke console. Router log menyimpan teks dan slots. Registry native hanya meredaksi berdasarkan nama key tertentu; message body, path, document text, command, atau secret yang diletakkan dalam field bernama umum dapat tetap tercatat.

#### M-2 — Download dan install runtime menambah supply-chain risk

- `core/installer.py` dapat menjalankan `pip install` untuk paket hilang.
- `scripts/first_run_wizard.py` memasang dependency (kedua requirements) dan
  Playwright browser.
- `dashboard/server.py` mengunduh CryptoJS saat import bila file vendor hilang.
- Ultralytics dapat mengunduh bobot YOLO berdasarkan nama model.
- Tabbit installer URL tersedia di konfigurasi.

Mayoritas dependency tidak dipin ke hash/version exact. Compromised package/update dapat memperoleh hak user aplikasi.

#### M-3 — Requirements tidak lengkap dan tidak reproducible

`requirements.txt` sebagian besar tanpa version pin; `requirements-xlix.txt` memakai minimum version. Beberapa dependency runtime tidak tercantum. Auto-installer mempunyai daftar ketiga yang berbeda. Hal ini menyulitkan reproduksi, patching keamanan, dan audit SBOM.

#### M-4 — Global warning suppression dan monkey-patch subprocess

`main.py` menonaktifkan semua Python warning dan mengganti global `subprocess.Popen` di Windows agar tanpa window. Ini bukan perilaku malware, tetapi dapat menyembunyikan warning keamanan/deprecation dan membuat efek global sulit diprediksi.

#### M-5 — Data persisten tidak terenkripsi

Transcript session, memory, tool logs, Relay event, command history, browser session, screenshot, dan OAuth fallback file tersimpan lokal. Beberapa retention rule ada untuk screen awareness, tetapi tidak ada kebijakan enkripsi/retention terpadu.

#### M-6 — Konfigurasi tidak portabel

`config.yaml` dan Tabbit resolver memuat path absolut user Windows tertentu. Ini membocorkan username lokal dalam konfigurasi dan dapat menyebabkan salah-resolve di mesin lain.

## 9. Saran perbaikan

### 9.1 Prioritas P0 — sebelum dipakai dengan data nyata

1. Jadikan `--no-voice` sebagai mode evaluasi default sampai policy kedua jalur disatukan.
2. Matikan grup `terminal_processes`, `code_execution`, `computer_use`, `cron_jobs`, `home_assistant`, dan `mcp` secara default.
3. Jangan expose dashboard ke LAN secara otomatis. Default bind seharusnya `127.0.0.1`; LAN harus opt-in eksplisit.
4. Jangan otomatis mengubah profile jaringan atau firewall saat boot. Tampilkan instruksi dan minta consent terpisah.
5. Pindahkan semua secrets ke OS keyring/credential manager. Jangan menyimpan API key lagi di `providers.json` bila keyring berhasil.
6. Tambahkan `google_token.json` dan semua credential fallback ke `.gitignore`; atur permission owner-only.
7. Rotasi API/OAuth token bila folder ini pernah dibagikan, disinkronkan ke cloud, atau dikirim sebagai archive.
8. Jangan gunakan custom/OpenAI-compatible base URL yang tidak dipercaya karena seluruh prompt dan memory dapat dikirim ke sana.

### 9.2 Prioritas P1 — hardening arsitektur

1. Buat satu policy/permission engine untuk **semua** action, baik voice legacy maupun agent native.
2. Gunakan default-deny capability grants per session dan per adapter: UI, voice, Telegram, cron, Relay, dan sub-agent harus punya izin berbeda.
3. Semua aksi eksternal atau mutasi harus memakai confirmation object yang tidak dapat dipalsukan LLM: target, preview, scope, expiry, dan single-use approval.
4. Ganti blacklist shell dengan allowlist command/argument atau hapus general-purpose shell dari model. Untuk kode, gunakan container/VM/Windows Sandbox/restricted token dengan network dan filesystem policy nyata.
5. Larang cron dan Telegram menjalankan tool interaktif/berbahaya tanpa pre-authorized policy yang sangat sempit.
6. Terapkan SSRF protection: hanya HTTP(S), resolve DNS, blok loopback/private/link-local/metadata, batasi redirect, size, MIME, dan timeout.
7. Untuk dashboard gunakan TLS, AEAD seperti AES-GCM bila application encryption tetap perlu, rate limiting, expiry token, revoke per-device, no query-string bearer, origin checks, dan upload limit kecil.
8. Tambahkan prompt-injection boundary: tandai web/document/tool output sebagai untrusted data dan cegah data tersebut memberikan otorisasi tool.
9. Redaksi log berdasarkan schema dan taint, bukan hanya substring nama field. Jangan log full commands, message, document, token, atau memory value.
10. Enkripsi database/token/screenshot sensitif dan buat retention/delete UI yang konsisten.

### 9.3 Prioritas P2 — maintainability dan supply chain

1. Konsolidasikan `requirements.txt`, `requirements-xlix.txt`, dan auto-installer menjadi satu dependency definition dengan lockfile serta hashes.
2. Buat SBOM dan jalankan dependency scanner, secret scanner, SAST, dan Defender/AV di CI.
3. Verifikasi hash/signature CryptoJS, model weights, Playwright browser, dan Tabbit installer sebelum eksekusi.
4. Hapus auto-download saat import. Download hanya melalui workflow install eksplisit dengan progress dan consent.
5. Satukan entry point dan deprecate jalur legacy secara bertahap setelah feature parity tercapai.
6. Perbarui `readme.md`, `scripts/first_run_wizard.py`, requirements, dan docs agar semuanya menyebut Mark XLIX/MK50 serta command yang sama.
7. Tambah security tests untuk command bypass, path escape, symlink, SSRF, dashboard brute force, token expiry, WebSocket auth, prompt injection, dan confirmation replay.
8. Tambah integration test yang memastikan tool group disabled juga benar-benar memblokir jalur voice legacy.
9. Hapus path username hardcoded; gunakan environment/path discovery.
10. Jangan suppress seluruh warnings. Filter hanya warning dependency yang benar-benar dipahami.

## 10. Checklist operasi aman

Sebelum menjalankan:

- [ ] Gunakan virtual environment dan Python yang didukung.
- [ ] Review dependency dan lockfile.
- [ ] Jalankan Defender/antivirus.
- [ ] Gunakan `--no-voice` untuk evaluasi pertama.
- [ ] Pastikan screen awareness tetap off kecuali dibutuhkan.
- [ ] Pastikan Telegram whitelist hanya berisi ID milik sendiri.
- [ ] Pastikan Relay bind localhost dan mempunyai secret kuat.
- [ ] Pastikan MCP server list kosong atau seluruh server dipercaya.
- [ ] Matikan tool shell/code/computer/cron yang tidak diperlukan.
- [ ] Jangan gunakan dashboard pada Wi-Fi publik.
- [ ] Periksa firewall rule `JARVIS Dashboard Port 8000/8001` dan `JARVIS Dashboard Python`.
- [ ] Jangan masukkan dokumen, screenshot, atau audio sensitif bila provider cloud tidak boleh menerimanya.
- [ ] Backup data penting sebelum mengizinkan file/desktop/dev-agent actions.

Setelah menjalankan:

- [ ] Review `data/logs/tools.jsonl`, `logs/`, scheduled tasks, cron, dan LaunchAgents.
- [ ] Periksa `data/generated/`, `logs/screenshots/`, dan uploads dashboard.
- [ ] Revoke device dashboard yang tidak dikenal.
- [ ] Hapus/rotasi token bila log atau folder pernah bocor.
- [ ] Bandingkan hash model/vendor bila file berubah tanpa alasan.

## 11. Kesimpulan akhir

Repo ini adalah proyek asisten AI yang sangat luas, bukan contoh sederhana chatbot. Fitur utamanya nyata dan saling terhubung: Gemini Live, PyQt6, browser, vision, agent, memory, skills, messaging, cron, serta automation OS. Struktur baru cukup baik dalam hal graceful degradation, timeout, event bus, whitelist Telegram, Relay fail-closed, tool logging, dan beberapa confirmation gate.

Masalah terbesar bukan indikator malware, melainkan **authority yang terlalu besar tanpa boundary yang seragam**. Model cloud, halaman web, document content, Telegram, cron, browser automation, dan shell masih dapat bertemu dalam satu proses dengan hak user. Selama `execute_code`, terminal blacklist, dashboard LAN, plaintext secrets, serta split policy legacy/native belum diperbaiki, perlakukan JARVIS sebagai software eksperimental berisiko tinggi dan jalankan hanya di akun/VM terisolasi dengan data non-sensitif.
