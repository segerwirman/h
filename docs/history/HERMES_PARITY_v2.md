# JARVIS_HERMES_PARITY v2 — Spesifikasi Implementasi

> # ⚠️ ARSIP — DOKUMEN HISTORIS
>
> Referensi `hermes-agent-main/` **telah dihapus** pada 2026-07-27
> (arsip: `hermes-agent-main-backup-20260727.tar.gz`, 69 MB, disimpan di
> luar repo).
>
> Seluruh kemampuan yang dijelaskan di sini **sudah diimplementasi native**
> di `jarvis/agent/` — 82 tool terdaftar lewat auto-discovery, dan paket itu
> tidak mengimpor apa pun dari referensi Hermes.
>
> Dokumen ini disimpan untuk **konteks keputusan desain**, bukan sebagai
> panduan implementasi. Setiap perintah `grep hermes-agent-main/...` di
> bawah tidak lagi bisa dijalankan.
>
> Verifikasi sebelum penghapusan: nol impor, nol path runtime, nol I/O ke
> folder tersebut, dan `skills.hub_sources` kosong dengan `skill_hub`
> memblokir substring `hermes` secara eksplisit. Detail:
> [`../AUDIT_FINDINGS_CODE.md`](../AUDIT_FINDINGS_CODE.md) §5.

> **Untuk: Claude Code (IDE).** Baca seluruhnya sebelum menulis kode.
>
> **Basis:** `AUDIT_REPORT.md` (2026-07-17) + 19 screenshot UI Hermes.
> **Repo:** `e:\jarvis agent\mk50hybrid` (lokal, bukan git repo)
> **Referensi:** `hermes-agent-main/` di dalam repo target — **READ-ONLY**
>
> **v2 menggantikan `JARVIS_HERMES_PARITY.md`.** Versi lama ditulis sebelum audit
> dan berisi asumsi yang sekarang terbukti salah. Buang yang lama.

---

## 0. KEPUTUSAN YANG SUDAH DIAMBIL USER

Jangan tanya ulang. Ini sudah final:

| # | Pertanyaan | Keputusan |
|---|---|---|
| 1 | Lokasi panel baru | **Ikon di ActionPanel + ContentStage** — lihat §0.1 (REVISI) |
| 2 | Panel Messaging | **Pakai HermesBridge** — Jarvis mengatur config Hermes lewat bridge |
| 3 | Fase pertama | **Skills** (counter, learned, toggle) |
| 4 | Provider account | **OpenAI OAuth (ChatGPT) wajib ada** + image gen `gpt-image-2` — lihat §7.3 |

### 0.1 REVISI — Rail kiri dibatalkan

User awalnya memilih rail navigasi kiri. Setelah audit §A.3 menemukan konflik
dengan SYS MONITOR rail (`ui.py:2046`, juga 148px, juga kiri), **user mengubah
pilihan ke ikon panel.**

➡ **Konflik §2.2 BATAL. Bukan lagi blocker.**
➡ Panel baru diakses lewat **ikon di ActionPanel** (`jarvis/ui/actionpanel.py`).
➡ **JANGAN buat `navrail.py`. JANGAN sentuh `ui.py`.**

Ini keputusan yang bagus — ActionPanel sudah punya pola GlyphButton + sinyal
`*_clicked` (`window.py:365-381`), jadi penambahan bersifat additive murni.

---

## 1. APA YANG BERUBAH DARI AUDIT

Audit mengubah tiga hal fundamental. Pahami ini dulu:

### 1.1 Skenario (a) — fondasi SUDAH ADA

Jarvis punya: `registry.py` (auto-discovery + gate `available()`), `loop.py`
(planner+executor, reflect async), `skills.py` (SKILL.md + frontmatter),
`memory_store.py` (FTS5 + embedding + hybrid), `cron.py`, `delegate.py`.

➡ **Ini BUKAN proyek membangun agent framework.** Ini proyek menambah
**lapisan manajemen** di atas fondasi yang sudah jalan (audit §D.3).

❌ JANGAN tulis ulang registry, loop, skills, atau memory.
✅ Tambahkan: usage telemetry, provenance/learned, toggle, grouping, UI.

### 1.2 HermesBridge mengubah scope Messaging drastis

Jarvis **sudah** terintegrasi Hermes via subprocess CLI
(`jarvis/integrations/hermes/bridge.py`, `actions/hermes_action.py`,
CircuitBreaker, Tier 2 `hermes send` / Tier 3 `hermes -z`).

Hermes sudah menjalankan 22 platform adapter. Jarvis **tidak perlu** menulis
satu pun adapter.

➡ Panel Messaging Jarvis = **editor untuk `~/.hermes/config.yaml`** + penampil
status, dieksekusi lewat bridge. Bukan implementasi platform.

### 1.3 Data mentah counter sudah ada

`registry.execute()` sudah menulis JSONL ke `data/logs/tools.jsonl` setiap
eksekusi. Counter `×901` tinggal agregasi + tampilan (audit §D.4).

Skill usage (`×44`) memang belum ada — itu yang perlu dibangun.

---

## 2. ATURAN MUTLAK

### 2.1 Zona FROZEN

