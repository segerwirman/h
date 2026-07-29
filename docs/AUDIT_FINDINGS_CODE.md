# AUDIT_FINDINGS_CODE — Lampiran Teknis

Bukti kode untuk `AUDIT_REPORT.md`. Setiap temuan membawa `file:baris` +
kutipan verbatim. Dokumen ini untuk developer; `AUDIT_REPORT.md` untuk
pembaca umum.

| | |
|---|---|
| **Tanggal** | 2026-07-27 |
| **Metode** | Pembacaan kode langsung di clone lokal (bukan lewat web GitHub) |
| **Commit** | `dc41ef9` (satu-satunya commit), working tree kotor (~55 file termodifikasi) |
| **Dikecualikan** | `hermes-agent-main/` (151 MB, gitignored), `.hermes/`, `__pycache__` |

> **Perubahan status vs audit 2026-07-27 versi web.** Audit sebelumnya menandai
> temuan `[TURUNAN]` karena `jarvis/`, `actions/`, `core/`, `tests/`,
> `dashboard/`, `ui.py`, dan paruh kedua `main.py` tidak terbaca. Semua zona itu
> kini sudah dibaca. Beberapa temuan naik menjadi `[TERBUKTI]`; beberapa
> **dibantah**.

---

## Ringkasan Perubahan Status

| ID | Temuan lama | Status baru |
|---|---|---|
| C-1 | Agent single-flight; lane suara diblokir 900 dtk | 🔴 **DIBANTAH sebagian besar** → diganti C-1′ |
| C-2 | Tidak ada model data tugas | ✅ **TERBUKTI** (dipersempit) |
| H-1 | Duplikasi tiga generasi | ⚠️ **TERBUKTI sebagian**, klaim "dua UI berjalan" **DIBANTAH** |
| H-1b | Bug memori terpisah | 🔴 **TERKONFIRMASI** — bukti empiris isi DB |
| M-7 | "327 tests" tak terverifikasi | ✅ **DIBANTAH** — 859 lulus |
| §7.3 | `core/social_*.py` hanya dirujuk `patch_ui.py` | ❌ **SALAH** — dirujuk `ui.py` |
| §8.5 | Orb `EXECUTING` mati / perlu kerja UI besar | ❌ **SALAH** — state hidup, ring sudah dirender |

---

## [3] GATE AGENT — C-1 DIBANTAH

### 3a. Single-flight? **TIDAK.** Yang ada hanyalah dedup teks-tugas identik.

`jarvis/agent/dispatch.py:24-25` — registri adalah **dict**, bukan flag tunggal:

```python
_active_lock = threading.Lock()
_active: dict[str, "TaskHandle"] = {}
```

Kuncinya teks tugas ter-normalisasi (`dispatch.py:66-67`):

```python
def _key(task: str) -> str:
    return " ".join(task.lower().split())[:160]
```

Penolakan hanya terjadi bila kunci sama (`dispatch.py:217-221`):

```python
    k = _key(task)
    with _active_lock:
        if k in _active:
            _logger.info("agent.dispatch.duplicate", task=task[:80])
            return False
```

Setiap tugas mendapat thread sendiri (`dispatch.py:295`):

```python
    threading.Thread(target=_worker, daemon=True, name="agent-task").start()
```

API konkurensi sudah ada dan dipakai (`dispatch.py:99-114`): `active_count()`,
`active_tasks()`, `cancel_all()`.

**Kesimpulan:** dua tugas **berbeda** sudah bisa berjalan bersamaan hari ini,
tanpa perubahan kode. Yang ditolak hanyalah pengulangan kalimat yang sama
persis — dan itu disengaja, dilaporkan jujur sebagai `busy`
(`jarvis/agent/interaction.py:305-306`):

```python
        if _dispatch.is_active(task):
            return "busy"
```

Tidak ada semaphore, tidak ada `max_concurrent`, tidak ada batas jumlah.
Konsekuensi lain: **tidak ada batas atas sama sekali** — lihat N-3.

### 3b. VoiceToolGate tidak menekan apa pun

Audit lama menyalahartikan namanya. `jarvis/agent/voice_gate.py:1-7`:

```python
"""Ordering gate between Gemini Live transcription and voice tool actions.

Gemini Live can emit a FunctionCall before input transcription is final.  The
gate stores only FunctionCall metadata until ``Transcription.finished`` is
true, then asks the shared tier router for the lane.  It does not touch audio,
VAD, STT, TTS, or playback.
"""
```

Fungsinya: menahan `FunctionCall` sampai transkripsi final, supaya perintah
separuh-ucap tidak dieksekusi. `voice_gate.py:130-135`:

```python
    def _take_ready(self, *, timed_out: bool) -> VoiceToolBatch | None:
        if not self._pending or self._route is None:
            return None
        calls = tuple(self._pending)
        self._pending.clear()
        return VoiceToolBatch(calls, self.text, self._route, timed_out)
```

`claim_agent_task()` (`voice_gate.py:109-119`) memang mengembalikan tugas berat
**sekali saja** — tetapi cakupannya **per giliran**, direset oleh `reset()`
(`voice_gate.py:37-42`), bukan per durasi tugas.

### 3c. Penekanan yang sebenarnya: `suppress_live_output`, cakupan satu giliran

Variabel lokal di `_receive_audio` (`main.py:1058`):

```python
        suppress_live_output = False
```

Diset saat rute berat diklaim (`main.py:1092`):

```python
            suppress_live_output = True
```

**Direset di batas giliran** (`main.py:1068-1078`):

```python
        def _reset_voice_turn(*, deliver_notice: bool = True):
            nonlocal agent_status, agent_notice, suppress_live_output
            ...
            suppress_live_output = False
```

Pemicu reset: `turn_complete` (`main.py:1297-1305`, `1331-1336`) atau timer
grace 2,5 detik (`main.py:86-88`):

```python
VOICE_TOOL_FINAL_TIMEOUT_S = float(
    os.environ.get("JARVIS_VOICE_TOOL_FINAL_TIMEOUT_S", "2.5")
)
```

Yang dibuang selama jendela itu: audio balasan (`main.py:1165-1166`) dan
transkripsi output (`main.py:1180-1182`) — **milik giliran yang menyerahkan
tugas saja**.

**Angka `agent.task_timeout_s: 900` tidak ada hubungannya dengan lamanya
penekanan.** Klaim C-1 "jendela mati 15 menit" salah.

### 3d. Mic tetap hidup selama agent bekerja

`_listen_audio` adalah task asyncio independen (`main.py:1008`), tidak pernah
dihentikan oleh dispatch. Gerbang satu-satunya (`main.py:1024-1031`):

```python
        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            if not jarvis_speaking and not self.ui.muted and not self._phone_active:
```

`_is_speaking`, `ui.muted`, `_phone_active` — tidak satu pun disentuh oleh
`jarvis/agent/dispatch.py`. Giliran berikutnya mengeksekusi tool secara normal
(`main.py:1118-1122`):

```python
            else:
                fn_responses = []
                for fc in batch.calls:
                    print(f"[JARVIS] 📞 {fc.name}")
                    fn_responses.append(await self._execute_tool(fc))
```

### 3e. Jalur hasil kembali — dan cacatnya yang nyata

Callback dipanggil dari thread worker (`dispatch.py:273`), diterima di
`main.py:760-775`, berujung ke `speak()`. `speak()` **aman-thread**
(`main.py:663-672`):

```python
    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )
```

**⚠️ N-1 [TERBUKTI] — hasil tugas dapat memotong Jarvis di tengah kalimat.**
`turn_complete=True` dikirim seketika, tanpa memeriksa apakah Jarvis sedang
bicara dan tanpa antrean batas-giliran. Ini satu-satunya bagian dari
`AUDIT_REPORT.md §8.4b` yang benar-benar masih perlu dibangun.

Jalur kedua yang sama: BUS (`dispatch.py:238`, `:271`, `:276`).

### 3f. Pembatalan — ada, tapi tidak terjangkau user

Rantainya lengkap:

| Lapis | Lokasi | Kode |
|---|---|---|
| Handle | `dispatch.py:62-63` | `def cancel(self): self.session.cancel()` |
| Session | `session.py:81-82` | `def cancel(self): self.cancelled = True` |
| Loop | `loop.py:165-169` | `if session.cancelled:` → `RunResult(ok=False, cancelled=True, …)` |

Dua batasan nyata:

1. **Hanya dicek di awal iterasi** (`loop.py:164-165`). `_execute_calls`
   (`loop.py:222`) tidak memeriksa ulang, jadi tool yang lama berjalan tidak
   bisa dipotong.
2. **⚠️ N-2 [TERBUKTI] — hanya Telegram yang bisa membatalkan**, dan itu pun
   `cancel_all()`, bukan per-tugas. Satu-satunya pemanggil produksi:
   `jarvis/agent/adapters/telegram.py:391`:

   ```python
           n = dispatch.cancel_all()
   ```

   Tidak ada jalur batal dari suara maupun dari UI desktop.

### 3g. Verdict C-1

**DIBANTAH sebagian besar.** Diganti dengan:

> **C-1′ [TERBUKTI]** — Konkurensi agent secara teknis sudah berfungsi
> (`dispatch.py:24-25`, `:295`), tetapi **tak terlihat dan tak terkendali**:
> tidak ada batas jumlah tugas (N-3), tidak ada jalur batal dari suara/UI
> (N-2), dan hasil tugas dapat menyela ucapan yang sedang berjalan (N-1).

---

## [2] MEMORI TERPISAH — **BUG TERKONFIRMASI**

### 2a. Empat store berbeda

| # | Store | Penulis | Pembaca | Lane |
|---|---|---|---|---|
| 1 | `memory/long_term.json` | `memory/memory_manager.py:76` ← `main.py:829` | `memory_manager.py:35` → `main.py:682` | **Suara** |
| 2 | `data/agent.sqlite` → `memories` | `jarvis/agent/memory_store.py:147` ← `tools/memory_tools.py:47`, `reflect.py:99` | `memory_store.py:287` → `loop.py:64` | **Agent MK50** |
| 3 | `data/agent.sqlite` → `agent_sessions`/`agent_turns` | `jarvis/agent/session.py:95-99` | `session.py:144-155` | Agent (arsip, bukan recall fakta) |
| 4 | `memory.sqlite` (root) → `episodic_log` | `jarvis/core/memory.py:186` | `jarvis/core/memory.py:199` → `jarvis/ui/window.py:425`, `ui/timeline.py:92` | **Lapis ketiga** — timeline UI saja |

