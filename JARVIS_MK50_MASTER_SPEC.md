# JARVIS_MK50 — MASTER SPEC (Standalone Voice Agent)

> **Untuk: Claude Code (IDE) & Codex (IDE).** Baca **seluruhnya** sebelum menulis satu baris kode.
>
> **Basis:** `AUDIT_REPORT.md` (2026-07-17), `jarvis.md`, `MARK-XLIX.md`.
> Dokumen ini **menggabungkan dan menggantikan** `JARVIS_MK50_STANDALONE.md` + addendum Google/Telegram, dan **membatalkan arah** `JARVIS_HERMES_PARITY_v2.md` (Hermes di-deprecate, §0.1).
>
> **Referensi Hermes:** `hermes-agent-main/` READ-ONLY — hanya untuk **membaca pola** (mis. flow OAuth), **bukan** untuk diintegrasikan.

---

## Daftar Isi

**Aturan**
- [§0 Keputusan arsitektur (FINAL)](#0-keputusan-arsitektur-final)
- [§1 Zona FROZEN](#1-zona-frozen)

**Otak & jalur**
- [§2 Router — jantung (tier otomatis)](#2-router--jantung-tier-otomatis)
- [§3 Model routing per lane (Gemini vs berat)](#3-model-routing-per-lane-gemini-vs-berat)
- [§4 Interaktivitas — ack + laporan (dua fase)](#4-interaktivitas--ack--laporan-dua-fase)

**Perbaikan perilaku**
- [§5 Bug fix — alur YouTube](#5-bug-fix--alur-youtube)
- [§6 Bug fix — berita/web lokal Indonesia](#6-bug-fix--beritaweb-lokal-indonesia)

**UI**
- [§7 Buang Tabbit + rombak ContentStage](#7-buang-tabbit--rombak-contentstage)
- [§8 Panel Home Assistant (CCTV, lampu, cuaca)](#8-panel-home-assistant-cctv-lampu-cuaca)

**Integrasi & keamanan**
- [§9 Secrets — keyring + fallback terenkripsi + OAuth](#9-secrets--keyring--fallback-terenkripsi--oauth)
- [§10 Google Cloud Connector (satu OAuth, banyak API)](#10-google-cloud-connector-satu-oauth-banyak-api)
- [§11 Messaging — Telegram Control native (+ UI Settings)](#11-messaging--telegram-control-native--ui-settings)

**Efisiensi & eksekusi**
- [§12 Efisiensi (9 item, diintegrasikan)](#12-efisiensi-9-item-diintegrasikan)
- [§13 Urutan kerja — Fase 0–9](#13-urutan-kerja--fase-09)
- [§14 Checklist verifikasi akhir](#14-checklist-verifikasi-akhir)
- [§15 Anti-pattern](#15-anti-pattern)
- [§16 Catatan untuk Claude Code & Codex](#16-catatan-untuk-claude-code--codex)
- [§17 Ringkasan kemampuan Jarvis](#17-ringkasan-kemampuan-jarvis)

---

## §0 Keputusan arsitektur (FINAL)

Jangan tanya ulang. Ini sudah diputuskan user:

| # | Keputusan |
| --- | --- |
| 1 | **Jarvis = voice agent mandiri.** Bisa tugas ringan **dan** berat sendiri, **tanpa memanggil Hermes.** |
| 2 | **Tier otomatis.** Tugas ringan → **tanpa** mode agent (jalur Gemini). Tugas berat → **otomatis** mode agent (jalur model berat). |
| 3 | **Model per lane.** Gemini API key hanya untuk **percakapan + tugas ringan**. Tugas berat → **otomatis pakai API key lain** (§3). |
| 4 | **ContentStage** hanya untuk: **vision camera**, **informasi interaktif**, dan **Home Assistant** (CCTV, smart lamp, cuaca). **Bukan** browser. |
| 5 | **Buang Tabbit** browser-agent dan panel browser di ContentStage sepenuhnya. |
| 6 | **Interaktif.** Jarvis meng-*acknowledge* saat menerima tugas, lalu **melapor** saat selesai (§4). |
| 7 | **Perbaiki UI Messaging** yang tumpang tindih (§11), dan **perbaiki error keyring** + tambah **OAuth provider lain** (§9). |
| 8 | **Google Cloud Connector** (§10): satu OAuth, banyak API (Calendar, YouTube Data, Gmail, Drive) — "melihat & membacakan". |
| 9 | **Telegram Control** (§11) harus **benar-benar berfungsi** (token + user ID), setara kontrol Hermes tapi native. |

### §0.1 Hermes di-deprecate

- ❌ **JANGAN** panggil `hermes send`, `hermes -z`, atau CLI Hermes apa pun saat runtime.
- ✅ **Deprecate** `jarvis/integrations/hermes/bridge.py` & `actions/hermes_action.py`: bungkus feature-flag `integrations.hermes.enabled: false` (default) sehingga **tidak pernah dipanggil**. Jangan hapus filenya (hindari diff besar); matikan jalurnya. Catat di `MIGRATION_NOTES.md`.
- ✅ Semua yang dulu didelegasikan ke Hermes (kirim pesan, agen berat) kini **native** di agent loop Jarvis (fondasi sudah ada: `loop.py`, `delegate.py`, `registry.py`).

### §0.2 Prinsip arsitektur

**Additive, satu seam tipis.** Router (§2) adalah satu-satunya "otak" yang memutuskan jalur. Voice pipeline & UI lama tetap; mereka hanya **memanggil Router**, bukan diganti. Kemampuan baru masuk modul baru yang berdiri sendiri.

### §0.3 Discovery wajib sebelum coding

Path di dokumen ini adalah **saran** dari audit — sesuaikan dengan struktur nyata. Lakukan Fase 0 (§13) dulu: petakan repo, temukan seam, lapor ke user, tunggu konfirmasi. **Kode nyata menang atas spec** — bertabrakan → lapor, jangan paksakan.

---

## §1 Zona FROZEN

Yang **tetap FROZEN** — identitas Jarvis, jangan diubah:

| Path | Status | Catatan |
| --- | --- | --- |
| Voice pipeline (TTS/STT/wake-word) | **FROZEN** | Suara & cara bicara Jarvis milik user |
| `jarvis/ui/theme.py` | **FROZEN** | Design token — baca untuk ambil warna/spacing, jangan ubah |
| Aset visual / animasi orb / layout dasar | **FROZEN** | Tampilan Jarvis |

Yang **boleh diubah** — ini "otak", bukan "identitas", dan user minta diperbaiki:

| Path | Status | Aturan |
| --- | --- | --- |
| Titik dispatch **intent → aksi** | **SEAM** | Boleh dire-route lewat Router (§2). Ubah **seminimal mungkin**, hanya di titik jahitan. |
| `jarvis/ui/window.py` | **SEMI-FROZEN** | Boleh wiring panel & registrasi ContentStage. Jangan refactor. |
| `jarvis/ui/actionpanel.py` | **SEMI-FROZEN** | Boleh tambah ikon (Home Assistant). Ikuti pola GlyphButton. |
| `ContentStage` (`jarvis/ui/stage.py`) | **BOLEH DIUBAH** | Buang panel browser, daftarkan panel baru (§7). |
| `main.py` / `ui.py` (root legacy) | **FROZEN untuk tampilan/suara** | Jika perilaku naif (mis. YouTube §5) berasal dari dispatch di sini, re-route lewat seam — jangan ubah audio/tampilan. |

**Aturan emas:** ubah **perilaku routing**, jangan ubah **cara Jarvis terlihat & terdengar**. Ragu → anggap FROZEN, tanya user, catat di `MIGRATION_NOTES.md`.

---

## §2 Router — jantung (tier otomatis)

**Tujuan:** satu klasifikasi otomatis yang memutuskan **Ringan (tanpa agent)** vs **Berat (agent penuh)** — plus model mana yang dipakai. Pengungkit efisiensi terbesar.

### §2.1 Dua lane

```
Perintah (voice / teks / Telegram)
        │
        ▼
┌──────────────────┐
│  ROUTER          │  jarvis/agent/router.py  (BARU)
│  classify(text)  │
└───────┬──────────┘
        │
   ┌────┴─────────────────────────┐
   ▼                              ▼
LANE A — RINGAN               LANE B — BERAT
(Gemini, tanpa agent)        (mode agent, key lain)
                             + ACK + laporan (§4)
T0 Reflex   (no LLM)         T2 Agent Loop  (loop.py)
T1 Single   (1 turn Gemini)  T3 Delegate    (delegate.py)
                             T4 Autonomous  (cron)
```

> Tier "Bridge-Send" lama (Hermes) **dihapus**. Ladder baru bersih dari Hermes.

### §2.2 Definisi tier

| Tier | Lane | LLM | Agent loop | Model | Contoh |
| --- | --- | --- | --- | --- | --- |
| **T0 Reflex** | A | ❌ | ❌ | — | Volume, brightness, mute, fullscreen, ESC, gesture, buka aplikasi tunggal, toggle lampu HA |
| **T1 Single** | A | ✅ 1 turn | ❌ | **Gemini** | "jam berapa", "cuaca hari ini", tanya-jawab, "putar lagu X" (Spotify), "acara kalender hari ini" (Google §10) |
| **T2 Agent** | B | ✅ multi | ✅ | **Berat** (§3) | "buka & putar YouTube X terbaru", "riset A lalu buat tabel", cari & perbaiki file, alur browser bertujuan |
| **T3 Delegate** | B | ✅ banyak | ✅ (sub) | Berat | Sub-tugas besar/terisolasi via `delegate_task` |
| **T4 Autonomous** | B | ✅ | ✅ (tanpa human) | Berat | Cron: laporan harian terjadwal, konsolidasi memori |

### §2.3 Kontrak Router

```python
# jarvis/agent/router.py  (BARU)
from dataclasses import dataclass
from enum import IntEnum

class Tier(IntEnum):
    REFLEX = 0
    SINGLE = 1
    AGENT = 2
    DELEGATE = 3
    AUTONOMOUS = 4

@dataclass
class Route:
    tier: Tier
    lane: str            # "light" | "heavy"
    model_profile: str   # "light" | "heavy"  → dipakai §3
    reason: str          # untuk log & debug
    confidence: float    # 0..1

def classify(text: str, context: dict) -> Route:
    """
    Dua lapis:
      1. RULES (cepat, high-confidence) — pola jelas → langsung tier.
      2. LLM FALLBACK (ambigu) — classifier ringan (Gemini), output JSON.
    Tidak pernah raise. Default aman: ragu total → T2 (agent),
    karena agent bisa mengerjakan tugas ringan, sebaliknya tidak.
    """
    ...
```

### §2.4 Lapis 1 — Rules (deterministik)

**Lane A (ringan)** jika:
- Cocok daftar aksi reflex (volume/brightness/mute/fullscreen/mic/gesture/buka-app-tunggal/toggle lampu) → **T0**.
- 1 aksi tunggal jelas tanpa sekuens: satu lagu, satu query cuaca, satu pertanyaan faktual, sapaan/percakapan, satu pembacaan data (kalender/email/berita) → **T1**.

**Lane B (berat)** jika ada sinyal multi-langkah / penilaian:
- Kata sekuens: "**buka dan** …", "**cari lalu** …", "**terus** …", "**setelah itu** …".
- Kata penilaian atas hasil: "**terbaru**", "**paling …**", "**bandingkan**", "**ringkas**", "**pilih**".
- Kata kerja agentik: "**riset**", "**buatkan**", "**analisis**", "**perbaiki**", "**otomatis**", "**kerjakan**".
- Menyentuh file/kode/terminal/desktop-berurutan/browser-bertujuan.
- **Contoh kunci user:** "buka dan putar youtube deddy corbuzier terbaru" → "buka dan putar" + "terbaru" → **T2 (Lane B)**. Wajib lolos sebagai berat (§5).

### §2.5 Lapis 2 — LLM fallback (ambigu saja)

Kalau confidence < 0.7, panggil classifier ringan pakai **Gemini**:

```
System: Klasifikasikan perintah user ke tier.
T0=aksi sistem sepele, T1=satu tool/percakapan/pembacaan data,
T2=butuh banyak langkah/tool/penilaian.
Balas JSON: {"tier": 0|1|2, "reason": "..."} — TANPA teks lain.
User: <text>
```

Parsing gagal → default **T2** (aman).

### §2.6 Seam — di mana Router dipasang

1. Temukan titik tunggal tempat voice/teks/Telegram berubah jadi aksi (Fase 0).
2. Sisipkan `route = classify(text, ctx)` di titik itu.
3. `route.tier <= T1` → jalur ringan **yang sudah ada** (Gemini Live dispatch). Jangan ubah perilakunya.
4. `route.tier >= T2` → **hand off ke agent loop** (`jarvis/agent/loop.py`) dengan model berat (§3) + ACK/laporan (§4).

**Lapor lokasi seam** sebelum coding besar.

---

## §3 Model routing per lane (Gemini vs berat)

### §3.1 Config

```yaml
# config.yaml
routing:
  light:
    provider: gemini            # percakapan + T0/T1
    model: <model-gemini-ringan>
  heavy:
    provider: <provider-berat>  # T2+ : openai_oauth | anthropic_oauth | openai_api | openrouter | local
    model: <model-berat>
    fallback: [openrouter, local]   # rantai fallback bila 402/kredit habis/timeout
```

### §3.2 Aturan

- `model_profile="light"` → klien Gemini (voice pipeline sudah pakai ini).
- `model_profile="heavy"` → `jarvis/agent/llm_client.py` / `providers.py` memilih provider berat. Infrastruktur multi-provider **sudah ada** (audit §A.7, §B.7) — **pakai**, jangan tulis ulang.
- Kredensial berat dari **secrets_store** (§9), bukan plaintext.
- Provider berat **belum dikonfigurasi** → Jarvis tetap jalan; tugas berat degrade dengan pesan jujur lewat TTS ("Sir, model untuk tugas berat belum diatur — silakan hubungkan di Settings"). **Jangan crash, jangan diam.**

### §3.3 Efisiensi model

Side-task murah (kompresi konteks, judul sesi, embedding, classifier Router §2.5) → **selalu** ke model ringan (Gemini). Model berat **hanya** untuk agent loop inti. Memangkas biaya langsung.

---

## §4 Interaktivitas — ack + laporan (dua fase)

Meniru pola "Immediate Vision Acknowledgment" Mark XLVIII, digeneralisasi ke semua tugas Lane B.

### §4.1 Kontrak dua fase

Untuk **setiap** tugas T2+:

1. **ACK (langsung, sebelum kerja):** TTS segera mengucapkan pengakuan singkat & natural dalam bahasa user. Contoh: *"Baik sir, saya kerjakan."* / *"Siap sir, sedang saya buka."* **Jangan** diam selama planner berpikir.
2. **PROGRESS (opsional, tugas panjang):** update ringan tiap ~3 dtk di UI/log (bukan TTS spam): mis. `🔧 browser_navigate → youtube.com`.
3. **LAPORAN (setelah selesai):** TTS melaporkan hasil konkret. Contoh: *"Video terbaru Deddy Corbuzier sudah diputar, sir."* / *"Web sudah terbuka, sir."*

### §4.2 Aturan

- **Bentuk sapaan** ("sir") dari persona (`jarvis/agent/core/prompt.txt`). Tetap **language-aware**: kalimat Bahasa Indonesia, sapaan sesuai persona; jangan campur bahasa janggal (pelajaran XLVIII).
- ACK & LAPORAN **wajib** untuk T2+. Untuk T0/T1 (ringan), respons langsung — jangan tambah basa-basi.
- Frasa **bervariasi** (jangan robotik): simpan set template di config/persona, pilih acak.
- Gagal → LAPORAN **jujur**: *"Maaf sir, videonya tidak ketemu — YouTube memuat halaman kosong."* **Jangan mengaku sukses saat gagal.**

### §4.3 Implementasi (seam)

```
# jalur Lane B, sebelum loop.run():
await speak(pick(ACK_TEMPLATES, lang))     # fase 1
result = await agent.run(task, ...)         # fase 2
await speak(render_report(result, lang))    # fase 3
```

`speak()` memanggil pipeline TTS Jarvis (FROZEN) — panggil, jangan ubah. Berlaku juga di Telegram (§11.6).

---

## §5 Bug fix — alur YouTube

### §5.1 Gejala (sekarang salah)

"buka dan putar youtube deddy corbuzier terbaru" → Jarvis membuka window & **mengetik perintah literal**, tidak menuju browser, tidak mencari target, tidak memutar video terbaru.

### §5.2 Akar masalah

Perintah di-route ke aksi naif (`open_app` + `computer_type` teks mentah) alih-alih **agent loop dengan tool browser**. Kata "**terbaru**" butuh **penilaian atas hasil pencarian** — mustahil dengan keystroke buta.

### §5.3 Target perilaku (Lane B / T2)

Router (§2.4) **wajib** menandai perintah ini berat, lalu agent loop:

1. `browser_navigate` → `https://www.youtube.com/results?search_query=deddy+corbuzier+terbaru` (atau navigate youtube.com → ketik di kolom via `browser_snapshot` → `browser_type` → submit).
2. `browser_snapshot` → baca accessibility tree hasil (judul + tanggal upload + channel).
3. **Pilih dengan penilaian:** utamakan channel resmi **Deddy Corbuzier** & video **paling baru** (boleh pakai sort-by-date `&sp=CAI%253D` sebagai jalur cepat).
4. `browser_click` ref video terpilih → halaman video.
5. Pastikan **autoplay** (klik play bila perlu; tangani consent/cookie via `browser_dialog`).
6. LAPORAN (§4): *"Video terbaru Deddy Corbuzier sudah diputar, sir."*

### §5.4 Aturan

- **SELALU `browser_snapshot` sebelum `browser_click`/`browser_type`** — jangan klik buta.
- Tool `youtube_video`/`youtube` (bila ada) **jangan** mengetik ke aplikasi acak — harus **menggerakkan browser**. Kalau tidak bisa, agent pakai `browser_*` generik.
- Browser = **satu context persisten** (jangan spawn tiap tool call).
- **Jangan** `open_app` + `computer_type` untuk tugas web bertujuan (itu akar bug).

### §5.5 Verifikasi

- [ ] Perintah YouTube → Router = **T2**.
- [ ] Jarvis membuka **browser** (bukan mengetik ke window acak).
- [ ] Video yang diputar milik **channel benar** & **terbaru**.
- [ ] ACK sebelum mulai; LAPORAN setelah play.

---

## §6 Bug fix — berita/web lokal Indonesia

### §6.1 Gejala

"apa berita terbaru hari ini" → hasil tidak ditargetkan ke Indonesia. User berdomisili di Indonesia & berbahasa Indonesia; hasil harus lokal.

### §6.2 Target

`web_search` (mode `news`) & `web_extract` **menyuntikkan lokal** ke setiap query:

```yaml
# config.yaml
locale:
  region: ID
  language: id
  timezone: Asia/Jakarta
  news_market: id-ID
```

- DuckDuckGo (`ddgs`): `region="id-id"` (param `kl`) pada `ddgs.news(...)`.
- Augmentasi query: "berita terbaru hari ini" → tambah konteks lokal + `region=id-id`.
- Pakai `ddgs.news()` (artikel nyata, bukan homepage — pelajaran XLVIII); tampilkan judul + sumber + waktu.

### §6.3 Deteksi otomatis lokal

Prioritas sumber `locale`:
1. `config.yaml: locale` (eksplisit).
2. **Bahasa terdeteksi** dari perintah (reuse "Silent Language Memory" XLVIII: Indonesia → `region=ID` bila config kosong).
3. Fallback: `id-ID`.

### §6.4 Aturan

- Semua tool web membaca `locale` dari config, **tidak hardcode** region.
- Hasil berita juga tampil di **panel info interaktif** ContentStage (§7) dengan timestamp + atribusi sumber.
- LAPORAN (§4) menyebut ringkas: *"Ini berita terbaru dari Indonesia, sir."*

### §6.5 Verifikasi

- [ ] Query berita → hasil didominasi sumber Indonesia berbahasa Indonesia.
- [ ] Mengubah `locale.region` → hasil ikut berubah.
- [ ] Kartu berita muncul di ContentStage (info), bukan panel browser.

---

## §7 Buang Tabbit + rombak ContentStage

### §7.1 Buang Tabbit

- Hapus jalur **Tabbit browser-agent**: `jarvis/browser/skill_memory.py` & `config/tabbit_skills.json`.
- Hapus **panel browser** dari ContentStage (buang entri `stage.register("browser", …)` di `window.py:317-343`).
- Embedded browser (QtWebEngine) **tetap ada** sebagai **tool agent** (`browser_*` untuk §5), tapi **bukan panel** di ContentStage. Jarvis mengemudikannya di latar; user tidak melihat panel Tabbit.
- Catat di `MIGRATION_NOTES.md`.

### §7.2 ContentStage baru — hanya 3 hal

```python
stage.register("vision", VisionPanel(...))   # kamera live + YOLO + skeleton (SUDAH ADA)
stage.register("info",   InfoPanel(...))      # info interaktif: cuaca, berita, hasil pencarian
stage.register("home",   HomePanel(...))      # Home Assistant: CCTV, lampu, cuaca (§8)
```

- ❌ Tidak ada "browser". ❌ Tidak ada "messaging" di ContentStage (messaging = Settings, §11).
- **Panel info interaktif:** kartu cuaca, kartu berita (§6), hasil pencarian dengan timestamp.

### §7.3 Aturan

- Ikon pemicu di **ActionPanel** (pola GlyphButton): tambah ikon **Home Assistant**. Ikon vision/upload/spotify tetap.
- Token warna/spacing dari `theme.py` (FROZEN — baca saja).
- Manfaatkan state `LOADING` saat panel menarik data (jangan blok UI thread).

---

## §8 Panel Home Assistant (CCTV, lampu, cuaca)

Bagian ContentStage (`"home"`). Tool HA sudah ada (`home_assistant.py`; `ha_list_entities`, `ha_get_state`, `ha_call_service` — audit §A.6). Ini menambah **UI** di atas tool yang ada.

### §8.1 Isi panel

| Widget | Sumber data | Aksi |
| --- | --- | --- |
| **CCTV / kamera** | Entity `camera.*` via HA (stream proxy / snapshot) | Tampil live; klik → perbesar |
| **Smart lamp** | Entity `light.*` | Toggle on/off, brightness slider → `ha_call_service("light","turn_on/off",...)` |
| **Cuaca** | Tool `weather_report` + entity `weather.*` | Kartu cuaca lokal (pakai `locale`, §6) |

### §8.2 Aturan

- State via **HA REST API + long-lived token** (`HA_URL`, `HA_TOKEN`); cache entity, refresh ~5 mnt.
- Stream kamera: proxy HA (`/api/camera_proxy_stream/<entity>`) di QtWebEngine/QMediaPlayer; bila berat → fallback snapshot berkala.
- Kontrol lampu = aksi langsung (T0/T1). Perintah suara "matikan lampu ruang tamu" → T1.
- Opsional: `HA_URL`/`HA_TOKEN` kosong → empty-state jujur ("Home Assistant belum terhubung"), tidak crash.

### §8.3 Verifikasi

- [ ] Panel Home tampil lewat ikon ActionPanel.
- [ ] Feed CCTV tampil (atau snapshot bila stream tak didukung).
- [ ] Toggle lampu benar-benar mengubah state HA.
- [ ] Kartu cuaca sesuai `locale`.
- [ ] Tanpa kredensial HA → empty-state, bukan error.

---

## §9 Secrets — keyring + fallback terenkripsi + OAuth

Error saat ini: *"keyring OS tidak tersedia - instal paket 'keyring' dulu; token tidak boleh disimpan plaintext"*. Token gagal disimpan → provider gagal.

### §9.1 Perbaiki keyring

- `requirements.txt`: tambah `keyring`, `cryptography` (fallback §9.2), dan (Windows) `pywin32` (DPAPI + Credential Locker).
- Windows: Credential Locker. macOS: Keychain. Linux: SecretService (dbus + GNOME Keyring/KWallet); headless → **wajib fallback §9.2**.

### §9.2 Fallback terenkripsi (JANGAN plaintext)

`jarvis/core/secrets_store.py` (sudah ada) → **berlapis**, urut prioritas:

```
1) keyring OS               → terbaik
2) Windows DPAPI            → win32crypt.CryptProtectData/Unprotect
                              (terenkripsi, terikat akun Windows, tanpa passphrase)
3) Fernet file terenkripsi  → cryptography.Fernet
                              key acak di ~/.jarvis/.keyfile (0600),
                              secret di ~/.jarvis/secrets.dat (0600), dir 0700
4) ❌ plaintext             → TIDAK PERNAH
```

- Deteksi backend saat start; **jangan error keras** kalau keyring absen — **turun ke fallback**, log backend aktif (satu baris).
- Ekspos backend aktif di **Settings** ("Penyimpanan aman: Keyring OS / DPAPI / File terenkripsi").
- API tetap: `get(name)` / `set(name, value)` / `delete(name)`. Kode pemanggil tidak berubah.

### §9.3 OAuth provider (LLM & lainnya)

| Provider | Metode | Kapabilitas |
| --- | --- | --- |
| Google **Gemini** | API key | chat (ringan §3), vision |
| **Google (Cloud Console)** | **OAuth** (loopback) | Calendar, YouTube Data, Gmail, Drive, dst. per scope (§10) |
| OpenAI (ChatGPT/Codex) | **OAuth** (PKCE+loopback) / API key | chat; image (`gpt-image-2` via API key) |
| Anthropic (Claude) | **OAuth** / API key | chat, vision |
| OpenRouter | API key | chat (fallback berat) |
| Local (LM Studio/Ollama) | endpoint (tanpa key) | chat |

> **Gemini** (LLM lane ringan) & **Google connector** (§10, data/Workspace) terpisah — keduanya bisa aktif bersamaan.

Flow OAuth (desktop-standard): `webbrowser.open()` + **loopback** `http://localhost:PORT/callback` (PKCE). **Jangan** QtWebEngine (login OAuth sering diblokir di webview embedded). Token → **secrets_store** (§9.2), **tidak** ke `config.yaml`. Baca pola dari `hermes-agent-main` (READ-ONLY) bila perlu; implementasi native.

```yaml
# config.yaml — metadata & capability; TOKEN di secrets_store
providers:
  gemini:         { enabled: true,  auth: api_key, capabilities: [chat, vision] }
  google:         { enabled: false, auth: oauth,   apis: {} }        # §10
  openai_oauth:   { enabled: false, auth: oauth,   capabilities: [chat] }
  openai_api:     { enabled: false, auth: api_key, capabilities: [chat, image, vision] }
  anthropic_oauth:{ enabled: false, auth: oauth,   capabilities: [chat, vision] }
  openrouter:     { enabled: false, auth: api_key, capabilities: [chat] }
  local:          { enabled: false, auth: none,    capabilities: [chat] }
```

`routing.heavy.provider` (§3) menunjuk provider berkapabilitas `chat` yang `enabled`. `image_generate` gate `available()` = True hanya bila ada provider berkapabilitas `image`.

### §9.4 Verifikasi

- [ ] Mesin tanpa keyring OS → token **tetap tersimpan terenkripsi** (DPAPI/Fernet), tanpa error, tanpa plaintext.
- [ ] Settings menampilkan backend aman aktif.
- [ ] OAuth OpenAI **dan** Anthropic login lewat browser → token tersimpan → provider `enabled`.
- [ ] Memilih provider berat di Settings → tugas T2 memakainya.
- [ ] `.keyfile`/`secrets.dat` berpermission ketat & ter-`.gitignore`.

---

## §10 Google Cloud Connector (satu OAuth, banyak API)

### §10.1 Prinsip — satu OAuth, banyak API

User meng-*enable* API di Cloud Console & membuat **satu OAuth client**; Jarvis OAuth dengan **scope** sesuai API aktif. Tambah API baru = tambah scope + satu modul tool — **bukan** OAuth baru.

```
Google Cloud Console (dikelola user)
  ├─ Buat Project
  ├─ Enable API:  YouTube Data v3 · Calendar · Gmail · Drive · Tasks · ...
  └─ OAuth Client 2.0 (Desktop app) → client_id + client_secret
                                    │
        ──OAuth (loopback+PKCE, reuse §9.3)──►  Token (scope gabungan)
                                    │                    │
                                    ▼                    ▼
                            secrets_store (§9)    Modul tool per-API
                                                  (gate available() per-scope)
```

`available()` tiap tool Google = True **hanya** bila token ada **dan** scope-nya tercakup. API yang tak di-enable → tool-nya diam. Registry sudah mendukung gate ini (audit §A.6).

### §10.2 Setup user (dokumentasikan di README)

1. Cloud Console → buat Project.
2. **Enable API** yang diinginkan (YouTube Data v3, Calendar, Gmail, Drive).
3. **OAuth consent screen** → *External* (atau *Internal* bila Workspace) → tambahkan diri sebagai *Test user*.
4. **Credentials → Create OAuth client ID → Desktop app** → salin `client_id` + `client_secret`.
5. Masukkan ke Jarvis (Settings → Providers → Google) → **Connect** → browser → izinkan scope → selesai.

> Selama app belum diverifikasi Google, muncul peringatan "unverified app" — normal untuk pemakaian pribadi (daftarkan diri sebagai test user). `client_secret` disimpan lewat secrets_store (§9), bukan `config.yaml`.

### §10.3 Scope per API

Inkremental, **read-only** kecuali fitur menulis diminta.

| API | Scope (read) | Scope (tulis, opsional) |
| --- | --- | --- |
| Calendar | `calendar.readonly` | `calendar.events` |
| YouTube Data v3 | `youtube.readonly` | `youtube` |
| Gmail | `gmail.readonly` | `gmail.send`, `gmail.modify` |
| Drive | `drive.readonly` | `drive.file` |
| Tasks | `tasks.readonly` | `tasks` |

Simpan scope yang **benar-benar diberikan** (hasil consent) di secrets_store bersama token, agar `available()` cek per-scope.

### §10.4 Modul tool — satu file per API

Di `jarvis/agent/tools/`. Ikut kontrak tool (async, timeout, `ToolResult`, tak pernah raise). "Membacakan" = tool kembalikan teks ringkas → agent/voice TTS-kan.

**`google_calendar.py`** — `gcal_events` (list hari ini/rentang → dibacakan), `gcal_create` (butuh scope tulis), `gcal_next`.
**`google_youtube.py`** (Data API — **baca**, beda dari memutar via browser §5) — `yt_subscriptions`, `yt_latest` (video terbaru langganan/channel → dibacakan), `yt_search_data`, `yt_my_stats`.
**`gmail.py`** (menjawab kebutuhan email) — `gmail_list` (unread/rentang → dibacakan), `gmail_read`, `gmail_send` (butuh `gmail.send`).
**`google_drive.py`** — `gdrive_search`, `gdrive_read` (ekspor teks).

**Pola generik "API Google lain"** (Contacts, Sheets, dst.): satu file tool + scope + token yang sama. Dokumentasikan di `MIGRATION_NOTES.md`.

### §10.5 Perbedaan penting — Data API vs Browser (§5)

| Perintah | Jalur | Tier |
| --- | --- | --- |
| "putar video terbaru Deddy Corbuzier" | **Browser** (§5): navigate → search → play | T2 |
| "video terbaru dari channel langgananku" | **YouTube Data API** (`yt_latest`): baca → bacakan | T1 |
| "acara kalender hari ini" | **Calendar API** (`gcal_events`) | T1 |
| "ada email baru?" | **Gmail API** (`gmail_list`) | T1 |

Router (§2) memilih: **membaca & membacakan** = ringan (Gemini, T1); **bertindak multi-langkah** = berat (T2).

### §10.6 Library & config

- `google-auth`, `google-auth-oauthlib` (OAuth loopback), `google-api-python-client`. Tambah ke `requirements.txt`.
- Reuse loopback OAuth §9.3; auto-refresh token; refresh token di secrets_store.
- Opsional: `providers.google.enabled=false` / scope tak diberikan → tool diam, Jarvis tetap jalan.

```yaml
# config.yaml (di bawah providers.google)
providers:
  google:
    enabled: false
    auth: oauth
    apis:                       # diisi sesuai enable user + hasil consent
      calendar:  { scopes: [calendar.readonly] }
      youtube:   { scopes: [youtube.readonly] }
      gmail:     { scopes: [gmail.readonly, gmail.send] }
      drive:     { scopes: [drive.readonly] }
```

### §10.7 Verifikasi

- [ ] Enable **hanya** Calendar → hanya `gcal_*` aktif; `gmail_*`/`yt_*` diam.
- [ ] "acara hari ini" → Jarvis **membacakan** acara dari Google Calendar.
- [ ] "video terbaru langgananku" → Jarvis membacakan judul dari YouTube Data API (bukan buka browser).
- [ ] "ada email baru?" → Jarvis membacakan ringkasan dari Gmail.
- [ ] Token & client_secret **tidak** di `config.yaml`.
- [ ] Scope tulis → fitur tulis (buat acara/kirim email) aktif; tanpa itu read-only.
- [ ] Provider Google kosong → Jarvis tetap start.

---

## §11 Messaging — Telegram Control native (+ UI Settings)

Menggabungkan perbaikan UI tumpang tindih **dan** adapter native yang berfungsi. Referensi desain: `jarvis.md` §5. Messaging **bukan** di ContentStage (§7) — ia di **Settings** + adapter background.

### §11.1 Status & tujuan

- **Sekarang:** kontrol Telegram **tidak berfungsi** mandiri — dulu hanya lewat Hermes (`hermes send`), di-deprecate (§0.1). UI-nya juga **tumpang tindih**.
- **Target:** hubungkan **bot token + user ID** → kirim perintah (teks & voice note) dari mana saja → Jarvis eksekusi (lewat Router §2, sama seperti suara) → balas hasil. Setara kontrol Hermes, tapi native.

### §11.2 Arsitektur — Telegram = adapter I/O sejajar suara

Perintah Telegram **memakai Router & agent yang sama** dengan perintah suara — lewat `classify()` (§2) → Lane A/B persis seperti dari mikrofon.

```
Telegram msg ──► Adapter ──► allowlist gate ──► Router.classify() ──► agent/loop
   (teks/voice)               (§11.4)              (§2)                  │
        ▲                                                                │
        └──────────────── balasan (edit pesan, streaming) ◄─────────────┘
```

### §11.3 Library & entry

- `python-telegram-bot` (async) atau `aiogram`. Tambah ke `requirements.txt`.
- Adapter: `jarvis/agent/adapters/telegram.py` (BARU), ikut `jarvis.md` §5.1 (`Adapter` ABC: `receive`/`send`/`ask`).
- Jalan sebagai task async dalam proses Jarvis (long-polling — tanpa port publik).

### §11.4 ⚠ Keamanan — allowlist (SYARAT)

Jarvis punya akses terminal + desktop + file. **Bot tanpa allowlist = menyerahkan komputer ke internet.**

```python
# Middleware PERTAMA, sebelum handler apa pun:
ALLOWED = {int(x) for x in secrets_get("TG_ALLOWED_IDS").split(",") if x}
if update.effective_user.id not in ALLOWED:
    log.warning(f"Akses ditolak: {update.effective_user.id}")
    return   # DIAM — jangan balas, jangan bocorkan bot ini ada
```

- Bot **tidak bisa** start tanpa minimal satu ID (master toggle disabled).
- Token & allowed IDs di **secrets_store** (§9), bukan plaintext.

### §11.5 Perintah

| Perintah | Fungsi |
| --- | --- |
| *(teks bebas)* | Kirim ke Router → agent (ringan/berat otomatis) |
| `/status` | Sesi aktif, tugas berjalan, resource |
| `/stop` | Batalkan tugas berjalan |
| `/todo` | Todo list saat ini |
| `/memory <query>` | Cari memori |
| `/cron` | List cron + tombol pause/resume/run |
| `/screen` | Screenshot desktop → foto |
| `/skills` | List skill |
| `/session` | ID sesi + tombol reset |
| `/confirm` | Setujui aksi `requires_confirmation` |

### §11.6 Voice note & interaktivitas

- **Voice note masuk → STT** pakai pipeline suara Jarvis (FROZEN — wrapper tipis `adapters/jarvis_voice.py`, jangan ubah) → teks → Router → agent.
- **ACK + LAPORAN (§4)** berlaku di Telegram: balas "🤔 Baik sir, saya kerjakan…" langsung, lalu **edit pesan yang sama** dengan progress, lalu laporan akhir. Jangan spam pesan baru.
- Output > 4000 char → file `.md`. Screenshot/gambar → foto.
- `requires_confirmation` → inline keyboard [✅ Lanjut] [❌ Batal], timeout 5 mnt → auto-batal.

### §11.7 UI konfigurasi (Settings → Messaging, rapi)

Perbaikan tumpang tindih:

- Layout `QFormLayout`/`QVBoxLayout` rapi (`setContentsMargins`/`setSpacing` dari `theme.py`), **bukan** posisi absolut.
- Field: **Bot token** (mask `•••` + badge *Saved*), **Allowed user IDs**, **master toggle** (disabled selama allowlist kosong), **status dot** (terhubung/belum).
- Simpan → secrets_store. Test koneksi → tampilkan nama bot bila valid.

### §11.8 Verifikasi

- [ ] Hubungkan **bot token + user ID** → status "terhubung".
- [ ] Teks bebas dari user allowlist → dieksekusi & dibalas hasilnya.
- [ ] Dari user **di luar** allowlist → **diabaikan total**, tanpa balasan.
- [ ] Voice note → di-STT → dieksekusi.
- [ ] Perintah berat dari Telegram → agent mode + ACK/LAPORAN (sama seperti suara).
- [ ] `/screen`, `/todo`, `/stop`, `/confirm` berfungsi.
- [ ] Panel Settings **tidak tumpang tindih**.
- [ ] **Tidak ada** pemanggilan Hermes. Token & IDs di secrets_store, ter-`.gitignore`.

---

## §12 Efisiensi (9 item, diintegrasikan)

| # | Item | Fase |
| --- | --- | --- |
| 1 | **Router tier tunggal** (cegah agent loop untuk T0/T1) | §2 — **Fase 1** |
| 2 | **Retire UI ganda** (`main.py`+`ui.py` ~180KB) — rencana pensiun `ui.py` setelah parity `jarvis/ui/` | **Fase 9** |
| 3 | **Agregasi `tools.jsonl` incremental** (cache byte-offset) | **Fase 6** |
| 4 | **Rotasi `tools.jsonl`** (harian/ukuran + rollup) | **Fase 6** |
| 5 | **Retrieval skill saat >~40 skill** (embed deskripsi, top-K) | **Fase 6** |
| 6 | **Model bertingkat** (side-task murah → model kecil) | §3.3 — **Fase 3** |
| 7 | **Lazy-load vision** (YOLO/MediaPipe hanya saat di-arm F6/F8) | **Fase 5** |
| 8 | **Enforce FROZEN via CI** (hash byte-identik voice/tema) | **Fase 9** |
| 9 | **Higiene secret** (`.env`, `api_keys.json`, `.keyfile`, `secrets.dat` ter-`.gitignore`) | **Fase 0** |

---

## §13 Urutan kerja — Fase 0–9

Satu fase → commit → lapor → lanjut. Jangan borong. Dependensi: secrets/OAuth (Fase 6) **sebelum** Google (Fase 7) & Telegram (Fase 8).

- [ ] **Fase 0 — Discovery.** Petakan repo (tree 3–4 level). Temukan **seam** intent→aksi (§2.6), lokasi voice dispatch, provider config, `secrets_store.py`, registrasi ContentStage. Pastikan `.gitignore` menutup semua secret (efisiensi #9). Tulis "Baseline Inventory" ke `MIGRATION_NOTES.md`. **STOP, lapor, tunggu konfirmasi.**
- [ ] **Fase 1 — Router + de-Hermes.** `router.py` (rules + LLM fallback, §2). Pasang di seam. Feature-flag Hermes `enabled:false` (§0.1). Test klasifikasi. **Belum ubah UI.**
- [ ] **Fase 2 — Bug YouTube + interaktivitas.** Perintah YouTube → T2 → alur browser benar (§5). Tambah ACK+LAPORAN dua fase (§4). Verifikasi §5.5.
- [ ] **Fase 3 — Model routing per lane.** `routing.light/heavy` (§3); side-task → model kecil (§3.3). Degrade jujur bila provider berat kosong.
- [ ] **Fase 4 — Web lokal Indonesia.** `locale` config + injeksi region/bahasa ke `web_search`/`web_extract`/news (§6). Reuse Silent Language Memory. Verifikasi §6.5.
- [ ] **Fase 5 — ContentStage + Tabbit + Home Assistant + vision lazy.** Buang Tabbit & panel browser (§7). Daftarkan `vision`/`info`/`home`. Bangun panel Home Assistant (§8). Lazy-load vision (#7). Verifikasi §8.3.
- [ ] **Fase 6 — Secrets + OAuth + telemetri.** Fix keyring + fallback terenkripsi (§9.1–9.2). OAuth multi-provider (§9.3). Agregasi/rotasi `tools.jsonl` (#3,#4); retrieval skill bila perlu (#5). Verifikasi §9.4.
- [ ] **Fase 7 — Google Cloud Connector.** OAuth Google (reuse §9.3) + `google_calendar` dulu (paling sederhana, "membacakan"), lalu `google_youtube`, `gmail`, `google_drive`. Gate `available()` per-scope. Dokumentasikan setup Cloud Console di README (§10.2). Verifikasi §10.7.
- [ ] **Fase 8 — Telegram Control (berfungsi) + UI Messaging rapi.** Adapter native (`adapters/telegram.py`) + allowlist + perintah + voice note→STT + ACK/LAPORAN, semua lewat Router. Rapikan UI Settings (§11.7). Verifikasi §11.8.
- [ ] **Fase 9 — Finalisasi.** CI hash FROZEN (#8). Rencana pensiun `ui.py` (#2). README/MIGRATION_NOTES final. Regression: UI & suara identik.

---

## §14 Checklist verifikasi akhir

- [ ] Voice & tema Jarvis → **identik** (diff kosong pada file FROZEN; CI hash lulus).
- [ ] **Tidak ada** pemanggilan Hermes saat runtime (grep `hermes` di jalur eksekusi = mati).
- [ ] Tugas ringan (cuaca, sapaan, putar lagu, baca kalender/email) → **tanpa** agent loop, jalur Gemini.
- [ ] Tugas berat (YouTube putar, riset, perbaiki file) → **otomatis** agent loop, model berat.
- [ ] "buka dan putar youtube deddy corbuzier terbaru" → browser terbuka, video channel benar & terbaru diputar.
- [ ] "apa berita terbaru hari ini" → berita Indonesia berbahasa Indonesia, tampil di panel info.
- [ ] Setiap tugas berat → ACK di awal + LAPORAN di akhir (jujur saat gagal).
- [ ] ContentStage hanya **vision / info / home**. Tidak ada browser/Tabbit.
- [ ] Panel Home Assistant: CCTV + toggle lampu + cuaca berfungsi.
- [ ] Keyring error hilang: token tersimpan terenkripsi tanpa plaintext; backend tampil di Settings.
- [ ] OAuth OpenAI & Anthropic berfungsi; provider berat bisa dipilih.
- [ ] Google Connector: enable API di Cloud Console → tool terkait aktif; "acara hari ini"/"email baru?"/"video terbaru langgananku" dibacakan.
- [ ] Telegram: token + user ID → perintah dari user allowlist jalan; user lain diabaikan; voice note jalan; UI rapi.
- [ ] Semua integrasi opsional kosong → Jarvis tetap start tanpa error.
- [ ] `.env`, `api_keys.json`, `.keyfile`, `secrets.dat` ter-`.gitignore`.
- [ ] `MIGRATION_NOTES.md` lengkap.

---

## §15 Anti-pattern

- ❌ **Menjalankan agent loop untuk tugas ringan** — Router harus mencegahnya (§2).
- ❌ **Memanggil Hermes** — deprecated (§0.1).
- ❌ **`open_app` + `computer_type` untuk tugas web bertujuan** — akar bug YouTube (§5). Pakai browser tools.
- ❌ **`browser_click` tanpa `browser_snapshot`** — klik buta.
- ❌ **Hardcode region berita** — baca `locale` (§6).
- ❌ **Menaruh browser/messaging di ContentStage** — ContentStage = vision/info/home saja (§7).
- ❌ **Menyimpan token plaintext / crash saat keyring absen** — fallback terenkripsi (§9).
- ❌ **Token/secret (OAuth, client_secret, bot token) di `config.yaml`** — secrets_store saja.
- ❌ **Login OAuth via QtWebEngine embedded** — browser eksternal + loopback (§9.3).
- ❌ **OAuth Google baru per-API** — satu OAuth, scope inkremental (§10.1).
- ❌ **Menyamakan `yt_latest` (baca) dengan memutar video (browser)** — dua jalur berbeda (§10.5).
- ❌ **Bot Telegram aktif tanpa allowlist** (§11.4).
- ❌ **Handler Telegram di luar Router** — harus lewat `classify()` yang sama (§11.2).
- ❌ **Mengubah suara/tema/animasi Jarvis** — FROZEN (§1).
- ❌ **Diam saat tugas berat berjalan / mengaku sukses saat gagal** — wajib ACK + LAPORAN jujur (§4).
- ❌ **Menulis ulang registry/loop/skills/memory** — sudah ada, bungkus (audit §D.3).
- ❌ **Mengerjakan semua fase sekaligus.**

---

## §16 Catatan untuk Claude Code & Codex

- **Discovery dulu, selalu (§0.3/Fase 0).** Path di sini **saran**; sesuaikan dengan struktur nyata. Kode nyata menang → bertabrakan, **lapor, jangan paksakan**.
- **Satu seam tipis (§2.6).** Router adalah otak; jangan sebar logika routing ke banyak tempat.
- **Ubah perilaku, bukan identitas.** Suara & tampilan FROZEN; routing & tool boleh diperbaiki.
- **Default aman.** Ragu ringan/berat → **berat** (agent bisa kerjakan ringan; sebaliknya tidak).
- **Semua opsional degrade jujur.** Kredensial kosong → pesan jelas lewat TTS/UI, **jangan crash, jangan diam.**
- **Verifikasi implementasi Hermes/OAuth** ke `hermes-agent-main` (READ-ONLY) bila meniru pola; **jangan mengarang** signature — kalau tak ada, katakan tidak tahu dan tanya.
- **Commit per fase, lapor, lanjut.** Jangan borong.

---

## §17 Ringkasan kemampuan Jarvis

Setelah 10 fase, Jarvis menjadi **voice-agent mandiri** (tanpa Hermes) dengan:

- **Tier otomatis** — ringan lewat Gemini (cepat, murah), berat lewat agent + model kuat, diputuskan Router.
- **Computer-use nyata** — navigasi/klik/scroll/ketik di **web** (`browser_*`) & **desktop** (`computer_*`); cari & perbaiki file (`file_ops`+`terminal`+`code_exec`); alur bertujuan seperti memutar video YouTube yang benar & terbaru.
- **Sadar-lokasi** — berita/web Indonesia berbahasa Indonesia otomatis.
- **Interaktif** — ACK saat menerima tugas, LAPORAN saat selesai (jujur saat gagal), di suara & Telegram.
- **Google Workspace/Data via suara & Telegram** — "acara hari ini?", "ada email penting?", "video terbaru langgananku?", "cari file di Drive" → dibaca lewat API resmi Google & **dibacakan**. Termasuk **email native** (Gmail).
- **Smart home** — panel CCTV, kontrol lampu, cuaca di ContentStage.
- **Kontrol jarak jauh Telegram** setara Hermes — kirim tugas (teks/suara) dari mana saja, dengan tier routing & keamanan allowlist, **tanpa Hermes**.
- **Memori & belajar antar sesi**, **cron**, **delegasi** — fondasi yang sudah ada, kini dipakai dengan benar.

Batas realistis: kualitas penyelesaian tugas sulit **berbanding lurus dengan kekuatan model berat** (§3). Jarvis memahami maksud & berusaha menyelesaikannya dengan tool yang tersedia — bukan jaminan sukses 100%; ia bisa coba ulang, dan aksi destruktif tetap minta konfirmasi.