| Path | Status | Alasan |
|---|---|---|
| `ui.py` (root, ~105 KB) | **FROZEN** | UI legacy Mark XLVIII, masih diimport `main.py` |
| `main.py` (root, ~76 KB) | **FROZEN** | Pipeline Gemini Live legacy, masih dipakai |
| `jarvis/ui/theme.py` | **FROZEN** | Design token — **BACA** untuk ambil warna/spacing, jangan ubah |
| Voice pipeline (TTS/STT/wake-word) | **FROZEN** | Suara Jarvis milik user |
| `jarvis/ui/window.py` | **SEMI-FROZEN** | Boleh tambah rail + register panel. JANGAN refactor. |
| `jarvis/ui/actionpanel.py` | **SEMI-FROZEN** | Jangan ubah. Rail baru terpisah. |
| `hermes-agent-main/` | **READ-ONLY** | Referensi. Jangan edit, jangan jalankan. |

**Aturan:** Ragu apakah FROZEN → anggap FROZEN, tanya user.
Perubahan pada file FROZEN yang "terasa perlu" → tulis usulan di
`MIGRATION_NOTES.md`, jangan lakukan.

### 2.2 ✅ Konflik rail — SELESAI (tidak perlu tindakan)

Audit §A.3 menemukan `ui.py:2046` sudah memakai rail kiri 148px untuk
SYS MONITOR. User **mengubah pilihan ke ikon panel** (§0.1), jadi tidak ada
tabrakan.

- ❌ JANGAN buat rail navigasi kiri.
- ❌ JANGAN sentuh `ui.py` atau SYS MONITOR.
- ✅ Tambah ikon di ActionPanel (§5.1).

### 2.3 Identitas: salin fungsi, bukan branding

| Di Hermes | Untuk Jarvis |
|---|---|
| Teks "Hermes" di UI | → "Jarvis" |
| Personality `Kawaii` | → persona dari `jarvis/agent/core/prompt.txt` |
| Tema Nous/Midnight/Ember/Mono/Cyberpunk/Slate | → **hilangkan**; Jarvis punya `theme.py` |
| TTS Edge / `en-US-AriaNeural` | → config voice Jarvis yang berjalan sekarang |
| Kartu "Nous Portal [RECOMMENDED]" | → hilangkan |
| "Hermes Cloud" (Gateway) | → hilangkan |
| Pet/petdex mascot | → hilangkan (tanya user kalau mau) |
| Skill `hermes-gateway-maintenance`, `hermes-agent-skill-authoring` | → jangan port |
| Toolset `hermes-cli` | → toolset Jarvis |

**Catatan khusus panel Messaging:** karena panel ini mengedit config Hermes
yang sebenarnya, nama platform (Telegram/Discord/dst) **tetap apa adanya** —
itu nama produk pihak ketiga, bukan branding Hermes.

---

## 3. ARSITEKTUR TARGET

```
┌──────────────────────────────────────────────────────────────┐
│ jarvis/ui/window.py  (SEMI-FROZEN — hanya tambah wiring)     │
│                                                              │
│   ┌──────────────────────────────────┐                       │
│   │ ContentStage (SUDAH ADA)         │                       │
│   │  stage.register("capabilities",…)│                       │
│   │  stage.register("messaging",…)   │                       │
│   │  stage.register("settings",…)    │                       │
│   └──────────────▲───────────────────┘                       │
│                  │ stage.show(nama)                          │
│   ┌──────────────┴───────────────────┐                       │
│   │ ActionPanel (SUDAH ADA)          │  ← floating bottom    │
│   │ [vision][upload][spotify][⚙]     │                       │
│   │        + [capa][msg]  ← BARU     │                       │
│   └──────────────────────────────────┘                       │
└──────────────────────────────────────────────────────────────┘
            │                    │                    │
            ▼                    ▼                    ▼
┌────────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ CapabilityService  │ │ MessagingService │ │ SettingsService  │
│ (BARU)             │ │ (BARU)           │ │ (BARU)           │
└─────────┬──────────┘ └────────┬─────────┘ └────────┬─────────┘
          │                     │                    │
          ▼                     ▼                    ▼
┌────────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ registry.py  ✅ADA │ │ HermesBridge ✅ADA│ │ config.py   ✅ADA│
│ skills.py    ✅ADA │ │ → ~/.hermes/     │ │ → config.yaml    │
│ tools.jsonl  ✅ADA │ │    config.yaml   │ │                  │
│ usage.json   BARU  │ │                  │ │                  │
└────────────────────┘ └──────────────────┘ └──────────────────┘
```

**Prinsip:** service layer baru membungkus yang sudah ada. UI bicara ke service,
tidak pernah langsung ke registry/bridge/config.

---

## 4. FASE 1 — FONDASI SKILLS (prioritas user)

### 4.1 Usage Counter

**Pola Hermes** (audit §B.4): sidecar JSON `~/.hermes/skills/.usage.json`,
atomic write (tempfile + `os.replace`), best-effort, `usage` = use + view + patch.

**Untuk Jarvis:** `jarvis/agent/skills_data/.usage.json`