Path store 2: `jarvis/agent/paths.py:28` `return data_dir() / "agent.sqlite"`,
dari `config.yaml:663` `data_dir: "data"`.

### 2b. Penulis lane suara

`main.py:824-829`:

```python
        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
```

→ `memory/memory_manager.py:15` `MEMORY_PATH = BASE_DIR / "memory" / "long_term.json"`
→ `memory/memory_manager.py:76` `MEMORY_PATH.write_text(`

### 2c. Pembaca lane agent

`jarvis/agent/loop.py:64`:

```python
        memories = memory_store.search(
```

→ `jarvis/agent/memory_store.py:287` `SELECT rowid, * FROM memories WHERE …`

### 2d. Tidak ada jembatan — pencarian menyeluruh

Kata `long_term` **hanya** muncul di:

- `memory/memory_manager.py:15` (store itu sendiri)
- `actions/computer_control.py:40`, `:151` (baca, untuk `_user_profile()`)
- `jarvis/core/locale.py:59-61` (baca `identity.language` saja)

**Nol kemunculan di seluruh `jarvis/agent/`.** Tidak ada langkah impor, tidak
ada migrasi (`scripts/` hanya berisi `verify_frozen.py`, `verify_hermes.py`,
`youtube_oauth_setup.py`, `benchmark_helpers.py`), dan cron hanya
sqlite→sqlite (`jarvis/agent/cron.py:178` → `memory_store.consolidate()`).

### 2e. Dua system prompt membaca store yang terpisah

| Lane | Rantai |
|---|---|
| Gemini Live | `main.py:682` `load_memory()` → `main.py:683` `format_memory_for_prompt` → `main.py:703` `system_instruction="\n".join(parts),` |
| Agent MK50 | `loop.py:64` `memory_store.search` → `loop.py:76-79` `template.format(…)` → `loop.py:156` `{"role": "system", …}` |

Template agent (`jarvis/agent/prompts/system.md:19`, `:22`) hanya punya
placeholder `{reflective_memories}` dan `{retrieved_memories}` — tidak ada
placeholder untuk long-term JSON.

### 2f. Handoff suara→agent tidak membawa memori

`main.py:782-788` hanya mengirim `task` + callback; `context=` tidak pernah
diisi. Akibatnya `dispatch.py:224` `session.execution_context = context`
bernilai `None`, dan `jarvis/agent/memory_access.py:17-18`:

```python
    if context is None:
        return MemoryScope("device-local", "device")
```

### 2g. Bukti empiris (kueri baca-saja atas DB nyata)

- `memory/long_term.json` — 5 fakta (identitas, preferensi sapaan, bahasa,
  model kamera, satu catatan instruksi).
- `data/agent.sqlite` tabel `memories` — 55 baris.
- **Irisan: nol.** Pencarian substring untuk nilai-nilai dari JSON di dalam
  sqlite mengembalikan 0 hasil untuk setiap fakta.
- Satu-satunya kemiripan (`"User prefers Indonesian language"`) ditulis
  independen oleh tool `memory_write` agent, dengan bentuk kunci berbeda —
  **duplikasi, bukan sinkronisasi**.

### 2h. Verdict

**BUG TERKONFIRMASI, dua arah:**

1. Fakta yang diucapkan user → `long_term.json` → **tak terbaca agent**.
2. Fakta yang dipelajari agent → `agent.sqlite` → **tak pernah masuk
   `system_instruction` Gemini Live** (`main.py:703`).

Ditambah lapis ketiga (`memory.sqlite`) yang **tidak memberi makan system
prompt mana pun** — `episodic_log` kosong (0 baris) di disk.

### 2i. Perbaikan minimal (deskripsi — JANGAN dikerjakan tanpa persetujuan)

⚠️ **`main.py` adalah zona FROZEN.** Perbaikan di bawah menyentuhnya, jadi
**butuh izin eksplisit user** dan pembaruan `config/frozen_manifest.json`.
Lihat PERTANYAAN UNTUK USER #1.

- **Berkas:** `main.py`, cabang `save_memory` di `_execute_tool`
  (`main.py:824-836`)
- **Perubahan:** setelah `update_memory(...)` (`main.py:829`), tambahkan mirror
  best-effort dalam `try/except` sendiri, dijalankan lewat executor
  `self._run_tool(loop, …)` yang sudah ada supaya panggilan embedding tidak
  memblokir receive-loop:

  ```python
  memory_store.write("semantic", f"{category}.{key}: {value}",
                     importance=0.8, tags=["voice", "long_term", category],
                     scope="device-local", owner="device")
  ```

- **Kenapa argumen itu persis:** `scope="device-local", owner="device"` wajib —
  itu satu-satunya pasangan yang dikembalikan `memory_access.resolve(None)`
  (`memory_access.py:17-18`) untuk dispatch suara tanpa konteks. `importance=0.8`
  melewati gerbang `min_importance=0.6` di `loop.py:71`.
- **Dedup sudah tertangani:** `memory_store.consolidate()`
  (`memory_store.py:397-402`, cosine > 0.92 → `superseded_by`), dijadwalkan di
  `cron.py:178`.
- **Arah sebaliknya butuh perubahan terpisah** di `_build_config`
  (`main.py:679-713`).

---

## [4] ORB `EXECUTING` — **HIDUP**, bukan mati

Audit lama (`AUDIT_REPORT.md:102`, `:271`) menyiratkan state ini tak pernah
dipakai. Salah.

### 4a. State di-set dari tujuh titik produksi

Semuanya di `jarvis/ui/window.py`: baris `804` (buka aplikasi), `851` (aksi
slot), `889` (kirim Telegram), `943` (messaging tier-2), `964` (tugas agent
tier-3), `996` (dispatch ketikan desktop), `1043` (start kamera).

Jalur keluar (`jarvis/ui/window.py:1095-1099`):

```python
    def _restore_orb(self) -> None:
        state = _LEGACY_STATE_MAP.get(self._legacy_state, OrbState.IDLE)
        if state in (OrbState.EXECUTING, OrbState.THINKING):
            state = OrbState.IDLE
        self._state_sig.emit(state.value)
```

### 4b. Progress ring **sudah dirender penuh**

Gerbang (`jarvis/ui/orb.py:477-478`):

```python
        if self.state == OrbState.EXECUTING:
            self._paint_progress(p, pos, r, col)
```

Renderer lengkap (`jarvis/ui/orb.py:664-674`):

```python
    def _paint_progress(self, p: QPainter, pos: QPointF, r: float,
                        col: QColor) -> None:
        rr = r * 0.86
        rect = QRectF(pos.x() - rr, pos.y() - rr, rr * 2, rr * 2)
        track = QColor(col); track.setAlpha(40)
        p.setPen(QPen(track, 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)
        arc = QColor(col); arc.setAlpha(230)
        p.setPen(QPen(arc, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, 90 * 16, -int(self._progress * 360 * 16))
```

Setter publik ter-clamp sudah ada (`jarvis/ui/orb.py:195-196`):

```python
    def set_progress(self, fraction: float) -> None:
        self._progress = max(0.0, min(1.0, fraction))
```

### 4c. **N-4 [TERBUKTI] — yang hilang hanyalah sumber data**

`set_progress` punya **tepat satu pemanggil**, dan itu harness dev di dalam
`if __name__ == "__main__":` (`jarvis/ui/orb.py:716`):

```python
            elif key == "p":
                self.orb.set_progress((self.orb._progress + 0.1) % 1.0)
```

Akibatnya di aplikasi terkirim `self._progress` **selalu `0.0`** —
`p.drawArc(rect, 90 * 16, -0)` menggambar busur nol panjang. User melihat
lingkaran track redup dan tidak ada yang lain.

Tidak ada sinyal progres numerik di hulu: BUS hanya membawa event terminal
(`dispatch.py:238` `agent.task.started`, `:271` `agent.task.done`, `:276`
`agent.task.failed`) — **tidak ada `agent.task.progress`**. Kanal
`adapter.progress` bertipe `str` dan berujung jadi baris log
(`jarvis/agent/adapters/ui.py:83-86`):

```python
    async def progress(self, text: str) -> None:
        win = self._win()
        if win is not None:
            win.write_log(f"SYS: {text}")
```

### 4d. **N-5 [TERBUKTI] — kunci config `progress_ring` mati**

`rg -n "progress_ring"` → 3 hasil: `config.yaml:230` dan dua penyebutan prosa di
`AUDIT_REPORT.md`. **Nol pembacaan dari Python.** Rendering digerbang murni oleh
`self.state == OrbState.EXECUTING` (`orb.py:477`), bukan oleh nilai config.
Menyetel `progress_ring: false` hari ini tidak mengubah apa pun — melanggar
klaim header `config.yaml:3` *"Source code contains zero magic numbers"*.

### 4e. Konsekuensi untuk perencanaan

Bagian mahal (matematika paint Qt, gating state, clamping) **sudah jadi**.
Yang tersisa: satu event progres di BUS, satu produsen pecahan
(`iterations / max_iter` dari `loop.py:164` + `loop.py:113`), satu subscriber di
`window.py`. Perkiraan: **~30–60 baris, nol baris di renderer.**

⚠️ Konflik desain: `AUDIT_REPORT.md:807` justru menyarankan **jangan** memakai
state `EXECUTING` untuk tugas berjalan, sementara `window.py` sudah memakainya
di tujuh tempat. Lihat PERTANYAAN UNTUK USER #3.

---

## [7] KUALITAS TEST — klaim "327" **usang, bukan salah**

### 7a. Hasil nyata

```
859 passed, 4 warnings in 38.25s
```

Dikonfirmasi independen: `859 tests collected in 1.28s`. Nol gagal, nol error,
nol skip. `MIGRATION_NOTES.md:1473` menyebut *"Tests: 327 passed"* — dokumen
tidak pernah diperbarui; suite justru tumbuh +532.

Struktur: **99 file `test_*.py`** + `conftest.py`, **792 definisi `def test_`**;
selisih 67 dari `@pytest.mark.parametrize`. Konfigurasi `pytest.ini`:
`testpaths = tests`, `addopts = -ra`.