```python
# jarvis/agent/skill_usage.py  (BARU)
"""Sidecar telemetry untuk skill. Best-effort — kegagalan tidak boleh
mengganggu eksekusi skill."""

from pathlib import Path
import json, os, tempfile, time

SIDECAR = Path("jarvis/agent/skills_data/.usage.json")

# Struktur:
# {
#   "browser-media-playback": {
#     "use": 40, "view": 3, "patch": 1,
#     "last_used": 1752700000,
#     "is_agent_created": false,     # ← sumber badge "learned"
#     "pinned": false,
#     "lifecycle": "active"          # active | stale | archived
#   }
# }

def bump(name: str, kind: str) -> None:
    """kind: use | view | patch. Tidak pernah raise."""
    ...

def usage_of(name: str) -> int:
    """Total = use + view + patch. Sesuai Hermes."""
    ...

def _atomic_write(data: dict) -> None:
    """tempfile + os.replace — aman dari corrupt saat crash."""
    ...
```

**Aturan keras:**
- `bump()` dipanggil **setelah** skill berhasil dipakai, bukan saat dipanggil.
- Semua operasi dibungkus try/except. Sidecar rusak → mulai dari kosong,
  jangan crash.
- Counter `×N` hanya tampil kalau `> 0` (lihat img 2: `airtable` dst tanpa counter).

### 4.2 Provenance & Badge "learned"

**Temuan audit §B.5 — ini penting dan mudah salah:**

> Skill yang dibuat lewat `skill_manage` ditandai **eksplisit** di sidecar
> (`is_agent_created`) — **tidak diinferensi dari lokasi file.**

Artinya: jangan tebak "learned" dari path atau tanggal file. Tandai saat
pembuatan.

```python
# Tiga sumber, sama seperti Hermes:
#   bundled → ikut repo Jarvis          → tanpa badge
#   hub     → di-install dari luar      → badge "hub"
#   agent   → dibuat agent via manage   → badge "learned"  ← is_agent_created=True
```

**Integrasi:** di `jarvis/agent/tools/skill_tools.py`, pada aksi `manage`
dengan `action="create"` → set `is_agent_created=True` di sidecar.

### 4.3 Toggle Enable/Disable

**Pola Hermes** (audit §B.3): `~/.hermes/config.yaml` → `skills.disabled: [...]`

**Untuk Jarvis:** `config.yaml` (sudah ada, loader `jarvis/core/config.py`
dengan pola `config.get("a.b.c", default)`).

```yaml
# config.yaml — tambahkan blok baru
skills:
  disabled: []        # daftar nama skill yang dimatikan

tools:
  disabled_groups: [] # daftar id grup tool yang dimatikan
```

**Penegakan — INI BAGIAN PALING PENTING:**

```python
# jarvis/agent/skills.py — modifikasi fungsi yang menyusun system prompt
def list_for_prompt() -> list[Skill]:
    disabled = set(config.get("skills.disabled", []))
    return [s for s in all_skills() if s.name not in disabled]
```

Skill yang di-disable: `name` + `description`-nya **tidak masuk system prompt
sama sekali**. Bukan masuk lalu ditolak — tidak masuk.

### 4.4 Kategori

Jarvis baru punya 1 skill (`laporan-harian`), belum ada kategori.

Tambahkan field opsional di frontmatter SKILL.md:
```yaml
---
name: laporan-harian
description: ...
triggers: [...]
category: Productivity     # ← BARU, opsional
---
```
Skill tanpa `category` → tampil sebagai `General` (sesuai Hermes, lihat
`computer-use` di img 1).

**Kategori dari screenshot** (untuk validasi/autocomplete): Media,
Software-Development, Mlops, Autonomous-AI-Agents, Browser, General, Github,
Creative, Research, Productivity, Data-Science, Email, Note-Taking, Smart-Home,
Automation, Hermes.

⚠ Kategori `Hermes` → jangan pakai untuk Jarvis.

### 4.5 Verifikasi Fase 1 (tanpa UI)

Tulis test yang membuktikan:
- [ ] `bump("x", "use")` → `usage_of("x")` naik
- [ ] Sidecar corrupt → tidak crash, mulai kosong
- [ ] Skill dibuat via `skill_manage` → `is_agent_created=True`
- [ ] `config.yaml: skills.disabled: [laporan-harian]` → skill itu **tidak ada**
      di system prompt sesi baru
- [ ] Skill enabled → muncul di system prompt

**Belum ada UI di fase ini.** Buktikan logika dulu.

---

## 5. FASE 2 — IKON PANEL + PANEL CAPABILITIES

> **Tidak ada prasyarat.** Konflik rail sudah batal (§0.1, §2.2).

### 5.1 Ikon di ActionPanel

Audit §A.3: ActionPanel = *floating bottom-center icon bar* dengan
vision · upload · spotify · settings. Sinyal `*_clicked` di `window.py:365-381`.

**Ikuti pola yang sudah ada — jangan bikin pola baru.**

```python
# jarvis/ui/actionpanel.py — TAMBAH, jangan ubah yang ada
capabilities_clicked = pyqtSignal()
messaging_clicked    = pyqtSignal()
# settings_clicked SUDAH ADA — pakai itu untuk panel Settings
```

**Integrasi ke window.py** — minimal:
```python
self.action_panel.capabilities_clicked.connect(
    lambda: self.stage.show("capabilities"))
self.action_panel.messaging_clicked.connect(
    lambda: self.stage.show("messaging"))
```

⚠ **`settings_clicked` sudah ada dan mungkin sudah terhubung ke sesuatu.**
Cek dulu (`window.py:365-381`). Kalau sudah ada handler settings lama:
lapor ke user — mau diganti panel Settings baru, atau ikon terpisah?
**Jangan diam-diam ganti perilaku tombol yang sudah dipakai.**

**Aturan visual:**
- Pakai **GlyphButton** yang sudah ada. Jangan bikin komponen tombol baru.
- Ambil token dari `jarvis/ui/theme.py`. Jangan hardcode warna/spacing.
- Ikon baru: gaya, ukuran, stroke, hover/active **identik** dengan ikon
  vision/upload/spotify yang sudah ada.
- Jangan impor library ikon baru untuk 2 ikon.

**Referensi ikon Hermes (img 1):** Capabilities = puzzle/chip, Messaging =
chat bubble. Ambil *konsepnya*, gambar ulang dengan gaya Jarvis.

### 5.2 Registrasi panel

`ContentStage` sudah ada (audit §A.4): dict `{nama: QWidget}` + cross-fade 250ms
+ state `EMPTY/LOADING/ACTIVE/ERROR`.

```python
stage.register("capabilities", CapabilitiesPanel(...))
stage.register("messaging",    MessagingPanel(...))
stage.register("settings",     SettingsPanel(...))
```

Manfaatkan state `LOADING` — panel Capabilities perlu baca sidecar + agregasi
JSONL, jangan blok UI thread.

### 5.3 Layout Panel Capabilities

Dari img 1–4 — 3 pane:

```
┌──────────────────────────────┬─────────────────────────┐
│ [search: Try "github"]       │  browser-media-playback │
│                              │  [Media] [Learned]      │
│ Skills 80 | Tools 21 | MCP | │                         │
│ Browse Hub                   │  <deskripsi>            │
│                              │                         │
│ ↓ Most used            [⋮]   │  Edit    Archive        │
│ ┌──────────────────────────┐ │         ^^^^^^^ merah   │
│ │ browser-media-playback   │ │                         │
│ │ Media  learned    ×44 ⬤ │ │                         │
│ ├──────────────────────────┤ │                         │
│ │ ...                      │ │                         │
│ └──────────────────────────┘ │                         │
│                              │                         │
│    "Changes apply to new sessions."  ← abu, kanan-bawah │
└──────────────────────────────┴─────────────────────────┘
```

**Urutan item** (dari img 1–2): yang punya counter di atas (desc), lalu sisanya
**alfabetis**. Bukti: setelah `hermes-gateway-maintenance ×1` langsung
`airtable`, `architecture-diagram`, `arxiv`, `ascii-art`, `ascii-video`...

**Search placeholder** berubah per tab: `Try "github"` (Skills), `Try "patch"` (Tools).

### 5.4 Tab Tools — Grouping

⚠ **Audit §C: "Toolsets/grup tool per skenario → Belum ada."** Jarvis memuat
semua tool yang lolos gate `available()`, tanpa grouping.

Jadi grup harus **dibuat**. Petakan 19 modul tool Jarvis ke grup:

```python
# jarvis/agent/toolgroups.py  (BARU)
TOOL_GROUPS = [
    ToolGroup(
        id="file_operations",
        name="File Operations",
        subtitle="read, write, patch, search",
        modules=["file_ops"],          # ← modul di jarvis/agent/tools/
    ),
    ToolGroup(
        id="terminal_processes",
        name="Terminal & Processes",
        subtitle="terminal, process",
        modules=["terminal"],
    ),
    # ... dst
]
```

**Tugas Claude Code:** buka `jarvis/agent/tools/`, petakan 19 modul nyata ke
grup. Jangan pakai daftar 21 grup Hermes mentah-mentah — Jarvis mungkin tidak
punya semuanya, dan mungkin punya yang Hermes tidak punya (audit menyebut
modul `food` — tidak ada di Hermes).

**Referensi 21 grup Hermes (img 4)** — untuk penamaan & subtitle, bukan untuk
disalin buta:

| Nama Grup | Subtitle | Default |
|---|---|---|
| File Operations | `read, write, patch, search` | ON |
| Terminal & Processes | `terminal, process` | ON |
| Browser Automation | `navigate, click, type, scroll` | ON |
| Computer Use (macOS/Windows/Linux) | `background desktop control via cua-driver` | ON |
| Skills | `list, view, manage` | ON |
| Web Search & Scraping | `web_search, web_extract` | ON |
| Task Planning | `todo` | ON |
| Clarifying Questions | `clarify` | ON |
| Session Search | `search past conversations` | ON |
| Code Execution | `execute_code` | ON |
| Vision / Image Analysis | `vision_analyze` | ON |
| Memory | `persistent memory across sessions` | ON |
| Task Delegation | `delegate_task` | ON |
| Cron Jobs | `create/list/update/pause/resume/run, with optional attached skills` | ON |
| Home Assistant | `smart home device control` | ON |
| Image Generation | `image_generate` | ON |
| Spotify | `playback, search, playlists, library` | ON |
| Text-to-Speech | `text_to_speech` | ON |
| Video Analysis | `video_analyze (requires video-capable model)` | **OFF** |
| Video Generation | `video_generate (text/image/reference)` | **OFF** |
| X (Twitter) Search | `x_search (requires xAI OAuth or XAI_API_KEY)` | **OFF** |