Satu-satunya warning — `jarvis/core/screen_awareness.py:65`, `Image.Image.getdata`
deprecated (Pillow 14, 2027-10-15).

### 7b. Smoke test: **nol**

Pola `except ModuleNotFoundError` muncul di 16 file, tetapi **selalu sebagai
pembuka** sebelum tes menguji perilaku nyata — sisa fase merah TDD, bukan tes
impor. Tidak ada satu pun tes yang hanya menegaskan sebuah modul bisa diimpor.

**Bucket A — penjaga artefak statis** (menguji teks berkas/dokumen/CI, bukan
runtime): **14 tes ≈ 1,6 %**. Contoh: `tests/test_phase9_finalization.py:74`
(`assert "python scripts/verify_frozen.py" in workflow`),
`tests/test_xlix_p0.py:156` (lint hex-color), `tests/test_architecture_inventory.py`
(3/3 tes, satu-satunya file yang 100 % Bucket A).

**Bucket D — tes perilaku nyata:** **≈845 dari 859 (98,4 %)**, tersebar di 98
dari 99 file. Rata-rata 2,7 assert per tes.

### 7c. **N-6 [TERBUKTI] — lubang cakupan: pembatalan yang dipicu user**

`dispatch.cancel_all()` (`dispatch.py:109`) **tidak pernah dieksekusi tes
mana pun**. Kedua referensi di `tests/` justru menggantinya:

- `tests/test_gateway_telegram_migration.py:102` —
  `monkeypatch.setattr(dispatch, "cancel_all", lambda: cancelled.append(True) or 7)`
- `tests/test_phase8_telegram_control.py:426` —
  `monkeypatch.setattr(dispatch, "cancel_all", lambda: 3)`

Seluruh rantai `/stop` → `cancel_all()` → `TaskHandle.cancel()`
(`dispatch.py:62`) → `Session.cancel()` (`session.py:81`) → loop menghormatinya
(`loop.py:165-169`) **tanpa cakupan**. `rg -n "cancelled=True|result.cancelled" tests/`
→ **nol hasil**.

Pembanding: cancel karena **timeout** (`dispatch.py:280`) *tercakup* di
`tests/test_phase2_browser_lease.py:327` — tetapi lewat stub `_FakeSession`
(`:279-288`) yang punya `cancel()` sendiri, jadi yang terbukti adalah call-site
dispatch, bukan `Session.cancel` maupun reaksi loop.

### 7d. Celah sekunder

| Jalur | Status |
|---|---|
| `dispatch.run_sync` (`dispatch.py:299`) | tidak dirujuk tes mana pun |
| `dispatch.is_active` (`dispatch.py:93`) | tidak dirujuk tes mana pun |
| `memory_store._embed` (`:97`) + pencarian vektor (`:121`) | selalu di-monkeypatch ke `lambda _texts: None` (`test_memory_continuity.py:14`, `test_memory_policy.py:40`, `:70`) → cabang embedding **tak pernah dieksekusi**; pencarian selalu jatuh ke FTS/LIKE |
| `memory_store.scope_counts` (`:215`) | hanya di-mock |

### 7e. Cakupan jalur kritis — ringkasan

| Modul | Verdict | Tes |
|---|---|---|
| `dispatch.py` | tercakup, ada celah | `test_phase2_dispatch.py`, `test_phase2_browser_lease.py`, `test_execution_context.py`, `test_mk50_routing_seams.py`, +4 |
| `loop.py` | tercakup, ada lubang (cancel) | `test_agent_core.py:96`, `test_phase2_browser_lease.py:17` |
| `memory_store.py` | tercakup baik | `test_agent_memory.py`, `test_memory_continuity.py`, `test_memory_policy.py` |
| `session.py` | tercakup, cancel hanya sebagian | `test_agent_memory.py:69`, `test_phase2_dispatch.py:158` |
| `voice_gate.py` | **paling kuat** | `test_voice_route_gate.py` (8 tes, 4,0 assert/tes), `test_voice_routing_integration.py` (10 tes) |

---

## Temuan Baru — Zona FROZEN & Arsitektur

### N-7 [TERBUKTI] — Zona FROZEN utuh, tapi provenansinya menggantung

```
$ python scripts/verify_frozen.py
FROZEN integrity: OK (10 files, baseline 094b696)
```

10 berkas terlindungi: `main.py`, `ui.py`, `core/stt.py`, `core/tts.py`,
`core/voice_listener.py`, `core/prompt.txt`, `jarvis/core/wake.py`,
`jarvis/ui/theme.py`, `jarvis/ui/orb.py`, `config/jarvis.ico`.

**Masalahnya:** `baseline_commit: 094b696` **tidak ada** di riwayat repo.

```
$ git cat-file -t 094b696
fatal: Not a valid object name 094b696
$ git log --oneline --all
dc41ef9 Initial commit
```

Hash isi tetap cocok, jadi integritas berkas terjaga — tapi acuan "disetujui
terhadap apa" menunjuk ke commit yang tak bisa diperiksa siapa pun.

> Catatan penting untuk perencanaan: `jarvis/ui/orb.py` **termasuk FROZEN**.
> Semua pekerjaan progress-ring di [4] menyentuh zona ini.

### N-8 [TERBUKTI] — H-1 "dua UI berjalan berdampingan" **DIBANTAH**

Hanya satu UI yang diinstansiasi. `jarvis/main.py:99-101`:

```python
    from jarvis.ui.window import JarvisUI
    build_ui = ui_factory or JarvisUI
    ui = build_ui(services={"assistant": assistant, "vision": vision})
```

UI baru itu lalu **diserahkan ke pipeline suara legacy** (`jarvis/main.py:50`):

```python
            jarvis_live = JarvisLive(ui)
```

`ui.py` (2621 baris) tetap **diimpor** lewat `main.py:38`
(`from ui import JarvisUI`) — sehingga seluruh kelas widget Qt-nya dimuat — tapi
`JarvisUI`-nya (`ui.py:2534`) **tidak pernah diinstansiasi** di jalur MK50.

**Koreksi:** ini **beban impor mati**, bukan dua UI yang berjalan bersamaan.
Hanya terjangkau bila seseorang menjalankan `python main.py` langsung.

### N-9 [TERBUKTI] — `AUDIT_REPORT.md §7.3` **salah** soal `core/social_*.py`

Audit lama menyatakan keduanya "hanya dirujuk `patch_ui.py` (yang dihapus)".
Kenyataannya (`ui.py:16-21`):

```python
from core.reactor import MiniReactor
from core.voice_listener import VoiceListener
from core.camera_vision import VisionProcessor
from core.social_manager import SocialManager
from core.social_ui import SocialConfigDialog
from core.settings_ui import SettingsDialog
```

Karena `main.py:38` mengimpor `ui.py`, menghapus `core/social_manager.py` atau
`core/social_ui.py` akan **memutus impor `main.py`** — yaitu memutus boot
pipeline suara. **Jangan hapus** sebelum `ui.py` benar-benar dipensiunkan
(rencananya ada di `docs/UI_LEGACY_RETIREMENT_PLAN.md`).

### N-10 [TERBUKTI] — `hermes-agent-main/` ada di disk, 151 MB

`.gitignore:39` → `hermes-agent-main/`. Ukuran terukur: **151 MB**. Jadi
`JARVIS_HERMES_PARITY_v2.md` (841 baris) merujuk sesuatu yang nyata secara
lokal, hanya tidak ikut ter-clone. Ini mengubah rekomendasi lama dari "referensi
tak bisa diakses" menjadi "referensi hanya-lokal, tidak tereproduksi".

### N-11 [TERBUKTI] — lane berat resolve diam-diam ke provider aktif

`config.yaml:641-642` menyisakan `routing.heavy.provider: ""`. Pemeriksaan
runtime:

```
heavy_candidates: ['openai_oauth', 'openrouter', 'local']
resolution provider: 'openai_oauth'
heavy_ready: True
dispatch.available(): True
```

Agent **aktif**. Tapi kandidat pertama datang dari `providers.active_name()`
(`jarvis/agent/model_routing.py:255-261`), bukan dari config — sehingga
mengganti provider aktif di Settings **diam-diam memindahkan lane berat** tanpa
jejak di `config.yaml`.

### N-12 [TERBUKTI] — `config.yaml` ter-track git dan masih menyediakan slot rahasia

```
$ git ls-files --error-unmatch config.yaml
config.yaml
```

H-4 tetap berlaku. Enam field masih ada dan masih kosong: `config.yaml:250-251`
(`instagram_token`, `facebook_token`), `:497-498` (`imap_user`, `imap_password`
— keduanya berkomentar *"SECURITY: gunakan env"*), `:703` (`home_assistant.url`),
`:705` (`spotify.client_id`).

### N-13 [TERBUKTI] — `core/prompt.txt` hanya 44 baris, tanpa penanda section

Tidak ada heading `[...]` sama sekali. Menambahkan section `[MULTI-TASKING]`
(`AUDIT_REPORT.md §8.4d`) adalah perubahan aditif yang bersih — **tetapi berkas
ini FROZEN** (`config/frozen_manifest.json`) dan merupakan milik user. Lihat
PERTANYAAN UNTUK USER #1.

---

## [1] DUPLIKASI TOOL — H-1 **TERKONFIRMASI SEBAGIAN**

### 1a. Angka yang selama ini dikutip semuanya salah

Diverifikasi ulang secara independen lewat AST:

| Klaim | Sumber | Nyata | Metode |
|---|---|---|---|
| "52 tool" agent | `README.md`, `MIGRATION_NOTES.md:1471` | **82 total** — 30 bergerbang kredensial, **52 ungated** | AST: setiap `ClassDef` turunan `Tool` dengan atribut `name` literal tak-kosong di 23 modul |
| "20 tool" suara | `AUDIT_REPORT.md:132` | **21** statis, **21–33** saat runtime | AST atas `TOOL_DECLARATIONS` (`main.py:125`) |
| "12 browser tool" | `MIGRATION_NOTES.md:1460` | 13 | idem |
| "Spotify 9" | `MIGRATION_NOTES.md:1465` | 10 | idem |