### 5.5 `enabled` vs `available` — dua konsep berbeda

Jarvis sudah punya gate `available()` di registry (audit §A.6).

```
available=False  → tool tidak bisa dipakai (kredensial hilang, model tak dukung)
                 → render ABU, toggle MATI & tidak bisa diklik
                 → contoh: Video Analysis, X Search di img 4

enabled=False    → user sengaja mematikan
                 → render NORMAL, toggle mati tapi bisa diklik
```

Jangan campur keduanya. `available()` sudah ada — **pakai**, jangan bikin ulang.

### 5.6 Counter Tool (×901)

Data mentah sudah ada: `data/logs/tools.jsonl` (audit §D.4).

```python
# jarvis/agent/tool_usage.py  (BARU)
def aggregate_from_jsonl() -> dict[str, int]:
    """Baca tools.jsonl → {tool_name: count}. Hanya yang sukses."""
```

**Performa:** JSONL akan tumbuh besar. Jangan baca ulang tiap render.
Cache + baca incremental (simpan byte offset terakhir), atau agregasi
periodik ke sidecar. Ukur dulu — kalau file masih kecil, baca penuh boleh.

**Detail pane Tools** (img 4) — chip monospace per tool:
```
File Operations
read, write, patch, search

[patch ×39] [read_file ×682] [search_files ×46] [write_file ×134]
```

### 5.7 Tab MCP & Browse Hub

Audit tidak menyebut MCP di Jarvis sama sekali. **Kemungkinan besar belum ada.**

**Jangan bangun di fase ini.** Render tab dengan empty state jujur:
> "MCP belum tersedia di Jarvis."

Lapor ke user — ini scope terpisah, bukan bagian dari "toggle panel".

Sama untuk Browse Hub (skill hub eksternal — audit §C: "Belum ada").

### 5.8 Penegakan Toggle Tool

```python
# jarvis/agent/loop.py — di titik penyusunan tool schema
def build_tool_schemas(session) -> list[dict]:
    snapshot = session.capability_snapshot   # diambil saat sesi DIBUAT
    schemas = []
    for group in toolgroups.all():
        if not group.available:      continue
        if group.id in snapshot.disabled_groups: continue
        for tool in group.tools():
            schemas.append(tool.schema())
    return schemas
```

**Kontrak "Changes apply to new sessions."** (teks itu ada di img 1–4):
snapshot capability diambil saat sesi dibuat, tidak berubah di tengah sesi.

---

## 6. FASE 3 — PANEL MESSAGING (via HermesBridge)

> **Keputusan user:** Jarvis mengatur config Hermes lewat bridge.

### 6.1 Prinsip

Jarvis **tidak** menulis adapter platform. Hermes sudah punya 22 (audit §B.6:
`hermes_cli/platforms.py` → `PLATFORMS: OrderedDict[key → PlatformInfo]`,
`gateway/platforms/base.py` ABC).

Panel Jarvis = **editor `~/.hermes/config.yaml`** + penampil status.

### 6.2 Yang harus di-audit dulu

Bridge sekarang cuma `hermes send` (Tier 2) + `hermes -z` (Tier 3) — keduanya
untuk *mengirim pesan*, bukan *mengatur config*.

**Cari tahu:**
1. Apakah Hermes CLI punya perintah config? (`hermes config get/set`?)
   → Baca `hermes-agent-main/cli.py` (757 KB — grep, jangan baca penuh).
2. Kalau tidak ada → Jarvis baca/tulis `~/.hermes/config.yaml` langsung
   (YAML, aman diedit), lalu bridge dipakai untuk reload/restart gateway.
3. Bagaimana cara tahu status platform (Connected/Disabled/Needs setup)?
   → Ada endpoint? Perintah CLI? Atau inferensi dari config?

**Lapor temuan sebelum coding.**

### 6.3 Field config-driven

Screenshot membuktikan field **berbeda per platform**:
- Telegram (img 6): Bot token · Allowed user IDs · Allow all users · Home channel ID · Home channel display name · `ADVANCED (1)`
- Discord (img 5): Bot token · Allowed Discord user IDs · `ADVANCED (4)`
- WhatsApp (img 7): **tanpa token** — *"This platform does not need a token here"* · `ADVANCED (3)`

➡ Harus config-driven. Ambil schema dari `hermes_cli/platforms.py`, jangan
hardcode 30 platform di UI Jarvis.

### 6.4 ⚠ KEAMANAN — Allowlist Wajib

Jarvis punya akses terminal + desktop + file. Bot messaging tanpa allowlist =
menyerahkan komputer user ke internet.

**Aturan:**
- Platform **tidak boleh** diaktifkan kalau `Allowed user IDs` kosong.
- `Allow all users = true` → tampilkan peringatan merah eksplisit, minta
  konfirmasi kedua. Field ini bertuliskan "(dev only)" di UI Hermes — hormati itu.
- Master toggle disabled selama allowlist kosong.

Ini bukan saran. Ini syarat.

### 6.5 UI

- List: nama + status dot (biru=connected, abu=belum) — img 5–7
- Detail: REQUIRED / RECOMMENDED / `ADVANCED (N)` collapsible
- Secret tersimpan: mask `•••` + badge `Saved` biru + tombol 🗑
- Field kosong: placeholder, tanpa 🗑
- Bawah: master toggle + `Save changes`

---

## 7. FASE 4 — PANEL SETTINGS

13 seksi (img 8–19). **Banyak yang sudah ada di Jarvis** — panel ini sebagian
besar UI untuk `config.yaml` yang sudah jalan.

| Seksi | Kondisi Jarvis | Tindakan |
|---|---|---|
| Model | Ada (`providers.py`, `settings_providers.py` UI) | Bungkus yang ada |
| Chat | Persona di `core/prompt.txt` | **JANGAN pakai "Kawaii"** |
| Appearance | `theme.py` + `config.yaml` | **Hilangkan theme picker Hermes** |
| Workspace | Sebagian ada | Petakan ke `config.yaml` |
| Safety | Registry sudah punya konfirmasi | Bungkus |
| Memory & Context | Ada (`memory_store.py`) | Ekspos knob budget/compression |
| Voice | **FROZEN** | Hanya baca/tulis config yang ada |
| Advanced | Sebagian ada | Petakan |
| Notifications | Perlu cek | Audit dulu |
| Providers | Ada (`providers.json`, `api_keys.json`, keyring) | Bungkus |
| Gateway | Tidak ada padanan | **Hilangkan** (Hermes Cloud = layanan Nous) |
| Tools & Keys | Ada sebagian | Bungkus |
| Archived Chats | Perlu cek | Audit dulu |
| About | — | Versi Jarvis, bukan `v0.18.2` |

### 7.1 Auxiliary Models (img 8)

Audit §C: "**Ada sebagian** — Jarvis multi-provider tapi tanpa konsep aux-task
terpisah/fallback berantai."

Hermes punya 8 slot: Vision · Web extract · Compression · Skills hub ·
Approval · MCP · Title gen · Curator. Pola: `auto · use main model` + aksi
`Set to main` / `Change`.

➡ Ini **fitur baru**, bukan pembungkus. Scope-nya nyata. Kerjakan setelah
Fase 1–3 selesai, atau tanya user apakah perlu sama sekali.

**Mixture of Agents** — tanya user. Kompleks, mungkin tidak perlu.

### 7.2 Voice — batas keras

Panel Voice **hanya** baca/tulis config voice Jarvis yang sudah ada.

- Dropdown TTS Provider → isi dengan provider yang **Jarvis punya**.
  Kalau Jarvis tidak punya konsep "provider" → **hilangkan dropdown**.
- Default value = konfigurasi Jarvis **yang berjalan sekarang**.
  Bukan `Edge`, bukan `en-US-AriaNeural`.
- ❌ JANGAN bikin pipeline voice baru. ❌ JANGAN ubah kode voice.

---

### 7.3 Providers — OpenAI OAuth + Image Generation (WAJIB)

> **Keputusan user #4.** Ini requirement, bukan opsional.

#### 7.3.1 ⚠ BACA INI DULU — OAuth ≠ API key

**Ini bukan satu jalur. Ini dua jalur berbeda, dan mudah salah.**

| | OpenAI OAuth (ChatGPT) | OpenAI API key |
|---|---|---|
| Autentikasi | Login browser | Paste key |
| Produk | Langganan ChatGPT/Codex | Platform API (`platform.openai.com`) |
| Billing | Langganan bulanan | Usage tier (bayar per pakai) |
| Akses LLM chat | ✅ Ya | ✅ Ya |
| Akses `gpt-image-2` | ⚠ **Belum terverifikasi** | ✅ Ya (Tier 1+) |

**Fakta terverifikasi dari docs OpenAI (17 Juli 2026):**
- Model string: `gpt-image-2`, snapshot `gpt-image-2-2026-04-21`
- Rilis 21 April 2026 (ChatGPT Images 2.0), menggantikan DALL-E 3 & GPT Image 1.5
- Endpoint: `v1/images/generations` (generate) & `v1/images/edits` (edit)
- Modalitas: input Text+Image → output Image
- Rate limit **Free: Not supported**. Tier 1: 5 IPM. Tier 5: 250 IPM.
- Dua tier kualitas: **Instant** & **Thinking**
- Tidak support: streaming, function calling, structured output

➡ **Rate limit berbasis usage tier = ini jalur API key, bukan jalur langganan.**

**Bukti dari Hermes sendiri (img 17 & 18):** OAuth account dan API key adalah
**dua halaman terpisah**. Entry Anthropic OAuth bahkan berlabel *"Required
Extra Usage Credits to Use Subscription"* — bukti bahwa OAuth langganan ≠ akses
API penuh.