Angka "52" **tidak salah, tapi disalahpahami**: itu jumlah tool tanpa kredensial.
`MIGRATION_NOTES.md:1477` sendiri mengakuinya (*"Integrasi opsional … `available()`
= False tanpa kredensial"*). Plafon sebenarnya 82.

**Runtime lane suara bukan 21.** `jarvis/main.py:47` memanggil
`google_voice.install(legacy)`, yang memutasi daftar legacy di tempat
(`jarvis/integrations/google_voice.py:59-61`):

```python
    current = [item for item in _legacy.TOOL_DECLARATIONS
               if item.get("name") not in _GOOGLE_NAMES]
    _legacy.TOOL_DECLARATIONS[:] = [*current, *declarations()]
```

`_GOOGLE_NAMES` berisi 12 nama (`google_voice.py:10-15`) yang **diambil dari
registry MK50** (`google_voice.py:43`). Jadi sesi Gemini Live melihat **21–33
tool** tergantung scope Google yang diberikan — dan itu berarti kedua sistem tool
tampil di **satu prompt yang sama**.

### 1b. Mekanisme discovery

`jarvis/agent/registry.py:38-73`, empat filter berurutan:

1. `registry.py:42-44` — `pkgutil.iter_modules`, modul berawalan `_` dilewati → 23 kandidat
2. `registry.py:47-51` — gagal impor → `_logger.warning("agent.tools.module_skipped", …)`, modul didrop **senyap**
3. `registry.py:53-56` — gerbang opsional: `gate = getattr(mod, "available", None)` … `if callable(gate) and not gate(): continue`
4. `registry.py:60-67` — `cls.__module__ == mod_name` mencegah re-export terhitung ganda

`jarvis/agent/toolgroups.py:38-79` memetakan 23 modul ke 20 grup toggle UI;
`tests/test_toolgroups_usage.py:32` menegaskan `union == set(registry.all_tools())`
— tidak ada tool yang lolos dari grup.

### 1c. Pemetaan 20 modul `actions/` — hanya **2** yang benar-benar kembar

| Relasi | Jumlah | Modul |
|---|---|---|
| **SAMA** (kapabilitas sama, dua-duanya hidup) | **2** | `browser_control`, `web_search` |
| **PARSIAL** (tak ada yang superset) | **10** | `code_helper`, `computer_control`, `desktop`, `dev_agent`, `file_controller`, `file_processor`, `reminder`, `screen_processor`, `system_monitor`, `youtube_video` |
| **TANPA padanan MK50** | **8** | `computer_settings`, `flight_finder`, `game_updater`, `hermes_action`, `open_app`, `proactive`, `send_message`, `weather_report` |

Ukuran juga berlawanan dengan dugaan: `actions/` = **8.996 baris / 20 modul**,
`jarvis/agent/tools/` = **4.361 baris / 23 modul**. Jalur legacy **dua kali lebih
besar**.

### 1d. **N-14 [TERBUKTI] — tabrakan nama `web_search`**

Ada dua tool berbeda dengan **nama identik**:

- Legacy: `main.py:145` (deklarasi) → `actions/web_search.py`, 5 mode
  (`search/news/research/price/compare`, `:373-390`) + kartu InfoPanel (`:126`)
- MK50: `jarvis/agent/tools/web.py:42`, ada throttle/retry (`web.py:26-32`) dan
  `web_extract` berbasis trafilatura (`web.py:137`)

Keduanya membungkus `ddgs` + `jarvis.core.locale`, dengan fitur berbeda, dan
**keduanya bisa terlihat oleh model yang sama**. Tidak ada yang superset.

### 1e. **N-15 [TERBUKTI] — divergensi keamanan: lease desktop dilewati jalur legacy**

Ini bukan redundansi, ini bahaya nyata. Tool MK50 mengambil lease eksklusif
(`jarvis/agent/tools/computer.py:15`):

```python
from jarvis.automation.desktop_service import DESKTOP
```

Sementara `actions/computer_control.py`, `actions/computer_settings.py`, dan
`actions/game_updater.py` menyetir pyautogui **tanpa lease sama sekali**.
Akibatnya perintah suara legacy dan `computer_click` milik agent bisa
**berebut mouse** — persis skenario yang `AUDIT_REPORT.md §8.2` coba cegah lewat
`EXCLUSIVE = {"desktop", …}`. Mekanismenya sudah ada; jalur legacy tidak
memakainya.

### 1f. **N-16 [TERBUKTI] — arah ketergantungan terbalik dari dugaan**

`jarvis/agent/tools/` **tidak mengimpor apa pun** dari `actions/`
(`grep -rn "actions" jarvis/agent/tools/*.py` → nol hasil). Tetapi kode MK50
**lain** bergantung pada `actions/`:

```
jarvis/agent/adapters/telegram_light.py:38   from actions.open_app import open_app
jarvis/agent/adapters/telegram_light.py:89   from actions import computer_settings
jarvis/ui/window.py:587                      from actions.open_app import open_app as legacy_open
jarvis/ui/window.py:808                      from actions.open_app import open_app as legacy_open
jarvis/ui/window.py:855                      from actions.computer_settings import computer_settings
```

**Jadi `actions/` bukan sekadar "legacy yang dihidupkan `main.py`".** Sistem baru
merutekan lewatnya untuk kapabilitas yang tidak pernah ia implementasikan ulang
(peluncuran aplikasi, volume/kecerahan/wifi).

### 1g. Perbedaan jaminan yang **bukan** duplikasi

Empat pasang "PARSIAL" sebenarnya menyandikan jaminan berbeda — menyatukannya
akan menghilangkan fungsi:

| Pasangan | Legacy | MK50 |
|---|---|---|
| `reminder` vs `cron_create` | Penjadwal **OS** (`actions/reminder.py:147`, `:203`, `:253`) → **selamat dari restart Jarvis** | `jarvis/agent/cron.py` → hanya menyala selama proses hidup |
| `file_controller` vs `file_ops` | Sandbox `$HOME` (`actions/file_controller.py:16`) — manajemen berkas konsumen | Sandbox workspace (`tools/file_ops.py:20-27`) — penyuntingan kode |
| `youtube_video` vs `google_youtube` | Playback + transkrip + ringkasan Gemini (`:356`, `:395`, `:462`) | Data API saja — **tanpa playback, tanpa ringkasan** |
| `system_monitor` vs `process_list` | cpu/ram/gpu/suhu/uptime via NVML+ctypes (`:113`) | hanya enumerasi proses (`terminal.py:83`) |

### 1h. Deletability: **19 dari 20 terblokir**

Satu-satunya yang bisa dihapus: `actions/hermes_action.py` — sudah inert secara
desain (`actions/hermes_action.py:48` `if not is_enabled():`), docstring `:1`
*"Deprecated Hermes action kept as an inert compatibility boundary."*
**Tanpa pemanggil produksi.** Penghambatnya hanya 4 referensi tes
(`tests/test_hermes_disabled.py:4`, `tests/test_hermes_integration.py:199`,
`:212`, `:233`).

**Menghapus `actions/` hari ini akan MENGHILANGKAN kapabilitas** — 8 modul tanpa
padanan MK50: peluncuran aplikasi, volume/kecerahan/wifi, otomasi Steam/Epic,
kirim IM, pencarian penerbangan, pemrosesan PDF/office/audio/video, pemicu
proaktif.

### 1i. **N-17 [TERBUKTI] — kode mati di `actions/screen_processor.py`**

`screen_process()` (`:397`) dan `warmup_session()` (`:445`) tidak punya pemanggil
di luar blok `__main__` modul itu sendiri (`:458`, `:462`). `main.py:870`
mengimplementasikan ulang tool `screen_process` secara inline, dan `main.py:50`
hanya mengimpor `_capture_camera, _capture_screen`. Kelas `_VisionSession`
(`:208`) karena itu **tak terjangkau di produksi**.

### 1j. Verdict H-1

**TERKONFIRMASI SEBAGIAN.**

- ✅ **Benar:** dua sistem tool independen memang hidup bersamaan, dengan dua
  mekanisme registrasi tanpa kode bersama (`main.py:125` + rantai if/elif
  `main.py:842-976`, versus `registry.py:42` + `registry.execute()`), tabrakan
  nama nyata (N-14), dan divergensi keamanan nyata (N-15).
- ❌ **Salah:** "duplikasi sistemik" dalam arti 20 modul punya kembaran.
  Hanya **2 dari 20**. Delapan tidak punya padanan sama sekali.
- ❌ **Salah:** seluruh angka di tabel H-1 (52/20).
- ⚠️ **Terlewat:** ketergantungan MK50 → `actions/` (N-16), yang membuat
  "pensiunkan `actions/`" jauh lebih mahal daripada yang tertulis di
  `AUDIT_REPORT.md §9 Prioritas 3`.

---

## [8] KEAMANAN

**Model ancaman.** Ini bukan server yang diserang dari jaringan. Ini asisten
lokal dengan akses terminal + desktop + berkas, digerakkan LLM yang
**menelan konten web tak tepercaya** lewat `web_extract`, `web_search`, dan
`browser_*`. **Musuh utamanya adalah prompt injection**, bukan penyerang remote.
Semua peringkat di bawah memakai lensa itu.

### Ringkasan

| # | Temuan | Tingkat |
|---|---|---|
| S1 | `execute_code` menjalankan kode arbitrer **tanpa konfirmasi** | 🔴 **KRITIS** |
| S2 | `file_search` / `file_list` **tanpa cek sandbox sama sekali** | 🟠 **TINGGI** |
| S3 | Command injection di `open_app.py` (dua jalur, input dari LLM) | 🟠 **TINGGI** |
| S4 | Blacklist regex `terminal` — satu-satunya penjaga, mudah dilewati | 🟠 **TINGGI** |
| S5 | `pip install` dengan nama paket pilihan LLM | 🟠 **TINGGI** |
| S6 | Sandbox `workspace_root` bersifat **anjuran**, bukan penegakan | 🟠 **TINGGI** |
| S7 | `exec()` kode buatan LLM di sandbox palsu (`actions/desktop.py`) | 🟡 SEDANG-TINGGI |
| S8 | `web_extract` tanpa validasi skema/host → SSRF loopback/LAN | 🟡 SEDANG |
| S9 | Token bearer dashboard tak pernah kedaluwarsa; `revoke-devices` tidak mencabutnya | 🟡 SEDANG |
| S10 | `/auto-login` tanpa rate limit padahal mencetak sesi | 🟡 SEDANG |
| S11 | `_ensure_network_access()` mati-tapi-termuat — UAC + Public→Private | 🟡 SEDANG |
| S12 | JSONL telemetry mencatat `terminal.command` / `execute_code.code` mentah | 🟢 RENDAH-SEDANG |
| S13 | Path absolut hardcoded (portabilitas, bukan eksploitasi) | 🟢 RENDAH |

### S1 [TERBUKTI — diverifikasi ulang] — `execute_code` tanpa konfirmasi 🔴

`jarvis/agent/tools/code_exec.py:34-40` — deklarasi kelas **lengkap**:

```python
class ExecuteCode(Tool):
    name = "execute_code"
    description = ("Eksekusi potongan kode di sandbox subprocess "
                   "(python/node/bash/powershell). Tangkap stdout, stderr, "
                   "exit code. Gunakan print() untuk hasil.")
    params_schema = _ExecParams
    timeout_s = 320
```

**Tidak ada `requires_confirmation`. Tidak ada override `needs_confirmation()`.**
Default basis (`jarvis/agent/base.py:55`):

```python
    requires_confirmation: bool = False    # tool berbahaya → True
```

`jarvis/agent/base.py:67-68` mengembalikan default itu. Maka
`jarvis/agent/registry.py:143` menghitung `needs = False` dan tool berjalan
**tanpa prompt**.

Input 100 % dari LLM (`code_exec.py:28` `code: str = Field(…)`), ditulis apa
adanya ke berkas temp (`code_exec.py:58`) lalu dieksekusi (`code_exec.py:61-65`).

**"Sandbox" adalah salah nama.** `code_exec.py:51` hanya menetapkan `cwd`:

```python
        sandbox = data_dir() / "sandbox"
```

Tidak ada pemisahan user, container, seccomp, maupun pembatasan filesystem.
`powershell` termasuk bahasa yang diterima (`code_exec.py:23`).

**Rantai eksploitasi, seluruhnya terbukti di repo ini:**

1. `web_extract` mengambil URL apa pun tanpa validasi (`tools/web.py:150-158`)
   dan mengembalikan hingga 16.000 karakter ke konteks model (`web.py:176-181`).
2. Dispatch lokal mengirim `context=None` — `main.py:782-788` tidak pernah
   mengisi `context`; `dispatch.py:195` default `context=None`.
3. `registry.py:110` — `if context is not None:` — **seluruh blok
   capability/policy dilewati** untuk run lokal.
4. `execute_code` tidak butuh konfirmasi → jalan.

Ditambah monkey-patch `CREATE_NO_WINDOW` global (`main.py:13-22`), eksekusinya
**tak terlihat di layar**.

**Perbaikan: satu baris** — `requires_confirmation = True` pada `ExecuteCode`.

### S2 [TERBUKTI — diverifikasi ulang] — `file_search`/`file_list` lolos sandbox 🟠

`jarvis/agent/tools/file_ops.py:159-163`:

```python
    async def run(self, pattern: str, path: str = "", glob: str = "",
                  max_results: int = 60, **_) -> ToolResult:
        root = _resolve(path) if path else workspace_root()
        if not root.is_dir():
            return ToolResult.fail(f"folder tidak ditemukan: {root}")
```

**Tidak ada panggilan `_inside_sandbox` di sini.** `_resolve` (`file_ops.py:30-32`)
menerima path absolut apa adanya. `read_only = True` (`file_ops.py:156`) berarti
tidak pernah ada prompt.

Verifikasi menyeluruh — `_inside_sandbox` hanya dipanggil di **tiga** tempat,
dan **ketiganya adalah override `needs_confirmation`**, bukan `run()`:

```
file_ops.py:54    return not _inside_sandbox(_resolve(kw.get("path", "")))   # FileRead
file_ops.py:90    return not _inside_sandbox(_resolve(kw.get("path", "")))   # FileWrite
file_ops.py:124   return not _inside_sandbox(_resolve(kw.get("path", "")))   # FilePatch
```

Setiap baris yang cocok dikembalikan ke model (`file_ops.py:186`):

```python
                            hits.append(f"{f}:{i}: {line.strip()[:200]}")
```

Daftar-lewat (`file_ops.py:16-17`) berisi `.git`, `node_modules`, `__pycache__`,
`.venv`, dst — **tidak termasuk `config`, `.ssh`, `.aws`, `AppData`**. Penjaga
biner (`file_ops.py:35-36`) dan batas 2 MB tidak mengecualikan JSON/YAML/dotenv.

**Dampak:** satu tool-call tersuntik — `file_search(pattern=".", path="<home>/.ssh")`
atau `path="<proyek>/config"` — mengekstraksi hingga 60 baris × 200 karakter
material kredensial langsung ke konteks LLM, **tanpa prompt, tanpa jejak** selain
nama tool. Digabung dengan `web_extract` (keluar) atau `execute_code`, ini
primitif baca-dan-eksfiltrasi yang lengkap.

`FileList` (`file_ops.py:213-216`) punya celah identik; ia hanya mengembalikan
nama+ukuran, jadi sifatnya pengintaian.

**Perbaikan: dua baris** — `if not _inside_sandbox(root): return ToolResult.fail(...)`
di kedua `run()`.

### S3 [TERBUKTI — diverifikasi ulang] — command injection `open_app.py` 🟠

Input dari LLM: `main.py:127` mendeklarasikan `open_app` sebagai tool Gemini;
`main.py:842-843` men-dispatch dengan `args` dari model. `_normalize`
(`actions/open_app.py:68-78`) **mengembalikan `raw` apa adanya** bila nama tidak
ada di `_APP_ALIASES`:

```python
    return raw  
```

**Jalur A** (`actions/open_app.py:82-89`) — penjaganya bisa dilewati:

```python
    if shutil.which(app_name) or shutil.which(app_name.split(".")[0]):
        try:
            subprocess.Popen(
                app_name,
                shell=True,
```

`which()` diuji pada `app_name.split(".")[0]`, tetapi **string utuh yang belum
dipecah** yang diteruskan ke `Popen(shell=True)`. Nama seperti
`calc.exe & <payload>` lolos: `split(".")[0] == "calc"`, `which("calc")`
berhasil, lalu seluruh string dieksekusi shell. `&` adalah pemisah cmd.exe.

**Jalur B** (`actions/open_app.py:95-97`) — **tanpa penjaga sama sekali**:

```python
    if ":" in app_name:
        try:
            subprocess.Popen(f"start {app_name}", shell=True)
```

Setiap `app_name` yang mengandung titik dua langsung masuk f-string shell.

### S6 [TERBUKTI] — sandbox `workspace_root` hanya anjuran 🟠

Fungsi validasinya sendiri **benar** (`file_ops.py:20-27`): `.resolve()`
meruntuhkan `..` sebelum uji parent, jadi tidak ada bug traversal *di dalam
fungsi itu*. Masalahnya letak pemanggilannya — hanya di `needs_confirmation`
(S2 di atas), tak pernah di `run()`.

`FileWrite.run` (`file_ops.py:92-107`) tidak memeriksa path sama sekali dan
bahkan membuat direktori baru (`p.parent.mkdir(parents=True, exist_ok=True)`).

Batas keamanan **sepenuhnya berada di prompt UX**, bukan di fungsi I/O.

**Diperparah fail-open** di `jarvis/agent/registry.py:141-145`:

```python
    try:
        needs = tool.needs_confirmation(**args)
    except Exception:                                        # noqa: BLE001
        needs = tool.requires_confirmation
```

Bila `_inside_sandbox` melempar apa pun selain `OSError`, fallback-nya
`requires_confirmation` = **`False`** untuk ketiga tool berkas → tulisan
diteruskan **tanpa prompt**. Kontrol keamanan yang gagal-terbuka.

Sisi positif: `registry.py:143-160` menolak bila `adapter is None`, jadi jalur
cron/headless **gagal-tertutup**.

### S4 [TERBUKTI] — blacklist `terminal` 🟠

`jarvis/agent/tools/terminal.py:42-43` adalah satu-satunya penjaga:

```python
    def needs_confirmation(self, **kw) -> bool:
        return bool(_DANGEROUS.search(kw.get("command", "")))
```

Blacklist pola atas shell Turing-complete bukan batas keamanan.
`powershell -Command …`, `curl … | sh`, `certutil -urlcache`, `python -c`,
payload base64 — tak satu pun cocok. Semua yang tak cocok jalan tanpa prompt dan
tak terlihat (`_CREATE_NO_WINDOW`, `terminal.py:16`).

### S5 [TERBUKTI] — `pip install` dipilih LLM 🟠

`actions/dev_agent.py:298-302` memasang `to_install` yang berasal dari
`dependencies = plan.get("dependencies", [])` (`dev_agent.py:537`) — JSON hasil
generasi model. Nama paket halusinasi/tersuntik memasang dan mengeksekusi
`setup.py` arbitrer. Tanpa allowlist, tanpa pin versi, tanpa konfirmasi.
Paparan *slopsquatting* klasik.

### S7 [TERBUKTI] — `exec()` kode LLM, sandbox bocor 🟡

`actions/desktop.py:96` — `exec(compile(code, "<jarvis_desktop>", "exec"), sandbox)`.
"Sandbox"-nya membatasi `__builtins__` tetapi menyuntikkan primitif pelarian:
`getattr`/`hasattr` (`desktop.py:45`), `Path` (`:52`), dan **modul `ctypes` utuh**
di Windows (`:69`). `ctypes` saja sudah tamat. Aturan "NO subprocess"
(`desktop.py:131-137`) hanyalah **teks prompt, bukan penegakan**.

**Yang menahannya jadi TINGGI:** `desktop.py:144` memakai `model="gemini-3.5-flash"`
yang bukan id model valid → panggilan gagal → jalur ini **rusak saat ini**.
Perbaiki nama modelnya dan celah ini hidup.

### S8–S13 (ringkas)

- **S8** `tools/web.py:148-158` — `url` bebas dari LLM, tanpa allowlist skema/host,
  tanpa penolakan IP privat, `read_only = True` → tanpa konfirmasi. Primitif SSRF
  ke loopback/LAN/`169.254.169.254`.
- **S9** `dashboard/server.py:368` `self._tokens: set[str]` **hanya pernah
  ditambah** (`:537`, `:571`, `:613`) — nol kedaluwarsa, nol pencabutan di
  seluruh berkas. `/api/revoke-devices` (`:630-632`) mengosongkan
  `_device_sessions` tapi **tidak menyentuh `_tokens`** — "admin revoke" tidak
  mencabut sesi hidup mana pun.
- **S10** `/login` dibatasi rate (`server.py:529`); `/auto-login` (`:550-556`)
  **tidak**. Keyspace ~1,07 × 10⁹ dengan kedaluwarsa 600 dtk membuat brute-force
  tak praktis, tapi asimetrinya jelas kelalaian dan perbaikannya satu baris.
  Kunci + token juga di-inline ke HTML dalam blok `<script>` (`:591-593`) →
  masuk riwayat browser.
- **S11** `dashboard/server.py:103-311` `_ensure_network_access()` meminta
  **elevasi UAC** (`:208-215`) untuk menjalankan `.bat` yang membuka port firewall
  **dan mereklasifikasi setiap profil jaringan Public menjadi Private**
  (`:157-160`). Menurunkan Public→Private di Wi-Fi publik menyalakan network
  discovery dan file sharing se-host. **Mitigasi: ini kode mati** — `rg` hanya
  menemukan definisinya. Konsisten dengan `jarvis/core/dashboard_security.py`
  yang mengunci `needs_firewall=False`. **Sebaiknya dihapus, bukan dibiarkan
  termuat.**
- **S12** `jarvis/agent/registry.py:215-224` — redaksi **berbasis nama kunci**
  (`_SECRET_HINTS = ("key", "token", "password", "secret", "credential")`).
  Parameter `terminal` bernama `command`, `execute_code` bernama `code`,
  `file_write` bernama `content` — **tak satu pun cocok**, jadi 800 karakter
  pertama tertulis apa adanya ke `tool_usage.jsonl`. Positifnya:
  `registry.py:190-192` dan `session.py:103-108` **tidak** menyimpan args.
- **S13** Path absolut: `actions/dev_agent.py:317` merekonstruksi home dari
  `Path.home().name` alih-alih `Path.home()` — patah pada profil yang diganti
  nama / akun domain. Sisanya probe NVML Windows berpenjaga try/except
  (`ui.py:106`, `actions/system_monitor.py:39`).

### Yang bersih

- **`os.system`: nol.** **`pickle`: nol.** **`eval()`: nol** — semua hit `.exec()`
  adalah `QApplication.exec()`/`QDialog.exec()` Qt, positif palsu.
- **Tidak ada nilai rahasia yang ter-log.** OAuth hanya mencatat nama event
  (`anthropic_oauth.py:87`, `:141`, `openai_oauth.py:103`, `:176`).
  `git ls-files` mengonfirmasi tak ada berkas kredensial yang ter-track.
  Catatan kecil: `main.py:830` mencetak nilai memori verbatim ke stdout.
- **Traversal ditangani benar** di dashboard (`server.py:785-795` menghapus
  seluruh separator; `:707-710` `Path(raw).name`) dan nama skill
  (`jarvis/agent/skills.py:131-132`, regex allowlist).
- **`jarvis/core/dashboard_security.py`** gagal-tertutup dengan baik: LAN
  **melempar** kecuali TLS tersedia, `lan_read_only` true, dan allowlist origin
  HTTPS eksak terkonfigurasi.

**Observasi (bukan kerentanan):** karena `_mutation_allowed()` (`server.py:481-482`)
mengembalikan `False` untuk seluruh mode LAN, `/login` dan `/api/device-login`
sama-sama 403 — **tidak ada cara memperoleh token bearer di mode LAN**, sehingga
setiap rute ber-`_auth` tak terjangkau. Mode LAN gagal-tertutup sampai titik
tidak berfungsi. Perlu diputuskan: dihapus, atau diperbaiki — karena "perbaikan"
yang naif adalah melonggarkan `_mutation_allowed`, dan itu persis perubahan yang
akan memapar `/api/command` ke jaringan.

### Enumerasi rute dashboard

17 dekorator rute. Mekanisme auth: token bearer in-memory (`server.py:473-475`).
Yang **tanpa** `_auth`: `/static/crypto.js` (:497), `/login` GET (:504), `/` (:508,
sengaja — auth sisi klien), `/login` POST (:525, ini *adalah* auth-nya,
rate-limited), `/auto-login` (:550, S10), `/api/device-login` (:599),
`/api/upload` fallback (:760, hanya mengembalikan 503 statis — inkonsistensi
kecil). Sisanya ber-`_auth`. `/api/command` (:634) — endpoint bernilai tertinggi —
digerbang benar: `_auth` + LAN-blocked + rate limit 30/menit + AES opsional.

---

## [9] KUALITAS KODE

### 9a. Berkas > 1500 baris — hanya empat

| Baris | Berkas | Catatan |
|---|---|---|
| **2621** | `ui.py` | Monolit legacy. Terblokir migrasi `main.py` (lihat N-8). |
| **1865** | `main.py` | Pipeline Gemini Live + deklarasi tool + dispatch + jembatan memori + monkey-patch global. Pemisahan jelas: audio ↔ dispatch ↔ memori. |
| **1844** | `jarvis/ui/window.py` | Fasad UI aktif. |
| **1825** | `jarvis/ui/panels.py` | Widget panel — terdekomposisi alami, satu modul per panel. |

Runner-up: `actions/game_updater.py` (1053), `jarvis/agent/tools/browser.py` (1028),
`actions/browser_control.py` (892), `dashboard/server.py` (878).

### 9b. **N-18 [TERBUKTI] — monkey-patch `Popen` global**

`main.py:13-22` menambal `subprocess.Popen` **untuk seluruh proses**. Dua masalah:

1. `kw.pop("startupinfo", None)` **membuang `startupinfo` milik setiap
   subprocess**, termasuk library pihak ketiga yang sah mengirimkannya —
   perubahan perilaku jarak-jauh tanpa opt-out.
2. Memaksa `CREATE_NO_WINDOW` global berarti **setiap perintah shell yang
   dijalankan agent tak terlihat user** — ini langsung memperkuat S1/S3/S4.

Efeknya juga hanya aktif bila `main.py` legacy diimpor, sehingga perilaku berbeda
antara `--no-voice` dan boot normal — jebakan debugging yang nyata.

### 9c. `except` yang menelan error

**Bare `except:` — hanya 2 di seluruh pohon:** `actions/youtube_video.py:317` dan
`:323`. Keduanya di parsing metadata YouTube; juga menelan `KeyboardInterrupt`.

**`except …: pass` — ~150 kemunculan di 40 berkas.** Mayoritas di lapis agent
memakai `# noqa: BLE001` secara konsisten dan memang best-effort. **Empat yang
benar-benar bermasalah:**

| Lokasi | Kenapa penting |
|---|---|
| `jarvis/agent/registry.py:141-144` | **Kontrol keamanan yang gagal-terbuka** (S6). Harus `needs = True`. |
| `jarvis/agent/registry.py:208-209` | Kegagalan tulis **audit-log senyap total**. Untuk tool yang bisa menjalankan shell, kehilangan jejak audit tanpa sinyal adalah celah nyata. |
| `jarvis/agent/dispatch.py:169-175` | **Vektor kegagalan-senyap paling terlihat user.** Setiap `on_ack`/`on_done`/`on_error` lewat sini. `_on_done` yang melempar = user **tidak dapat jawaban sama sekali** dan **tidak dapat error**, sementara tugas tercatat sukses. |
| `jarvis/agent/memory_store.py:80-81` | Jalur **tulis memori**. `except sqlite3.OperationalError: pass` melingkupi blok multi-statement, jadi disk penuh / DB terkunci / skema korup tak bisa dibedakan dari "tanpa FTS5". Memori diam-diam turun jadi tak-tercari. |

Yang **wajar**: `loop.py:189-190`, `:266-267` (pesan progres kosmetik),
`interaction.py:307-308` (terdokumentasi), `core/voice_listener.py:60-63`
(`sr.WaitTimeoutError` adalah sinyal alur normal), `main.py:1019-1022`
(backpressure terdokumentasi).

### 9d. **N-19 — TODO/FIXME/HACK: praktis nol**

Satu-satunya hit adalah **teks prompt di dalam string instruksi LLM**
(`actions/dev_agent.py:243`), bukan anotasi developer.

Ini **bukan otomatis kekuatan**. Mengingat volume dokumen perencanaan di root
(`MIGRATION_NOTES.md`, `AUDIT_REPORT.md`, dst), pekerjaan tertunda tampaknya
dilacak **di dokumen, bukan di kode**. Penanda in-code adalah yang bertahan
melewati refactor dan yang ditemukan `grep` saat berburu bug.

### 9e. Import melingkar

**Siklus tingkat-modul: NOL.** Paket benar-benar mengimpor secara asiklik.

**Namun ada 5 "penghindaran siklus"** — import di dalam fungsi yang ada
*justru karena* modul target sudah mengimpor modul saat ini di tingkat atas:

| # | Import tertunda | Sisi balik | Verdict |
|---|---|---|---|
| 1 | `interaction.py:301` `from jarvis.agent import dispatch as _dispatch` | `dispatch.py:19` `from jarvis.agent.interaction import detect_language, render_ack` | Siklus nyata `interaction ↔ dispatch` — paling signifikan secara struktural |
| 2 | `providers.py:328` `from jarvis.agent import llm_client` | `llm_client.py:22` `from jarvis.agent.providers import …` | Siklus nyata; dibungkus `try/except` sehingga ImportError sejati juga tertelan |
| 3 | `jarvis/core/config.py:96` `from jarvis.core import llm` | `jarvis/core/llm.py:13` `from jarvis.core import config` | Siklus nyata `config ↔ llm`. `config` adalah modul terbawah — seharusnya tidak bergantung pada `llm` sama sekali. **Paling bersih untuk diperbaiki.** |
| 4–5 | `telegram_control.py:149`, `:231` | `adapters/telegram.py:22` | Siklus struktural, dua titik hindar |

**Bukan temuan:** 15 import di dalam `run()` pada `jarvis/main.py` adalah
*lazy loading disengaja* — masing-masing dibungkus `try/except` + `logger.warning`
supaya tiap subsistem bisa gagal independen. **Pola yang benar; jangan "dirapikan".**

### 9f. Import berat di boot path — hampir semuanya bersih

Paket `jarvis/*` disiplin. Seluruh dependensi berat diimpor **di dalam fungsi**:
`jarvis/vision/process.py:204-205` (`cv2`, `mediapipe` — di dalam worker; ini
`multiprocessing.Process`, induknya tak pernah memuat cv2), `vision/yolo.py:24`
(`torch`), `vision/device_caps.py:54,82,94,101`, `core/boot.py:79,94`,
`core/memory.py:143,394,418`, `core/wake.py:132,325`.

Header `jarvis/vision/process.py:14-21` — modul yang **memang** diimpor di thread
boot utama — **nol dependensi berat**. Ini persis benar.

**Satu temuan nyata — N-20 [TERBUKTI]: `cv2` di boot path thread suara.**

Rantai impor, terbukti:

```
jarvis/main.py:175   voice_thread = _start_voice_pipeline(ui)
jarvis/main.py:41      import main as legacy
main.py:38               from ui import JarvisUI
ui.py:18                   from core.camera_vision import VisionProcessor
core/camera_vision.py:1-2    import cv2 / import numpy as np   ← tingkat modul
```

`cv2` (~300–600 ms, ~100 MB RSS) diimpor tanpa syarat pada setiap boot
non-`--no-voice`. **Yang menahannya di SEDANG:** ini terjadi di thread daemon
`jarvis-live` (`jarvis/main.py:57-60`), bukan thread UI Qt — jendela tetap
tergambar dan orb tetap beranimasi. Biayanya adalah **waktu-sampai-respons-suara-pertama**,
bukan waktu-sampai-jendela.

Ironinya: subsistem `jarvis/vision/` modern **sudah** mengisolasi cv2 ke proses
terpisah dengan benar — beban ini murni datang dari tumpukan kamera legacy yang
ditarik hanya untuk memenuhi simbol `VisionProcessor`. `torch`, `mediapipe`,
`ultralytics`, `transformers`, `onnxruntime` **semuanya sudah di luar boot path**.

---

## [5] JALUR HERMES — **INERT tapi masih terjangkau**

### 5a. Distribusi

302 baris cocok di 36 berkas. **`main.py` dan `ui.py` root: NOL kemunculan** —
pipeline suara FROZEN bersih sepenuhnya.

Tiga kategori berbeda, dan membedakannya sangat penting:

1. **Bridge asli** — `jarvis/integrations/hermes/{bridge,async_dispatch,messaging_service,platform_catalog}.py`
   + `actions/hermes_action.py`. `bridge.py:129` benar-benar `subprocess.run` ke
   CLI `hermes`.
2. **Nama legacy pada kode hidup** — `jarvis/ui/window.py::run_hermes()` dan
   `jarvis/nlp/agent.py::HermesAgent`.
3. **Komentar saja** — ~10 baris di `auxiliary.py`, `capability_service.py`,
   `skills.py`, `toolgroups.py`, dst. Nol kode.

### 5b. Gerbang flag: **lengkap dan gagal-tertutup**

`jarvis/integrations/hermes/bridge.py:35-42` — sumber kebenaran tunggal:

```python
def is_enabled() -> bool:
    """Return feature flag Hermes dengan default aman (nonaktif)."""
    return config.get("hermes.enabled", False) is True
```

Perhatikan `is True` — nilai truthy-tapi-bukan-`True` (`"false"`, `1`) **tidak**
mengaktifkannya.

Setiap batas eksekusi dijaga: `bridge.py:94-95` (`_exe`), `:102-103`
(`available`), **`:117-118` (`_run` — satu-satunya titik `subprocess.run`)**,
`:205-206` (`check`), `async_dispatch.py:49-51` (sebelum konstruksi bridge *dan*
spawn thread), `hermes_action.py:48-52`, `messaging_service.py:114-135`,
`:179-180`, `:195-196`, `:225-226`, `:256-257`, `boot.py:125-128`.

`bridge.py:115-116` mendokumentasikan desainnya: *"Security boundary: keep this
guard immediately before every possible executable lookup/subprocess call."*
Diverifikasi `tests/test_hermes_disabled.py:48-72`, yang meracuni cache
(`bridge._resolved = "hermes"`) dan membuat `shutil.which`/`subprocess.run`
melempar, lalu menegaskan semua metode publik tetap gagal-tertutup.

**Efek samping impor tingkat-modul: tidak ada yang berbahaya.** `CircuitBreaker`
dikonstruksi di `HermesBridge.__init__` (`bridge.py:83-87`), yang hanya berjalan
lewat `HermesBridge.get()` — dan setiap call site produksi memeriksa
`is_enabled()` lebih dulu.

### 5c. Tidak ada impor saat boot

| Importer | Gaya | Terjangkau saat boot? |
|---|---|---|
| `actions/hermes_action.py:23-24` | **eager tingkat-modul** | **TIDAK** — `actions/` **tidak punya `__init__.py`**, dan `main.py:43-61` mengimpor 19 modul saudara **tanpa** `hermes_action` |
| `jarvis/core/boot.py:125` | lazy, dalam `_check_hermes()` | **TIDAK** — terdaftar di `boot.py:149` sebagai `"core.hermes"`, tapi `config.yaml:303-310` **tidak memuat `core.hermes`** di `boot.subsystems`; `boot.py:179` memfilter `if name in _CHECKS` |
| `jarvis/ui/window.py:927-928` | lazy, **setelah** penjaga `allow_agent` di `:907` | **TIDAK** |
| `jarvis/ui/panels.py:1024` | lazy, di `MessagingPanel.__init__` | **TIDAK** — `MessagingPanel` tak pernah diinstansiasi di produksi (`rg` → hanya `tests/test_parity_panels.py:294,308,320`) |
| `scripts/verify_hermes.py:16-17` | tingkat-modul | **TIDAK** — skrip manual mandiri |

### 5d. **N-21 [TERBUKTI] — yang MASIH berjalan meski `enabled: false`**

**(a) Regex router jalan tanpa syarat.** Tidak ada pemeriksaan flag di
`jarvis/core/router.py` sama sekali. `classify()` masih memancarkan
`Intent.HERMES_TASK` di `router.py:179`, `:192`, `:244`, dan dikonsumsi di
`jarvis/ui/window.py:721-725`:

```python
        elif c.intent is Intent.HERMES_TASK:
            self.run_hermes(c.slots, text, allow_agent=False)
```

Jadi **`run_hermes()` adalah fungsi hidup yang dieksekusi hari ini.** Diverifikasi:
satu-satunya call site produksi adalah `window.py:725`, selalu `allow_agent=False`.

Dengan `allow_agent=False` ia hanya bisa (1) mengirim Telegram native sungguhan
via `send_from_anywhere` (`window.py:894`), atau (2) menolak keras
(`window.py:907-914`). Impor bridge di `window.py:927-928` **tak terjangkau**.

⚠️ **Konsekuensi perilaku:** perintah yang cocok `_HERMES_SEND_RE` **ditolak
diam-diam** bila bot Telegram native tidak berjalan — bukan ditangani.

**(b) Toggle Settings masih bisa mempersenjatai ulang bridge.**
`jarvis/core/settings_service.py:297-306` masih menyajikan seksi "Hermes Bridge"
dengan field bool `hermes.enabled`. `set_value` (`:368`) →
`config_write.set_scalar` → `jarvis/core/config_write.py:57` `config.reload()`.
Karena `is_enabled()` membaca config **live** dan `_exe()` resolve malas,
**membalik toggle mempersenjatai ulang CLI tanpa restart.**

*Mitigasi:* panel yang merendernya (`panels.py:1339 SettingsPanel`) tak pernah
diinstansiasi di produksi; sheet yang hidup (`actionpanel.SettingsSheet`,
`settings_providers`, `settings_messaging`) **nol** referensi hermes. Tapi
menyunting `config.yaml` dengan tangan tetap mempersenjatai penuh.

**(c) `scripts/verify_hermes.py` tanpa penjaga flag.** `:28`
`bridge = HermesBridge.get()` tanpa `is_enabled()` di mana pun. Inert hanya
karena penjaga internal bridge menyala — tetapi ini satu-satunya berkas yang
*bermaksud* menjalankan CLI.

### 5e. **N-22 [TERBUKTI] — `HermesAgent` adalah NAMA, dan ia HIDUP**

`jarvis/nlp/agent.py:16-17` `class HermesAgent(NLPModule)` **tidak pernah**
menyentuh bridge/CLI. Ia orkestrator ReAct mandiri di atas `jarvis.core.llm` +
`MemoryManager`. **Diinstansiasi di setiap boot:** `jarvis/main.py:86-88` →
`jarvis/nlp/assistant.py:40` `("jarvis.nlp.agent", "HermesAgent")` → `:51`
`__import__`. `can_handle` mengembalikan lantai **0.65** (`agent.py:32`),
menjadikannya catch-all hidup di pipeline NLP.

**Mengganti namanya kosmetik; menghapusnya menghilangkan handler yang bekerja.**

Serupa, eskalasi sudah pindah ke router MK50 **sebelum** klasifikasi `Intent`
(`window.py:688-698`), dan frasa eksplisit "suruh hermes …" **dicegat ke agent
native**, tak pernah ke CLI (`jarvis/agent/router.py:76-80`, `:298-299`).
Artinya `jarvis/core/router.py:177-179` **terbayangi dan tak terjangkau**.

### 5f. Verdict: **TIDAK aman dihapus sebagai satu operasi**

| # | Penghambat | Bukti |
|---|---|---|
| **B1** | `jarvis/core/router.py` masih memproduksi `Intent.HERMES_TASK`, `window.py` masih men-dispatch-nya. Menghapus `run_hermes` **memutus jalur kirim Telegram native tier-2 yang hidup**. | `router.py:25`, `:179`/`:192`/`:244`; `window.py:721-725`, `:886-905` |
| **B2** | `boot.py:149` mendaftarkan `"core.hermes": _check_hermes` | `boot.py:125` |
| **B3** | **67 asersi tes** di 2 berkas khusus + 9 lainnya. `tests/test_hermes_disabled.py` **adalah bukti bahwa jalur ini tetap inert** — menghapus kodenya menghapus buktinya. | `test_hermes_disabled.py:4-12`; `test_hermes_integration.py:199-234` |
| **B4** | `panels.py:1024` `MessagingPanel` bergantung keras pada `messaging_service`; `tests/test_parity_panels.py:294-320` menginstansiasinya | `panels.py:1024` |

**Aman dihapus HARI INI:** `scripts/verify_hermes.py` (102 baris, nol importer,
dan satu-satunya pemanggil bridge tanpa penjaga — menghapusnya **mengurangi**
risiko).

**Urutan pensiun yang disarankan:** ① buang seksi `hermes` dari
`settings_service.py:297-306`; ② arahkan ulang `Intent.HERMES_TASK` ke messaging
native dan ganti namanya (`Intent.DIRECT_MESSAGE`), hapus `run_hermes`;
③ hapus `boot.py:123-137,149`; ④ hapus `jarvis/integrations/hermes/`,
`actions/hermes_action.py`, `scripts/verify_hermes.py`, `MessagingPanel`, dan
tesnya **dalam satu commit**.

### 5g. `hermes-agent-main/` — 151 MB, 6.442 berkas

Gitignored (`.gitignore:34-35`), jadi tidak ada di riwayat — tetapi **setiap
working tree developer membawa 151 MB**, dan setiap `rg`/`grep`/indeks IDE tanpa
scope menyentuhnya. Runtime tidak pernah membacanya, dan itu **ditegakkan**:
`jarvis/agent/skill_hub.py:18` `_BLOCKLIST_SUBSTRINGS = ("hermes", "petdex", "yuanbao")`
dengan `_DEFAULT_SOURCES = ()` (`:20`), diasersi
`tests/test_hermes_disabled.py:41-45`.

`.hermes/` = 144 KB, hanya 10 markdown perencanaan. Tanpa kode.

---

## [6] FILE YATIM

**Metode.** 271 berkas `.py` dienumerasi; untuk tiap modul dicocokkan lima pola
referensi di seluruh `.py`/`.yaml`/`.json`/`.txt`/`.ini`/`.md`, self-hit
dikecualikan, lalu **disilangkan dengan empat mekanisme pemuatan dinamis**.

### 6a. Mekanisme dinamis — ini yang memisahkan "yatim" dari "auto-discovered"

1. **`jarvis/agent/registry.py:37-70`** — pemindaian direktori. Setiap `.py`
   non-underscore di `jarvis/agent/tools/` **diimpor lewat scan filesystem**.
2. `jarvis/nlp/assistant.py:39-51` — `__import__` berbasis tabel, 9 modul NLP.
3. `jarvis/ui/panels.py:1564,1627,1648` — `__import__(f"jarvis.integrations.{provider}")`.
4. **Tidak ada relative import di seluruh pohon** — satu-satunya hit `from \.`
   adalah baris prosa di dalam string prompt (`actions/dev_agent.py:217`).
   Jadi analisis dotted-path ini **lengkap**.

### 6b. **N-23 [TERBUKTI] — §7.3 audit lama SALAH soal `core/social_*.py`**

`AUDIT_REPORT.md:516` menyatakan *"Hanya dirujuk `patch_ui.py` (yang dihapus)"*.
Ripgrep membantah:

```
ui.py:19:from core.social_manager import SocialManager          ← TERLEWAT audit lama
ui.py:20:from core.social_ui import SocialConfigDialog          ← TERLEWAT audit lama
ui.py:1362: self.social_manager = SocialManager(notification_callback=self._log_sig.emit)
ui.py:1363: self.social_manager.start_polling()
```

`ui.py` hidup (`main.py:38`), dan `main.py` diimpor entry point kanonik
(`jarvis/main.py:41`). Keduanya juga **FROZEN**, jadi impor itu tak bisa dibuang
tanpa re-baseline manifest.

**Menghapus salah satu → `ImportError` di `ui.py:19`, di jalur suara produksi.**
Proteksi sama meluas ke `core/reactor.py`, `core/camera_vision.py`,
`core/voice_listener.py`, `core/settings_ui.py`.

### 6c. ✅ AMAN DIHAPUS — terbukti tak dirujuk

| Berkas | Baris | Bukti |
|---|---:|---|
| `patch_ui.py` | 88 | `rg "patch_ui"` → 0 hit kode. Menulis ke path **di luar pohon** (`:4`) |
| `mw.txt` | 750 | 0 hit kode; bukan modul |
| `create_jarvis_profile.py.bak` | 98 | 0 ref; `diff` membuktikan sintaks rusak di `:50` (`680Kilau,`) |
| `actions/youtube_video.py.bak` | 680 | `.bak` — tak bisa diimpor; 0 ref |
| `jarvis/agent/tools/google_youtube.py.bak` | 202 | `pkgutil.iter_modules` hanya menghasilkan `.py` → **tidak** dimuat; 0 ref |
| **`core/installer.py`** | 138 | `rg "installer\|Installer"` → **hanya docstring-nya sendiri** (`:2`). Relik "MARK XL" |
| **`core/llm_client.py`** | 586 | Semua hit `llm_client` menunjuk `jarvis/agent/llm_client.py` (berkas **berbeda & hidup**). Klien Ollama/LM-Studio MARK XL, **nol importer** |
| `scripts/verify_hermes.py` | 102 | 0 hit kode; satu-satunya pemanggil bridge tanpa penjaga |

**Total: 2.644 baris kode/teks mati.** Tiga `.bak` (980 baris) — yang di
`jarvis/agent/tools/` membayangi nama modul hidup di setiap grep dan pencarian IDE.

### 6d. 🔒 PERTAHANKAN — dan satu jebakan penting

**N-24 [TERBUKTI] — 13 modul di `jarvis/agent/tools/` punya NOL referensi impor
tetapi SEMUANYA HIDUP** lewat auto-discovery `registry.py:42-47`:
`clarify.py`, `code_exec.py`, `cron_tools.py`, `file_ops.py`, `food.py`,
`google_drive.py`, `session_tools.py`, `spotify.py`, `todo.py`, `vision.py`
(nol ref sama sekali), plus 11 lain yang hanya dirujuk tes.

> **Menghapus salah satunya menghilangkan kapabilitas agent secara diam-diam,
> tanpa `ImportError` apa pun sebagai peringatan.** Skrip `audit_dead_code.sh`
> di `AUDIT_REPORT.md §7.4` akan menandai ke-13 modul ini sebagai "YATIM" —
> **skrip itu berbahaya bila diikuti secara harfiah.**

Juga dipertahankan: `jarvis/nlp/agent.py` (dimuat tiap boot), 19 `actions/*.py`,
`core/social_*` dan saudaranya (6b), berkas gateway, dan modul `comments/*`
yang dirujuk `actions/youtube_video.py:79` / `tools/google_youtube.py:36`.

### 6e. ⚠️ RAGU — butuh keputusan manusia

| Item | Kenapa ragu |
|---|---|
| **`jarvis/core/notify_hub.py`** (191) | **Nol referensi di mana pun** — hanya 2 baris `MIGRATION_NOTES.md`. Memenuhi ambang "aman" secara mekanis, **tapi** docstring `:1` menyebut *"NotificationHub (Mark L Change 1) — post-boot notification poll"* — ini **fitur yang dibangun tapi belum disambung**, bukan legacy mati. Menghapusnya membuang pekerjaan yang disengaja. |
| **`jarvis/integrations/youtube_capability.py`** (111) | Nol referensi kode. Tapi docstring `:1-13` menjelaskan **invarian keamanan** — "API key TIDAK cukup untuk memposting balasan … agar UI bisa menonaktifkan kontrol balasan sampai OAuth benar-benar tersambung". Menghapusnya membuang **penjaga**, bukan bangkai. |
| `qt.conf` | Qt memuatnya **berdasarkan konvensi nama berkas**, bukan impor. Ketiadaan referensi **tidak membuktikan apa pun**. Butuh uji DPI UI. |
| `setup.py` (11) | Bukan berkas packaging — pembungkus instal yang mencetak `"Run 'python main.py' to start MARK XXV."` (`:10`). Namanya **direservasi setuptools**. **Ganti nama, jangan hapus.** |
| `create_jarvis_profile.py` (98) | Utilitas operator tak-ter-track, terdokumentasi di `JARVIS_CHROME_PROFILE.md`. Nol kopling kode. |
| **17 modul "matang tapi belum tersambung"** — `voice_delivery.py`, `automation/browser_service.py`, `browser/agent_view.py`, `core/health.py`, `core/monitors.py`, `gateway/{delivery,rollout}.py`, `gateway/platforms/{discord,whatsapp_cloud}.py`, `plugins/{loader,runtime,manifest}.py`, `runtime/evaluation.py`, `ui/{provider_health_panel,sessions_panel}.py`, `vision/{device_caps,frame_governor}.py`, `integrations/comments/{facebook,instagram,x_adapter,youtube}.py` | Masing-masing punya **tepat satu importer, dan itu tes**. Empat adaptor komentar mensubklas `PlatformAdapter` tapi **tak pernah dikonstruksi**. `runtime/evaluation.py` bahkan punya runbook operator (`docs/EVALUATION_RUNBOOK.md:9`). **Jangan hapus massal** — ini kapabilitas bertahap, dan tesnya ikut hilang. Diturunkan dari AMAN ke RAGU sesuai aturan bukti. |

---

## Catatan Metodologi

- Semua klaim **KRITIS/TINGGI** di [8] diverifikasi ulang secara independen oleh
  auditor utama dengan membaca berkasnya langsung, bukan hanya menerima laporan
  subagent. Termasuk S1 (`code_exec.py:34-40` + `base.py:55`), S2
  (`file_ops.py:159-163` + ketiga call site `_inside_sandbox`), S3
  (`open_app.py:68-97`), dan fail-open `registry.py:141-145`.
- Angka tool (82/52, 21) dihitung ulang via AST oleh auditor utama, cocok persis
  dengan laporan subagent.
- Jumlah tes (859) dikonfirmasi ulang lewat `pytest --collect-only`.
- Yang **TIDAK** diverifikasi: tidak ada kode yang dijalankan untuk membuktikan
  eksploitasi S1–S8; semuanya analisis statis atas jalur kode. Tidak ada
  perubahan berkas yang dilakukan di seluruh audit ini.