**Kesimpulan sementara:** OAuth kemungkinan besar hanya memberi **LLM chat**.
Image gen `gpt-image-2` kemungkinan butuh **API key berbayar**.

#### 7.3.2 Tugas verifikasi — JANGAN ASUMSIKAN

**Sebelum coding, baca `hermes-agent-main`:**

```bash
# grep, jangan baca cli.py penuh (757 KB)
grep -rn "oauth" hermes-agent-main/ --include=*.py | head -50
grep -rn "chatgpt\|codex" hermes-agent-main/ --include=*.py | head -50
grep -rn "gpt-image\|images/generations" hermes-agent-main/ | head -20
```

**Jawab:**
1. Bagaimana Hermes implementasi OpenAI OAuth? (flow, token store, refresh)
2. Endpoint apa yang dipakai OAuth? (Codex backend? `api.openai.com`?)
3. **Apakah OAuth Hermes bisa akses image generation?** Kalau ya, lewat mana?
4. Bagaimana Hermes memisahkan credential OAuth vs API key?

**Lapor temuan ke user sebelum coding.** Kalau ternyata OAuth memang tidak bisa
image gen — user perlu tahu bahwa API key berbayar dibutuhkan, sebelum waktu
terbuang.

#### 7.3.3 Desain — Dua Jalur Independen

Apa pun hasil verifikasi, **rancang dua jalur terpisah**. Ini benar di kedua
skenario, jadi tidak ada waktu terbuang.

```yaml
# config.yaml
providers:
  openai_oauth:
    enabled: false
    # token di keyring (jarvis/core/secrets_store.py SUDAH ADA), BUKAN di YAML
    capabilities: [chat]        # diisi setelah verifikasi §7.3.2

  openai_api:
    enabled: false
    # key di keyring / config/api_keys.json (SUDAH ADA)
    capabilities: [chat, image, vision]

image_generation:
  provider: openai_api          # ← jalur mana yang dipakai
  model: gpt-image-2
  quality: instant              # instant | thinking
  size: 1024x1024               # sampai 4096x4096
```

**Aturan:**
- Jarvis sudah punya `secrets_store.py` (keyring) + `config/api_keys.json` +
  `config/providers.json` (audit §A.5). **Pakai itu.** Jangan bikin store baru.
- Token OAuth **tidak boleh** masuk `config.yaml` (file itu plaintext & mungkin
  ter-commit). Keyring saja.
- `image_gen` tool (`jarvis/agent/tools/image_gen.py` — SUDAH ADA) → tambah
  `available()` gate: return False kalau tidak ada jalur yang punya
  capability `image`. Registry sudah support pola ini (audit §A.6).

#### 7.3.4 UI (img 17)

```
🔑 Connect an account                    Have an API key instead?
Sign in with a subscription — no API key to copy.

Connected
OpenAI OAuth (ChatGPT)          [✓ Connected]           ›  🗑
Opens a verification page in your browser — Jarvis connects
automatically
```

- ❌ **Hilangkan kartu "Nous Portal [RECOMMENDED]"** — itu branding Nous.
- Teks "Hermes connects automatically" → "Jarvis connects automatically".
- Kalau OAuth **tidak** bisa image gen (hasil §7.3.2): tampilkan hint jujur
  di UI, mis. *"OAuth: chat saja. Image generation butuh API key."*
  **Jangan diam** — user akan bingung kenapa image gen tidak jalan.

#### 7.3.5 Flow OAuth

Screenshot bilang: *"Opens a verification page in your browser — Hermes
connects automatically"*.

Jarvis punya QtWebEngine (`jarvis/browser/embed.py`). **Tapi:** login OAuth di
webview embedded sering diblokir provider (deteksi user-agent / kebijakan
"embedded browser"). Hermes sendiri memakai **browser eksternal**, bukan
embedded — itu sebabnya teksnya "opens a verification page in your browser".

➡ Pakai `webbrowser.open()` + **loopback server lokal** untuk callback.
Ini pola OAuth desktop standar (PKCE + `http://localhost:PORT/callback`).
Jangan paksakan lewat QtWebEngine.

## 8. FASE 5 — CURATOR (opsional)

Audit §B.5 menemukan: Hermes punya `agent/curator.py` — maintenance background
untuk skill hasil belajar. Lifecycle `active → stale → archived` berbasis
timestamp dari sidecar. Pinned bypass. **Tidak pernah delete, hanya archive.**

Jarvis punya `reflect.py` (belajar pasca-task) tapi tanpa lifecycle skill
(audit §C).

Ini pasangan alami dari badge "learned" — tanpa curator, skill hasil belajar
menumpuk selamanya. Tapi bukan prasyarat.

**Tanya user** apakah perlu. Kalau ya, `lifecycle` sudah disiapkan di sidecar (§4.1).

---

## 9. URUTAN KERJA

Satu fase → commit → lapor → lanjut. Jangan borong.

- [ ] **Fase 0** — ~~Konflik rail~~ **BATAL** (§0.1). Langsung Fase 1.
- [ ] **Fase 1** — Skills: usage counter, provenance, toggle, kategori.
      Test lulus, **belum ada UI**.
- [ ] **Fase 2a** — Ikon ActionPanel + registrasi 3 panel ke ContentStage.
      Panel kosong. Cek `settings_clicked` yang sudah ada (§5.1).
- [ ] **Fase 2b** — Panel Capabilities: tab Skills (counter, learned, toggle,
      search, sort, detail pane).
- [ ] **Fase 2c** — Tab Tools: grouping 19 modul, counter dari JSONL,
      enabled vs available, chip detail.
- [ ] **Fase 2d** — Tab MCP & Browse Hub: empty state jujur. **Lapor.**
- [ ] **Fase 3** — Panel Messaging via bridge. Audit CLI dulu (§6.2), **lapor**,
      baru coding. Allowlist wajib (§6.4).
- [ ] **Fase 4** — Panel Settings, seksi per seksi.
- [ ] **Fase 5** — Auxiliary models / Curator — **tanya user dulu**.

---

## 10. VERIFIKASI AKHIR

- [ ] `ui.py`, `main.py`, `theme.py`, voice → **tidak berubah** (diff kosong)
- [ ] UI Jarvis lama → identik
- [ ] Suara Jarvis → identik
- [ ] Skill disabled → **tidak ada** di system prompt sesi baru
- [ ] Tool group disabled → **tidak ada** di schema LLM sesi baru
- [ ] Counter naik setelah pemakaian nyata (bukan percobaan gagal)
- [ ] Skill dibuat agent → badge `learned` muncul
- [ ] Sidecar corrupt → tidak crash
- [ ] Toggle bertahan setelah restart
- [ ] Platform messaging tanpa allowlist → **tidak bisa aktif**
- [ ] Tidak ada string "Hermes"/"Nous"/"Kawaii"/"Edge"/"AriaNeural" di UI Jarvis
- [ ] `MIGRATION_NOTES.md` lengkap

---

## 11. ANTI-PATTERN

- ❌ **Toggle kosmetik** — kalau tidak mengubah tool schema / system prompt, itu bohong.
- ❌ **Menulis ulang registry/loop/skills** — sudah ada, bungkus saja (audit §D.3).
- ❌ **Menulis adapter platform** — Hermes sudah punya 22, pakai bridge.
- ❌ **Menyalin 21 grup Hermes buta** — petakan ke 19 modul Jarvis yang nyata.
- ❌ **Infer "learned" dari path/tanggal** — tandai eksplisit (§4.2, audit §B.5).
- ❌ **Baca JSONL penuh tiap render** — cache/incremental (§5.6).
- ❌ **Load semua skill body ke context** — hanya name+description (sudah benar
      di `skills.py`, jangan rusak).
- ❌ **Salin tema/voice Hermes** — melanggar §2.1.
- ❌ **Sentuh `ui.py` / SYS MONITOR** — tidak perlu, rail batal (§0.1).
- ❌ **Bikin `navrail.py`** — user pilih ikon panel.
- ❌ **Ganti diam-diam handler `settings_clicked`** yang sudah ada (§5.1).
- ❌ **Asumsikan OAuth bisa image gen** — verifikasi dulu (§7.3.2).
- ❌ **Simpan token OAuth di `config.yaml`** — keyring saja (§7.3.3).
- ❌ **Platform aktif tanpa allowlist** (§6.4).
- ❌ **Kerjakan semua fase sekaligus.**

---

## 12. YANG MASIH HARUS DITANYAKAN

1. ~~Konflik rail kiri~~ — **SELESAI**, user pilih ikon panel (§0.1).
1b. **`settings_clicked` sudah ada?** Kalau sudah punya handler — ganti
    atau ikon terpisah? (§5.1) **Cek saat Fase 2a.**
1c. **OAuth bisa image gen?** Verifikasi ke `hermes-agent-main` (§7.3.2).
    Kalau tidak → user butuh API key berbayar. **Lapor sebelum coding.**
2. **MCP & Browse Hub** — mau di-scope? (§5.7)
3. **Auxiliary models 8 slot** — perlu? (§7.1)
4. **Mixture of Agents** — perlu?
5. **Curator** — perlu? (§8)
6. **Provider list** — Jarvis pakai OpenAI-compatible. Perlu 19+ provider seperti
   Hermes, atau cukup yang dipakai?
7. **Pet/petdex** — user belum ditanya. Asumsi: tidak.

---

## 13. CATATAN UNTUK CLAUDE CODE

- **Spec ini berbasis audit nyata**, bukan tebakan. Path & temuan di dalamnya
  berasal dari `AUDIT_REPORT.md`. Tapi detail implementasi Hermes (nama fungsi,
  signature) tetap **harus diverifikasi** ke `hermes-agent-main`.
- **Yang akurat dari screenshot:** teks UI, label, urutan, subtitle, default,
  daftar platform, 13 seksi settings. Salin persis.
- **Kode nyata menang** atas spec. Bertabrakan → lapor, jangan paksakan.
- **Jarvis sudah punya fondasi.** Tugasnya lapisan manajemen, bukan core.
- **Ragu file FROZEN → anggap FROZEN, tanya.**
- **Salin fungsi Hermes, bukan identitas Hermes.**
