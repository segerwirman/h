# JARVIS — Rencana Perbaikan Berfase

**Dibuat:** 2026-08-04 · **Diperbarui:** 2026-08-05 (audit ulang menyeluruh — Siklus 2 ditambahkan)
**Baseline:** HEAD `39cae8c` · FROZEN `094b696` (10 file, integritas OK)
**Status dokumen:** Fase 0-12 SELESAI (12 = opsi (b), tanpa perubahan frozen). T1 dimitigasi — sisa tindakan di sisi endpoint.
**SIKLUS 2 (2026-08-05): Fase 13-19 SELESAI.**
**SIKLUS 3 (2026-08-05, sore): Fase 20-21, 23 SELESAI. Fase 22 SEBAGIAN** — empat
temuan lapangan dari pemakaian nyata; lihat bagian SIKLUS 3 di akhir. Lihat
bagian [Siklus 2](#siklus-2--audit-ulang-2026-08-05) di akhir dokumen.
**Suite:** `pytest tests/ -q` → **2281 lulus, 0 gagal** · hijau juga dengan jaringan keluar diblokir · 6 run berturut tanpa crash (S-13 tuntas lewat S-14) · `ruff` bersih ·
FROZEN OK (10 file, baseline `094b696`).

---

## Status ringkas

| Fase | Judul | Status |
|------|-------|--------|
| 0 | Baseline & jaring pengaman | ✅ SELESAI |
| 1 | Pasang dependency runtime | ✅ SELESAI |
| 2 | Pulihkan state provider | ✅ SELESAI |
| 3 | Verifikasi voice end-to-end | ✅ SELESAI |
| 4 | Kegagalan boot harus terlihat | ✅ SELESAI |
| 5 | Hapus blocking tanpa timeout | ✅ SELESAI |
| 6 | Regression test anti-kambuh | ✅ SELESAI |
| — | *Di luar rencana:* provider custom + fix OAuth | ✅ SELESAI |
| 7 | Pulihkan suite pytest utuh | ✅ SELESAI |
| 8 | Lunasi utang test (14) + T7 | ✅ SELESAI |
| 9 | Keputusan produk (4 kegagalan) | ✅ SELESAI |
| 10 | Pengerasan keamanan | ✅ SELESAI |
| 11 | Jujurkan capability & config | ✅ SELESAI |
| 12 | Konsolidasi dual stack | ✅ SELESAI — opsi (b): satu entry point ditegakkan |
| **T1** | **`http://` polos ke endpoint custom** | ⚠️ **DIMITIGASI — keputusan hardware ada di Takeda** |

### Perjalanan suite

| Titik | Lulus | Gagal | Crash |
|---|---|---|---|
| Sebelum apa pun (system python) | 1990 | 41 | 1 |
| Setelah Fase 1-2 | 2013 | 18 | 1 |
| Setelah provider custom + fix OAuth | 2021 | 19¹ | 1 |
| Setelah Fase 5-6 | 2037 | 18 | 1 |
| Setelah T1 | 2056 | 18 | 1 |
| Setelah Fase 7 — `pytest tests/ -q` SATU perintah | 2060 | 19² | 0 |
| Setelah Fase 8 | 2076 | 4 | 0 |
| Setelah Fase 9 | 2083 | 0 | 0 |
| **Setelah Fase 10 (sekarang)** | **2097** | **0** | **0** |

² +4 lulus = test yang dulu tak pernah dijalankan karena crash. +1 gagal = `test_mk50_routing_seams::test_telegram_tool_backed_t1_degrades_honestly_without_agent`, yang **lulus sendirian tetapi gagal di suite penuh** — polusi antar-test yang secara struktural tidak mungkin terlihat oleh runner per-file. Lihat T7.

¹ +1 sementara: `test_relay.py` bentrok port 8791 dengan JARVIS yang sedang berjalan. Bukan regresi — terbukti hijau lagi 24/24 setelah JARVIS ditutup, tanpa perubahan kode apa pun.

---

## Aturan yang berlaku di semua fase

1. **Jangan sentuh file FROZEN** tanpa approval eksplisit Takeda: `main.py`, `ui.py`, `core/stt.py`, `core/tts.py`, `core/voice_listener.py`, `core/prompt.txt`, `jarvis/core/wake.py`, `jarvis/ui/theme.py`, `jarvis/ui/orb.py`, `config/jarvis.ico`.
2. **Perbaikan masuk lewat seam editable**: `jarvis/integrations/`, `jarvis/ui/window.py`, `jarvis/main.py`, `pyproject.toml`, `config.yaml`.
3. **Setiap fase punya gate exit** yang harus hijau sebelum lanjut.
4. **`unset PYTHONPATH`** sebelum apa pun yang mengimpor `jarvis.*`.
5. **Qt headless**: `QT_QPA_PLATFORM=offscreen`, simpan `QApplication` **dan widget host** di variabel global — tanpa referensi Python yang hidup, widget ter-GC di tengah test (`wrapped C/C++ object ... has been deleted`).
6. **Candidate WA0 staged jangan disentuh.**
7. **Buktikan test RED dulu.** Test penjaga yang tidak pernah terbukti merah tidak berguna.

### Gate standar

```bash
unset PYTHONPATH
export QT_QPA_PLATFORM=offscreen
.venv/Scripts/python.exe scripts/verify_frozen.py   # FROZEN integrity: OK
.venv/Scripts/python.exe -m ruff check .            # All checks passed!
git diff --check                                    # kosong
```

---

# BAGIAN I — SUDAH DIJALANKAN

## Fase 0 — Baseline ✅

Backup `providers.json`, `uv.lock`, daftar paket disimpan di scratchpad sesi (**bukan** di repo, supaya `git status` tetap bersih).

## Fase 1 — Dependency runtime ✅

```bash
uv sync --frozen --extra voice --extra vision --extra agent --extra dev
```

**112 paket masuk, 0 dibuang, `uv.lock` md5 tidak berubah** (itu gunanya `--frozen`).

Gate terbukti:
```
.venv/Scripts/python.exe -c "import main"   →  IMPORT_OK   (dulu: ModuleNotFoundError sounddevice)
smoke import 11 modul                       →  11/11 OK    (dulu: main dan ui FAIL)
```

> **Koreksi rencana awal:** langkah "pasang manual `croniter` dan `python-telegram-bot`" **tidak perlu** — keduanya sudah ada di extra `[agent]` (`pyproject.toml:82,88`). Perintah `uv sync` di atas sudah membawanya.

## Fase 2 — State provider ✅

`providers.set_active("gemini")` lewat API modul, bukan edit tangan, supaya `reset_clients()` ikut jalan.

Hasil: **7/7 subsistem ONLINE**, `boot.done failed=[]` (dulu 6 FAILED).

> **Koreksi rencana awal:** `routing.heavy.provider: custom` **BUKAN kerusakan**. Itu default yang di-commit di `config.yaml:731`, dan komentarnya menyatakan perilaku degrade jujur memang disengaja. Tidak diubah.

## Fase 3 — Verifikasi voice end-to-end ✅

Terbukti dari log sesi live, bukan asumsi:

| Jalur | Bukti |
|---|---|
| Teks | `text="hi"` → `SPEAKING` → `turn.outcome success` — **tanpa** `nlp.routed`/`handle_error`, artinya `on_text_command` ter-bind dan masuk sesi Live |
| Suara | 11 giliran berturut-turut dengan `had_input=True`, state `TRANSCRIBING` tercapai |
| Wake | `wake.calibrated noise_floor=0.002`, `wake.ignored_session_active` ×4 (tepukan terdeteksi, benar diabaikan saat sesi aktif) |
| Tool | `system_reflex ok=True`, `open_app ok=True` |
| Vision | kamera 5.502 byte disuntikkan balik ke sesi |

Shutdown bersih `exit 0` di setiap sesi — kekhawatiran thread `daemon=False` tidak terwujud.

## Fase 4 — Kegagalan boot terlihat ✅

**Temuan yang mengubah rancangan:** UI **sudah punya** mesin notifikasinya — `window.py:1989-1991` mendorong notifikasi untuk setiap `boot.check` dengan `ok=False`. Yang hilang: pipeline suara **tidak pernah menerbitkan `boot.check`**. Jadi pekerjaannya menyambungkan ke bus, bukan membangun UI baru.

Tambahan di `jarvis/main.py`:

| Fungsi | Guna |
|---|---|
| `_import_legacy()` | seam impor terpisah — kegagalan bisa diuji tanpa merusak lingkungan |
| `_voice_failure_detail(exc)` | exception → kalimat yang bisa ditindaklanjuti |
| `_publish_voice_status(ok, detail)` | terbitkan `boot.check` untuk `core.voice`; dibungkus try/except supaya visibilitas tak pernah mematikan boot |
| `_install_voice_seams(legacy, logger)` | 13 seam dipindah keluar dari `runner()`, isi identik |
| `voice.pipeline_ready` | log + publish ONLINE tepat setelah `on_text_command` ter-bind |

Klasifikasi pesan:
```
ModuleNotFoundError    → "Dependency hilang: <nama>. Jalankan: uv sync --extra voice ..."
TimeoutError           → pesan timeout apa adanya
api key / unauthorized → "API key bermasalah — buka Settings."
lainnya                → sebab asli, 200 karakter
```

**Belum dilakukan:** spanduk permanen. Yang dipakai adalah `notifications.push(severity="error")` yang sudah ada — tersimpan di drawer, bukan menetap di layar. Kalau Takeda mau spanduk sungguhan, itu pekerjaan UI tersendiri.

## Fase 5 — Blocking tanpa timeout ✅

`jarvis/ui/window.py` (**`ui.py` FROZEN tidak disentuh**):

```python
def wait_for_api_key(self, timeout=None, should_stop=None) -> bool
```
Default dari `config.get("voice.api_key_wait_timeout_s", 300)`.

Nilai baliknya **dipakai** — timeout tak berguna kalau pemanggil mengabaikannya:
```python
if not _await_api_key(ui, stop_requested.is_set):
    raise TimeoutError("API key belum diisi — buka Settings, simpan key, "
                       "lalu jalankan ulang JARVIS.")
```
lalu jatuh ke jalur visibilitas Fase 4.

Adapter kompatibilitas untuk UI lama (`ui.py` hanya punya `wait_for_api_key(self)` dan mengembalikan `None`):
```python
try:
    result = ui.wait_for_api_key(should_stop=should_stop)
except TypeError:                    # UI lama
    result = ui.wait_for_api_key()
return result is not False           # None dari UI lama = tetap sukses
```
Adapter ini punya testnya sendiri.

## Fase 6 — Regression test ✅

| Test | Jumlah | Catatan |
|---|---|---|
| `tests/test_runtime_deps_present.py` | 8 | 6.1 |
| `tests/test_voice_pipeline_failure_visible.py` | 8 | Fase 4 + adapter Fase 5 |
| `tests/test_wait_for_api_key_bounded.py` | 5 | 6.3 |
| `tests/test_oauth_disconnect_confirm.py` | 3 | di luar rencana |
| **Total test baru** | **24** | semua dibuktikan RED lebih dulu |

> **6.2 tidak ditulis terpisah** — `test_pipeline_sukses_menerbitkan_core_voice_online` dan `test_ui_lama_tanpa_argumen_tetap_didukung` sudah meng-assert `ui.on_text_command is not None`. Duplikat tidak menambah perlindungan.

**6.1 diperluas dari rencana.** Rencana awal hanya "modul bisa diimpor". Jebakan `openai` membuktikan itu tidak cukup — paket bisa terpasang tapi tidak terdeklarasi, lalu lenyap pada `uv sync` berikutnya. Jadi dua lapis: dapat diimpor **DAN** terdeklarasi di `pyproject.toml`.

Empat modul dijaga, dipilih dengan satu prinsip — **kegagalannya senyap**:
```
sounddevice   main.py:35         ditelan except di jarvis/main.py
google.genai  main.py:36         sesi Live mati tanpa pesan
openai        llm_client.py:75   gagal hanya saat chat pertama
croniter      cron.py:51         _next_run() kembalikan None diam-diam
```
Parser deklarasinya diverifikasi tidak vakum: 52 nama terbaca, kontrol negatif (`tensorflow`, nama karangan) benar-benar `False`.

## Di luar rencana — provider custom & OAuth ✅

### Provider custom Takeda berfungsi

Blokirnya: paket `openai` tidak terpasang, padahal `llm_client.py:75` mengimpornya untuk semua provider `openai_compat`.

```
base_url : http://43.167.18.81:20128/v1
model    : ds/deepseek-v4-flash
ok       : True    content: 'OKE'    stop: stop
```

**Perilaku yang perlu diingat:** dengan `max_tokens=20` jawabannya **kosong** — model ini membakar ~33 token reasoning dulu. Baru pada `max_tokens=200` teksnya muncul. Balasan kosong tanpa error = batas token, bukan koneksi putus.

**Jebakan yang dicegat:** `openai` tidak terdaftar di `pyproject.toml`. Uji buktinya:
```
uv sync --frozen --dry-run  →  Would uninstall: openai==2.53.0, jiter==0.16.0
```
Maka: `openai>=2.0` ditambahkan ke extra `[agent]`, lalu `uv lock` regenerasi — **+66 baris, 0 dihapus, nol pergeseran versi paket lain**. Setelahnya `uv sync --frozen` tidak lagi membuangnya.

> **Pelajaran:** menambah dependency ke `pyproject.toml` saja **tidak cukup**. Tanpa `uv lock`, `uv sync --frozen` memakai lock basi dan tetap membuang paketnya.

### Bug OAuth: login sukses lalu langsung putus

Bukti di `logs/jarvis.log`:
```
09:18:48  oauth.connected  provider=openai_oauth
09:18:48  oauth.logout     provider=openai_oauth    ← detik yang SAMA
```

Penyebab: `settings_providers.py:480-482` memakai **satu tombol** untuk HUBUNGKAN dan PUTUSKAN. Setelah login sukses labelnya berubah jadi `PUTUSKAN`, dan cabang putus **langsung memanggil `logout()` tanpa bertanya**. Satu klik berikutnya — sangat wajar setelah browser selesai — menghancurkan token. Gejala bagi user: "sudah terhubung tapi tetap gagal terkoneksi dengan model".

Perbaikan: `_confirm_disconnect()` dengan default **No**, pesannya mengarahkan ke tindakan yang benar.

**Langkah manual yang tetap wajib:** `configured()` untuk OAuth = `enabled AND bool(model) AND supports("chat")` (`providers.py:146-148`), dan DEFAULTS `openai_oauth` punya `model: ""` — sengaja, karena katalog Codex spesifik per akun. Jadi setelah login: **pilih model, lalu SIMPAN**. Tanpa itu `configured()` tetap False walau token sehat.

---

# BAGIAN II — TEMUAN BARU (belum ada fasenya)

Semua ini muncul **saat eksekusi**, tidak ada di rencana awal.

## 🔒 T1 — `http://` polos ke endpoint custom — DIMITIGASI SEBAGIAN

`config/providers.json`: `base_url = http://43.167.18.81:20128/v1`

API key Takeda dikirim sebagai header `Authorization` **dalam bentuk terbaca** melewati internet publik.

### Probe TLS 2026-08-04 — tidak ada jalur aman di host itu

```
port 20128   TCP terbuka, TLS -> SSLError WRONG_VERSION_NUMBER
             (dengan maupun tanpa verifikasi sertifikat — server bicara HTTP polos)
port 443     ConnectionRefused
port 8443    ConnectionRefused
```

**Kesimpulan: endpoint itu HTTP-only.** Tidak ada varian HTTPS untuk dipindahi, jadi masalahnya tidak bisa diselesaikan dari sisi repo.

### Yang sudah dikerjakan — membuatnya tidak lagi senyap

Prinsipnya sama dengan Fase 4: kalau tidak bisa dicegah, minimal jangan diam.

| Tempat | Perubahan |
|---|---|
| `jarvis/agent/providers.py` | `insecure_plaintext_base_url()` — `http://` ke host **non-lokal**. Loopback/IP privat/`.local` sengaja dikecualikan: plaintext wajar di sana, dan peringatan cerewet akan diabaikan justru saat penting |
| `jarvis/agent/llm_client.py` | `agent.llm.insecure_base_url` diterbitkan tepat saat klien dibangun — momen credential mulai mengalir |
| `jarvis/ui/settings_providers.py` | status panel menampilkan `⚠ TIDAK TERENKRIPSI` |
| `tests/test_insecure_base_url_warning.py` | 19 test, termasuk pemastian peringatan **tidak ikut membocorkan** kuncinya |

Terverifikasi dengan config nyata:
```
provider aktif : custom
ditandai bahaya: True
PERINGATAN TERBIT: agent.llm.insecure_base_url  host=43.167.18.81
```

### Keputusan yang masih milik Takeda

Repo kini memperingatkan, tetapi **paparannya tetap ada**. Pilihan nyata:

1. **Aktifkan TLS di endpoint** bila Takeda mengendalikannya — satu-satunya perbaikan sesungguhnya.
2. **Terowongan terenkripsi** (stunnel / SSH / WireGuard) lalu arahkan `base_url` ke ujung lokal terowongan — `insecure_plaintext_base_url()` otomatis diam karena tujuannya jadi loopback.
3. **Putar kunci** dan pakai kunci berkuota terbatas khusus endpoint ini, dengan asumsi ia bocor.
4. **Terima risikonya** secara sadar — sekarang setidaknya tercatat dan terlihat.

Kunci yang sekarang harus dianggap sudah terpapar sejak pemakaian pertama, apa pun pilihannya.

## T2 — 429 RESOURCE_EXHAUSTED di lane teks

```
agent.llm.retry        ClientError: 429 RESOURCE_EXHAUSTED  ×2
agent.llm.chat_failed  ClientError: 429 RESOURCE_EXHAUSTED  ×2
```

Kuota Gemini habis di lane teks/agent. **Sesi Live tidak terpengaruh** — 13 giliran suara sukses di menit yang sama. Retry sudah ada dan bekerja; batasnya yang tercapai.

**Diperiksa 2026-08-08:** `routing.heavy.provider = custom`, jadi lane berat memang tidak lagi memakai kuota Gemini. Lane ringan tetap `gemini` (pilihan Takeda), sehingga 429 masih mungkin di sana. Belum terlihat lagi di log; dibiarkan terbuka sampai ada bukti dari pemakaian nyata, bukan ditutup karena sunyi.

## T3 — `test_relay.py` memakai port tetap — SELESAI ✅ (lihat Fase 10.1)

Test memakai port webhook dari `.env` (8791). Kalau JARVIS berjalan, test menabrak server sungguhan dan dapat HTTP 401. Perlu port ephemeral atau isolasi. Masuk wilayah Fase 10.

## T4 — `core.browser DEGRADED` — TERJELASKAN 2026-08-08, belum diperbaiki

Boot melaporkan `core.browser DEGRADED — system browser ready; no embed driver`, padahal PyQt6-WebEngine terpasang dan cek terpisah di proses lain mengembalikan `QtWebEngine ready`.

**Penyebabnya ditemukan dan bisa direproduksi.** `PyQt6.QtWebEngineWidgets` harus diimpor SEBELUM `QApplication` dibuat; sesudahnya importnya gagal. Diukur di dua proses bersih:

```
tanpa QApplication   -> CheckResult(ok=True, degraded=False, 'QtWebEngine ready')
sesudah QApplication -> CheckResult(ok=True, degraded=True,  'system browser ready; no embed driver')
```

Jadi bukan kosmetik dan bukan kesalahan deteksi: driver embed benar-benar tidak tersedia pada saat boot memeriksanya, karena urutannya. Log boot nyata (`logs/jarvis.log`, 2026-08-05) memang berbunyi `DEGRADED`.

**Perbaikannya** adalah memindahkan import WebEngine ke sebelum `QApplication` dibuat — tetapi `QApplication` lahir di jalur UI, dan `main.py`/`ui.py` FROZEN, jadi ini butuh seam dan keputusan cakupan. Belum dikerjakan.

## T5 — FAISS tidak ada di extra mana pun

`memory.faiss_missing` muncul di setiap boot; memori semantik nonaktif. `faiss-cpu` tidak terdaftar di `[voice]`/`[vision]`/`[agent]`. Kosmetik, tapi berarti satu fitur mati diam-diam — kelas yang sama dengan insiden utama.

**Diperiksa ulang 2026-08-08:** `import faiss` → `ModuleNotFoundError`, dan `pyproject.toml` masih hanya menyebutnya di komentar (baris 213), bukan sebagai dependensi. Masih TERBUKA, tidak berubah.

## T8 — `test_voice_playback_fix` flaky di bawah beban — TERBUKA

`test_play_audio_mengeluarkan_semua_chunk_dan_drain` gagal **satu kali** saat suite penuh dijalankan, lalu:

```
5x standalone       -> 3 passed, 3 passed, 3 passed, 3 passed, 3 passed
ulangan suite penuh -> 2102 passed, 0 failed
```

Bukan regresi: baik test itu maupun `jarvis/integrations/voice_playback_fix.py` tidak disentuh sesi ini (`git status` kosong untuk keduanya).

Penyebabnya bergantung waktu — `tests/test_voice_playback_fix.py:98` menunggu `await asyncio.sleep(0.15)` dengan `tail_grace_s=0.02` dan `poll_s=0.01`. Di mesin yang sedang terbebani suite penuh, 0,15 detik bisa tidak cukup untuk menuntaskan drain.

**Perbaikan yang disarankan:** ganti tidur tetap dengan menunggu kondisi (poll sampai antrean kosong dengan batas waktu longgar), bukan menaikkan angka tidurnya — menaikkan angka hanya menggeser ambangnya, tidak menghapus keretanannya.

## T7 — Polusi antar-test — SELESAI ✅

`test_telegram_tool_backed_t1_degrades_honestly_without_agent` lulus sendirian tetapi gagal di suite penuh. Baru terlihat setelah Fase 7 — runner per-file secara struktural tidak bisa menemukan kelas bug ini. Pembenaran terbaik untuk Fase 7.

**Pencemar ditemukan lewat bisect biner** atas 123 file yang berjalan lebih dulu (7 iterasi): `tests/test_gws_read_activation.py`.

Baris 27 file itu menjalankan `registry.all_tools(refresh=True)` **selagi `google_auth.has_read_scope` ditambal `True`**. `monkeypatch` memulihkan fungsinya, tetapi **cache `_tools` di registry tidak ikut dipulihkan** — jadi test berikutnya melihat tool Google Calendar seolah aktif.

### Jebakan kedua: urutan teardown fixture

Perbaikan pertama saya (fixture yang me-refresh cache) **tidak bekerja**, dan kegagalannya menyesatkan: pesannya berubah, seolah membaik.

Sebabnya urutan. Fixture di-finalisasi terbalik dari urutan setup. Dengan tanda tangan `(monkeypatch, restored_registry_cache)`, refresh berjalan **sebelum** `monkeypatch` melepas tambalan — sehingga menyimpan ulang state palsu yang sama.

Perbaikannya menukar urutan parameter jadi `(restored_registry_cache, monkeypatch)`.

**Pelajaran:** fixture yang memulihkan state global harus diminta **sebelum** `monkeypatch` di daftar parameter, supaya ia di-teardown belakangan.

## T6 — Model OAuth harus dipilih manual

Lihat bagian OAuth di atas. Takeda memilih perbaikan tanpa auto-pilih model, jadi langkah ini memang tetap manual. Dicatat supaya tidak terlihat seperti bug di kemudian hari.

---

# BAGIAN III — FASE YANG BELUM DIJALANKAN

## FASE 7 — Pulihkan suite pytest utuh — SELESAI ✅ (diverifikasi 2026-08-08)

**Status dokumen ini sempat basi.** Diperiksa ulang: seluruh suite kini jalan
dalam SATU proses — `2518 passed`, dan `tests/test_actionpanel_toggle.py`
sendiri `5 passed`. Crash `0xC0000409` tidak lagi terjadi. Kesehatan repo bisa
diukur dengan satu perintah, yang justru dipakai di setiap fase Siklus 2–4.
Catatan investigasi di bawah dipertahankan sebagai riwayat.


`tests/test_actionpanel_toggle.py` crash native `0xC0000409` (STACK_BUFFER_OVERRUN, Qt offscreen) dan **membunuh seluruh proses pytest**. File itu punya 5 test; 1 lulus lalu proses mati, 4 tidak sempat jalan.

Selama ini belum diperbaiki, kesehatan repo tidak bisa diukur dengan satu perintah — semua angka di dokumen ini dihasilkan runner per-file.

### Akar masalah — BUKAN yang saya duga

Semua hipotesis lifecycle Qt saya **terbantah**. `test_actionpanel_toggle.py` sudah memegang `_APP` sejak awal (baris 11). Memegang referensi `JarvisUI`: tidak menolong. Memakai satu window bersama: tidak menolong. Menghentikan animasi: tidak menolong.

Bisect berpasangan menunjukkan polanya:
```
T1(toggle vision) + apa pun    -> crash
T3 + T4 (tanpa vision)         -> OK
T3 + T1 (vision di test KEDUA) -> OK
```

Lalu isolasi per-langkah lewat subprocess terpisah:
```
buka saja                  OK
buka + tutup               CRASH  (di processEvents, saat fade berjalan)
vision_panel.NO_FX = True  OK
stage._fade_ms = 0         OK
_pix = object()            CRASH
_pix = QPixmap(64, 48)     OK      ← penentu
```

**Sebabnya ada di test itu sendiri, bukan di produk.** Test mengisi `win.vision_panel._pix = object()` untuk membuat `has_payload` bernilai True. Tetapi `VisionPanel.paintEvent` (`jarvis/ui/overlays.py:351`) memanggil `self._pix.transformed(...)`.

Selama panel terbuka, paintEvent tidak pernah menyentuh objek palsu itu. Saat ditutup, `ContentStage.hide_all()` memasang `QGraphicsOpacityEffect` dan menganimasikannya — dan efek grafis **memaksa repaint sungguhan ke buffer offscreen**. `paintEvent` berjalan, `object().transformed` meledak **di dalam callback paint Qt**, tempat exception Python tidak bisa dipropagasikan. Proses mati `0xC0000409` dan membawa seluruh sesi pytest.

### Perbaikan

`tests/test_actionpanel_toggle.py`: helper `_payload()` mengembalikan `QPixmap(64, 48)` asli, dipakai di tiga tempat yang dulu memakai `object()`. Produk tidak disentuh — tidak ada bug produk di sini.

Hasil: **5/5 lulus, exit 0.** Empat test yang tak pernah dijalankan sejak lama kini benar-benar dieksekusi.

### Gate exit — TERCAPAI

```
pytest tests/ -q   →  19 failed, 2060 passed, 5 warnings in 123.76s
```
Selesai sampai baris ringkasan, nol crash. Pertama kalinya kesehatan repo bisa diukur satu perintah.

### Pelajaran yang lebih luas

Payload palsu (`object()`, `Mock()`) pada widget yang punya `paintEvent` adalah ranjau: aman selama widget tak pernah dilukis, mematikan begitu ada yang memicu repaint. Gejalanya muncul jauh dari penyebabnya — di test lain, dalam bentuk crash proses, bukan assertion. **Pada widget yang melukis, pakai objek Qt sungguhan.**

## FASE 8 — Lunasi utang test — SELESAI ✅

**Gate tercapai: 19 → 4 kegagalan, 2076 lulus, 0 crash.** Empat sisanya persis Fase 9.

Dugaan awal "dua kelompok akar masalah" ternyata **terlalu sederhana** — nyatanya lima, dan dua di antaranya bukan sekadar ekspektasi basi.

| File | Gagal | Akar sebenarnya | Perbaikan |
|------|-------|-----------------|-----------|
| `test_browser_routing_p0.py` | 5 | fixture menambal `webbrowser.open`, tetapi `open_url` memakai `native_actions.open_external_url` yang **di Windows memanggil `os.startfile`** | tambal seam sebenarnya + 2 lapis pengaman |
| `test_browser_routing_p0.py` | 1 | ContentStage kini juga mendaftarkan `studio` (Studio A-D) | perbarui ekspektasi |
| `test_browser_takeover_and_panel.py` | 2 | awareness dipensiunkan dari panel default (UI U1) | opt-in lewat config, cakupan GlyphButton dipertahankan + 1 test baru untuk `focus_mode` di panel default |
| `test_mk50_routing_seams.py` | 3 | stub kurang `_pending_voice_proposal_id` (window.py:694) | lengkapi stub |
| `test_phase2_ingress.py` | 2 | stub kurang `_record_task_result` (window.py:2002); `render_ack` tak lagi diimpor `interactive_dispatch` | lengkapi stub, buang tambalan mati |
| `test_phase2_ingress.py` | 1 | **seam ACK pindah** ke `ack_composer.compose_ack` (interactive_dispatch.py:66); teks dipilih dari daftar template | tambat composer supaya deterministik |

### ⚠️ Temuan serius: suite benar-benar membuka browser

`test_browser_routing_p0.py` menambal `webbrowser.open`, padahal `MainWindow.open_url` memanggil `jarvis.core.native_actions.open_external_url`, dan di Windows fungsi itu memakai `os.startfile` — **jalur yang sama sekali tidak tertambal**.

Diverifikasi langsung: `os.startfile('https://example.com')` sungguh terpanggil saat test berjalan. Artinya setiap kali suite dijalankan di Windows, browser default benar-benar diluncurkan beberapa kali. Itu bukan sekadar assertion gagal — itu efek samping nyata yang lolos tanpa disadari.

Sekarang tiga lapis ditambal (`open_external_url`, `webbrowser.open`, `os.startfile`) sehingga tidak ada jalur yang lolos di platform mana pun.

**Pelajaran:** menambal seam yang salah tidak selalu membuat test gagal dengan jujur — kadang ia diam-diam membiarkan efek samping sungguhan terjadi.

## FASE 9 — Keputusan produk — SELESAI ✅

**Gate tercapai: 4 → 0 kegagalan. Suite hijau penuh, 2083 lulus.**

Empat kegagalan ternyata **tiga** keputusan; satu lagi utang test yang menyamar.

### 9.1 `buka youtube` — CLARIFY dipertahankan, test dibuat deterministik

`router.py:417` menanyakan "Aplikasi YouTube atau buka di browser?" saat sebuah kata cocok dengan aplikasi terpasang DAN situs terkenal. Komentar di kode menyebut ini perbaikan bug: *"Menebak di sini persis bug yang dilaporkan."*

**Cacat kedua yang lebih penting: test lama machine-dependent.** `youtube` tidak ada di `_APP_HINTS`; yang memicu CLARIFY adalah entri Start Menu mesin penguji (`resolve('youtube')` → `'YouTube'` source `start_menu`). Di mesin tanpa entri itu, test lama LULUS.

Perbaikan: assertion inti diubah sesuai nama test (bukan `OPEN_BROWSER_AGENT`), lalu **dua test baru dengan `app_registry` di-stub** menutup ketiga cabang — situs saja → `OPEN_URL`, situs+aplikasi → `CLARIFY`, aplikasi saja → `OPEN_APP`. Cakupan naik, ketergantungan mesin hilang.

### 9.2 Browser eksternal — ternyata utang test, bukan keputusan

`open_browser_agent` (window.py:1901) memakai `open_external_url` → `os.startfile`, sedangkan test menambal `webbrowser.open`. **Kasus ketiga** dari pola yang sama; test ini pun diam-diam meluncurkan browser sungguhan. Ditambal tiga lapis.

### 9.3 Identitas subagent — `delegation` dipertahankan

`ExecutionContext.for_child` (execution_context.py:34) sengaja mengubah `source` menjadi `delegation`, **mewarisi `actor_id`**, dan mencabut toolset `desktop_safe`. Jadi subagent kehilangan otoritas desktop tetapi pertanggungjawabannya tetap terlacak.

Mengembalikan `source` ke `telegram` berarti subagent memperoleh kembali hak kanal remote. Test diperbarui untuk menegaskan batas ini, plus assertion baru bahwa `desktop_safe` benar-benar tercabut — kontrak keamanannya kini terkunci, bukan sekadar tersirat.

### 9.4 Hint ikon Studio — celah produk, diperbaiki di produk

`config.yaml:294` memuat `studio` di ikon default, tetapi `HINT_TEXT` tidak punya kuncinya — hover ikon Studio tidak memunculkan tooltip. Ditambahkan `"studio": "Content Studio"` di `jarvis/ui/action_hint.py` (bukan file frozen), selaras dengan tooltip yang sudah ada di `actionpanel.py:120`.

Ini satu-satunya perubahan **produk** di Fase 8-9; sisanya seluruhnya sisi test. Kini 13 dari 13 ikon default punya hint.

## FASE 10 — Pengerasan keamanan — SELESAI ✅

### 10.1 Isolasi port — ternyata BUG PRODUK, bukan bug test

Dugaan lama saya keliru. `test_relay.py` sudah benar sejak awal: ia mengoper `port=0` dan memakai `tmp_path`. Yang salah ada di produk:

```python
self.port = int(port or _env("RELAY_WEBHOOK_PORT", "8791"))   # SEBELUM
```

`0` itu **falsy**, jadi idiom baku "pilih port bebas" jatuh ke default env dan setiap pemanggil ephemeral diam-diam **merebut port produksi 8791**. Log membuktikannya: dua receiver berbeda sama-sama melaporkan `relay.webhook_started port=8791`.

Lebih buruk lagi di Windows: dengan `SO_REUSEADDR` dua proses bisa sama-sama "berhasil" bind ke port yang sama, sehingga permintaan test nyasar ke server produksi — itulah HTTP 401 misterius yang muncul saat JARVIS berjalan.

Perbaikan: `int(port if port is not None else _env(...))`. Lima test baru di `tests/test_relay_webhook_binding.py`.

**Terbukti**: dengan 8791 sengaja diduduki proses lain, `test_relay.py` + test baru → **29 lulus**. Sebelum perbaikan, kondisi yang sama meruntuhkannya.

### 10.2 Skrip elevasi tidak lagi di temp bersama

`_elevation_script()` menulis `.bat` di `~/.jarvis/fw/` memakai ulang `_strict_dir`/`_strict_file` dari `secrets_store`, lalu **menghapusnya saat context keluar** — termasuk bila terjadi exception.

Berkas ini dieksekusi dengan hak Administrator lewat `ShellExecuteW(..., "runas", ...)`. Selama ia berada di `tempfile.gettempdir()`, siapa pun yang bisa menulis di sana berpeluang mengganti isinya di antara penulisan dan eksekusi.

Ikut dirapikan:
- `subprocess.run([bat], shell=True)` → `["cmd.exe", "/c", bat]` tanpa `shell=True`.
- Thread pembersih tertunda 5 detik dihapus; berkas kini hilang begitu context selesai (~2 detik lebih awal).

6 test di `tests/test_dashboard_elevation_script.py`.

### 10.3 `/auto-login` memakai pembatas laju yang sama dengan `/login`

Endpoint itu menerima credential sekali-pakai yang sama tetapi tidak punya pembatas apa pun. Kini memakai `_auth_rate_limiter` yang persis sama — satu kebijakan, bukan dua.

3 test di `tests/test_dashboard_autologin_rate_limit.py`, **RED dibuktikan dengan menonaktifkan pembatasnya**: 2 gagal tanpa, 3 lulus dengan.

> **Catatan jujur:** RED pertama saya untuk butir ini TIDAK sah — test gagal karena saya menyetel `limiter.limit` padahal atribut sebenarnya `_limit`, jadi test itu diam-diam tidak menguji apa pun. Diperbaiki dengan memasang limiter baru lewat konstruktor publik. Menyetel atribut privat di test adalah cara mudah membuat test yang tampak hijau tanpa menguji apa pun.

## FASE 11 — Jujurkan capability & config — SELESAI ✅

### ⚠️ Dua temuan saya sendiri TERBANTAH di fase ini

Fase ini sebagian besar berakhir dengan mengoreksi audit saya, bukan mengoreksi repo. Dicatat apa adanya.

### 11.1 — roadmap ternyata JAUH lebih jujur dari klaim saya

Temuan awal saya: *"roadmap melaporkan kemampuan yang belum ada di produksi."* **Berlebihan.**

Yang sebenarnya sudah tertulis di `.hermes/handoffs/current.md`:
- baris 349 — `WA9 rings live integration (wire RolloutRings ke lane nyata)` terdaftar sebagai **Next phase**, menunggu approval Takeda;
- baris 280 — *"supporting source does not prove the bounded call-agent program is runtime-wired, fixture-accepted, or live-proven."*

Dan `LIVE-PROVEN` itu **benar**: ada live run nyata dengan approval Takeda — tone loopback 144.000 sample → arm → kill → `session: cancelled`, `proof: done`.

Menurunkan status jadi `unproven-live` — yang sempat disetujui Takeda atas dasar pemaparan saya — justru akan **menghapus klaim yang benar**. Tidak dilakukan.

Masalah nyatanya jauh lebih sempit: baris 3 berbunyi `WA9-live COMPLETE — kill switch, LIVE-PROVEN x2`, sedangkan keterangan "belum tersambung runtime" berada 346 baris di bawahnya. Pembaca sekilas akan salah simpul.

Perbaikan (3 titik di `.hermes/handoffs/current.md`, semuanya menambah batasan tanpa menghapus fakta):
1. baris 3 — ditambah `library, BELUM tersambung runtime; wiring = Next phase`;
2. blok status WA9-live — ditambah bukti verifikasi grep 2026-08-04 dan catatan nol pemanggil produksi;
3. paragraf milestone — ditambah kotak cakupan: baca "COMPLETE" sebagai *tugas fase selesai*, bukan *kemampuan tersedia di produksi*.

Bonus: peringatan `⚠️ Pre-existing ... test_awareness_toggle gagal KeyError: 'awareness'` di dokumen itu ternyata **sudah basi** — test tersebut kini mendokumentasikan kontrak awareness-retired dan lulus 25/25. Ditandai beres.

### 11.2 — "config drift" saya sebagian besar TIDAK ADA

Temuan awal saya menyebut lima kunci "dibaca kode tetapi tanpa default": `whatsapp_web.call.enabled`, `whatsapp_web.call.rollout_ring`, `whatsapp_web.kill_switch`, `agent.browser.enabled`, `voice.enabled`.

Verifikasi ulang: **kode tidak pernah membaca satu pun dari kelimanya** (`grep config.get` → 0 file). Nama-nama itu **saya karang sendiri** saat probing audit; wajar mengembalikan `None`. Itu bukan drift, itu kesalahan metode saya — memprobe tebakan lalu memperlakukan hasilnya sebagai temuan.

Kunci yang benar-benar dibaca kode ada 16. Diuji satu per satu terhadap `config.yaml`:

```
15 dari 16  punya default          (agent.browser.*, whatsapp_web.*, voice.playback.*, ...)
 1 dari 16  TIDAK punya default    voice.api_key_wait_timeout_s
```

Satu-satunya drift nyata itu **saya sendiri yang perkenalkan di Fase 5**. Ditambahkan ke `config.yaml` di bawah `voice:` beserta komentar alasannya. `config.validate()` kini melaporkan nihil.

**Pelajaran:** memprobe nama kunci tebakan lalu melaporkan `None` sebagai temuan menghasilkan temuan palsu. Daftar kunci harus diturunkan dari `grep config.get` di kode, bukan dari ingatan.

## FASE 12 — Konsolidasi dual stack — SELESAI ✅ (opsi b)

### Duplikasinya JAUH lebih kecil dari dugaan awal

Rencana lama menyebut "`ui.py` 104 KB vs `jarvis/ui/window.py` 2.400+ baris". Itu membandingkan ukuran FILE, bukan permukaan yang benar-benar dibagi. Pengukuran AST atas kelas `JarvisUI` di kedua sisi:

```
ui.JarvisUI (FROZEN)       18 metode
jarvis.ui.window.JarvisUI  20 metode
dimiliki keduanya          18   ← MK50 superset KETAT
hanya di legacy             0
hanya di MK50               2   (_mic_meter, queue_greeting)
tanda tangan menyimpang     2   (__init__, wait_for_api_key)
```

Jadi risikonya bukan "dua implementasi besar saling menyimpang", melainkan **dua penyimpangan spesifik** — dan salah satunya sengaja dibuat Fase 5.

### Entry point: opsi (b) ternyata sudah benar de facto

- `readme.md:124-126` mendokumentasikan **hanya** `python -m jarvis.main`.
- `pyproject.toml:105` memaketkan **hanya** `jarvis = "jarvis.main:main"`.
- `main.py:1876` **masih** punya blok `__main__`, jadi `python main.py` tetap bisa dijalankan — tetapi tidak didokumentasikan dan tidak dipaketkan.

Artinya jalur legacy sudah pensiun dalam praktik; yang kurang hanyalah penegakan.

### Yang dikerjakan tanpa menunggu keputusan

`tests/test_ui_facade_parity.py` — 4 test, analisis AST statis (tanpa Qt):

| Penjaga | Menangkap |
|---|---|
| MK50 superset dari legacy | MK50 menyusut sehingga pipeline legacy kehilangan pijakan |
| penyimpangan harus terdaftar | penyimpangan BARU yang menyelinap tanpa alasan tertulis |
| daftar tidak boleh basi | entri yang sudah diselesaikan tapi lupa dibuang |
| entry point tetap satu | `python main.py` mulai didokumentasikan lagi |

Ketiganya **dibuktikan bisa merah**: menghapus entri `KNOWN_DIVERGENCE` → `tanda tangan menyimpang tanpa alasan tertulis: ['wait_for_api_key']`; menambah entri basi → `entri KNOWN_DIVERGENCE sudah tidak relevan: ['write_log']`.

Duplikasinya tidak dihapus — tetapi sejak sekarang **tidak bisa memburuk diam-diam**.

### Keputusan Takeda: opsi (b) — satu entry point ditegakkan

`readme.md` kini menyatakan eksplisit bahwa `python -m jarvis.main` adalah **satu-satunya entry point yang didukung**, dengan kotak peringatan yang menyebut alasannya secara konkret: jalur legacy memakai `ui.py` FROZEN yang masih memuat `wait_for_api_key` tanpa batas (`ui.py:2588`), sehingga JARVIS bisa diam total dan proses tak bisa keluar bersih. Blok arsitektur juga ditandai: skrip `main.py` di root = legacy, tidak didukung.

Test kelima `test_readme_menyatakan_jalur_legacy_tidak_didukung` mengunci ketiga pernyataan itu (entry point tunggal, peringatan legacy, rujukan `ui.py:2588`). **Dibuktikan merah** dengan menghapus kotak peringatan → `AssertionError: peringatan jalur legacy hilang dari readme`.

### Batas jujur dari opsi (b)

`main.py:1876` **masih** punya blok `__main__`, jadi `python main.py` secara teknis tetap bisa dijalankan. Menghapusnya berarti mengubah berkas FROZEN dan menerbitkan baseline frozen baru — di luar cakupan (b).

Artinya penegakan opsi (b) bersifat **dokumentasi + penjaga test**, bukan penghalang teknis. Bug `ui.py:2588-2590` masih ada dan masih terjangkau oleh siapa pun yang sengaja menjalankan skrip legacy. Yang berubah: tidak ada lagi dokumen yang mengarahkan ke sana, dan setiap upaya mendokumentasikannya kembali akan membuat suite merah.

Menutupnya sepenuhnya membutuhkan keputusan terpisah untuk mengeluarkan `main.py`/`ui.py` dari status frozen.

---

## Saran urutan berikutnya

```
SEKARANG — keputusan Takeda, bukan pekerjaan kode
  T1  aktifkan TLS / terowongan / putar kunci   (repo sudah memperingatkan)

KEMUDIAN
  Fase 10 keamanan + isolasi test
  Fase 11 kejujuran capability & config
  T4      selidiki core.browser DEGRADED
  T2      verifikasi ulang kuota 429

JANGKA PANJANG
  Fase 12 konsolidasi dual stack
```

---

## Kondisi "semuanya berfungsi"

- [x] `python -m jarvis.main` boot tanpa `voice.pipeline_failed`, `wake.disabled`, `mic_meter.unavailable`
- [x] `boot.done` memuat 7 subsistem di `online`, `failed=[]`
- [x] Perintah teks → ada balasan **dan** ada suara
- [x] Perintah suara → transkripsi masuk, ada balasan (11 giliran `had_input=True`)
- [x] Wake tepuk-ganda → terpicu (`wake.calibrated`, `wake.ignored_session_active`)
- [x] Kalau dependency dilepas paksa, JARVIS **memberitahu** — tidak diam *(Fase 4)*
- [x] Menunggu API key tidak menggantung selamanya *(Fase 5)*
- [x] Dependency yang gagal senyap dijaga test — terpasang **dan** terdeklarasi *(Fase 6)*
- [x] `pytest tests/ -q` selesai sampai ringkasan tanpa crash *(Fase 7)*
- [x] Utang test lunas — 19 → 4 kegagalan, semuanya berlabel Fase 9 *(Fase 8)*
- [x] **Kegagalan tersisa NOL** — suite hijau penuh *(Fase 9)*
- [x] Kalau credential melintas terbaca, JARVIS **memperingatkan** — log + panel Settings *(T1)*
- [ ] Credential tidak melintas dalam bentuk terbaca sama sekali *(T1 — butuh TLS di sisi endpoint; tidak bisa diselesaikan dari repo)*
- [x] `verify_frozen.py` → OK, baseline `094b696`
- [x] `ruff check .` → All checks passed!

Baris "memberitahu — tidak diam" itu yang paling penting, dan sekarang sudah tercentang. Sistem yang gagal dengan berisik bisa diperbaiki dalam hitungan menit. Sistem yang gagal dalam diam menghabiskan satu hari penuh — persis yang terjadi 2026-08-04.

---
---

# SIKLUS 2 — audit ulang (2026-08-05)

**Pemicu:** Takeda melaporkan 4 gejala lapangan + 1 error berulang setelah
Fase 0-12 dinyatakan selesai. Audit ulang dijalankan menyeluruh: suite penuh,
inventaris seluruh tool, pembuktian hidup jalur agent dan sub-agent.

## Apa yang benar-benar dijalankan di audit ini

| Uji | Perintah / metode | Hasil |
|---|---|---|
| Suite penuh | `pytest tests/ -q` | **2101 lulus, 1 gagal**, 83.8 s |
| Inventaris tool | enumerasi `registry.all_tools()` + `registry.schemas()` | **99 tool terdaftar**, 90 terekspos default |
| Descriptor capability | `capabilities.REGISTRY.descriptor_for_tool` untuk 99 tool | **0 tanpa descriptor** |
| Validitas schema | 90 schema OpenAI diperiksa nama + `parameters` | **0 rusak** |
| Import modul tool | 48 modul di `jarvis/agent/tools/` | **0 gagal import** |
| Gate ketersediaan | `available()` tiap modul | 11 modul mati (kredensial kosong) |
| Provider berat | `model_routing.heavy_resolution()` | `custom` siap |
| LLM mentah | `cl.chat([...])` | OK, 3.6 s, balas `PONG` |
| **Tool-calling** | `cl.chat` + schema `web_search` | OK — model memanggil tool dengan argumen benar |
| Agent loop tanpa tool | `loop.run("2+2 berapa?", max_iterations=3)` | OK, **1 iterasi** |
| Agent loop dengan tool | `loop.run(... web_search ..., max_iterations=6)` | OK, **2 iterasi**, `web_search` sukses 3.4 s |
| **Sub-agent** | `registry.execute("delegate_task", ...)` | **OK, 3.0 s**, ringkasan kembali normal |
| Kontak WhatsApp | `load_contacts()` | 1 kontak allowlist (`honbrew`) |

**Kesimpulan uji:** pipa inti **tidak rusak**. Agent loop, tool-calling, dan
sub-agent semuanya hidup dan benar. Empat gejala yang dilaporkan Takeda
**bukan** kerusakan pipa — semuanya cacat desain di lapisan di atasnya.

### Modul tool yang mati karena kredensial (bukan error)

`briefing_tool`, `calendar_safe`, `gcal_safe_agenda`, `gmail`, `gmail_safe`,
`google_calendar`, `google_drive`, `google_youtube`, `home_assistant`,
`image_gen`, `spotify` — 11 modul. Gate `available()` menolak dengan tertib,
tidak ada exception. Ini perilaku yang benar; dicatat agar tidak salah dibaca
sebagai kerusakan.

---

## Temuan

### S-1 — Klaim palsu "sudah menelepon" (KRITIS)

Gejala Takeda: *"jarvis memberi klaim palsu dengan mengatakan sudah menelpon
padahal tidak sama sekali."*

**Tiga lapisan gagal berturut-turut. Tidak ada satu pun yang menahan.**

**Lapis 1 — tool melapor sukses dari klik, bukan dari keadaan panggilan.**
[whatsapp_web.py:569-586](jarvis/integrations/whatsapp_web.py#L569-L586):

```python
button.click()
page.wait_for_timeout(500)
return {"state": "calling", "contact": contact.name}
```

Klik dilakukan, tunggu 500 ms, lalu **langsung mengaku `calling`**. Halaman
tidak dibaca ulang. Tombol hangup (`_HANGUP_SELECTORS`) — satu-satunya bukti
bahwa panggilan benar-benar berjalan — tidak pernah dicek. Bandingkan dengan
`hangup()` di baris 602-612 yang justru **memang** memeriksa elemen sebelum
mengklaim perubahan. Konsistensinya terbalik: jalur yang paling perlu bukti
justru yang paling tidak punya.

**Lapis 2 — tidak ada kontrak bukti untuk panggilan.**
[task_contracts.py](jarvis/agent/task_contracts.py) hanya mengimplementasikan
`YouTubeLatestPlayContract`. `prepare_task()` mengembalikan task polos untuk
segala hal lain, dan [dispatch.py:378-392](jarvis/agent/dispatch.py#L378-L392)
hanya memvalidasi bukti bila `prepared.contract is not None`. Untuk tugas
panggilan, **teks akhir model diteruskan apa adanya** ke `_on_done` lalu
diucapkan. Mesin verifikasi bukti sudah ada, terbukti bekerja, dan hanya
dipasang di satu jalur.

**Lapis 3 — prompt agent berat tidak melarang klaim tanpa bukti.**
[voice_native_tools.py:385](jarvis/integrations/voice_native_tools.py#L385)
punya aturan eksplisit *"Jangan mengaku berhasil sebelum hasil tool menyatakan
sukses"* — tapi itu untuk lane suara cepat.
[prompts/system.md](jarvis/agent/prompts/system.md) yang dipakai agent berat
**tidak memuat larangan itu sama sekali**. Aturan nomor 8 hanya menyinggung
kasus edit-diri-sendiri.

**Konsekuensi tambahan:** bila konfirmasi ditolak,
[registry.py:167-171](jarvis/agent/registry.py#L167-L171) mengembalikan string
gagal biasa. Tidak ada yang mencegah model menarasikan sukses sesudahnya.

---

### S-2 — Konfirmasi berlebihan pada panggilan WhatsApp (KRITIS)

Gejala Takeda: *"whatsapp call juga terlalu banyak meminta konfirmasi ... saya
ingin jarvis ... langsung mengeksekusi panggilan."*

**Akar masalah bukan jumlah tool berkonfirmasi — melainkan konfirmasi suara
yang tidak bisa dijawab dengan suara.**

[ui.py:108-141](jarvis/agent/adapters/ui.py#L108-L141) `UIAdapter.ask`
menunggu `Future` yang **hanya** diselesaikan oleh event BUS `confirm`/`cancel`.
Satu-satunya penerbit event itu:

* [window.py:953-972](jarvis/ui/window.py#L953-L972) — kata **yang DIKETIK**
  `confirm` / `konfirmasi` / `cancel` / `batalkan aksi`;
* [window.py:1974](jarvis/ui/window.py#L1974) — gestur jempol.

Ucapan "ya", "lanjut", "boleh" **tidak diterima**. Jadi perintah suara
"telepon Honbrew" memaksa Takeda pindah ke keyboard. Itulah yang terasa
sebagai "terlalu banyak meminta konfirmasi": bukan banyaknya pertanyaan, tapi
pertanyaan yang tidak bisa dijawab lewat kanal yang sedang dipakai.

Lapisan yang memperparah:

* `whatsapp_call`, `whatsapp_answer`, `whatsapp_send_message` menetapkan
  `requires_confirmation = True` **statis** di kelas
  ([whatsapp_web.py:177](jarvis/agent/tools/whatsapp_web.py#L177)). Tidak ada
  kunci config, tidak ada pengecualian untuk kontak allowlist, tidak ada
  jendela kepercayaan setelah persetujuan pertama.
* Kontak sudah lolos allowlist `data/whatsapp_contacts.json` **dan**
  `resolve_contact()` menolak apa pun di luar daftar. Konfirmasi kedua untuk
  satu kontak yang sudah di-allowlist adalah gerbang ganda pada risiko yang
  sama.
* Timeout `agent.confirm_timeout_s` = **300 detik**. Konfirmasi yang tidak
  terjawab menggantung 5 menit, lalu mengembalikan gagal, lalu model mencoba
  lagi — memakan iterasi (lihat S-5).

---

### S-3 — Hasil pencarian tidak menampilkan sumber di browser

Gejala Takeda: *"ketika saya meminta jarvis untuk mencarikan informasi jarvis
menampilkan sumber informasi tersebut dengan membuka browsernya."*

Perilaku sekarang [web.py:95-115](jarvis/agent/tools/web.py#L95-L115):
`web_search` menerbitkan `info.card` ke panel info UI dan **berhenti di situ**.
Browser tidak pernah dibuka.

Dua cacat terpisah:

1. **Mode `news` membuang URL sepenuhnya.** Baris kartu untuk berita disusun
   `f"{title}  [{source} {date}]"` — tanpa `href`. Mode `text` menyertakan URL,
   mode `news` tidak. Untuk permintaan berita, sumbernya bahkan **tidak terlihat
   sebagai teks**, apalagi terbuka.
2. **Desain sekarang justru melarang perilaku yang diminta.**
   [voice_native_tools.py:375](jarvis/integrations/voice_native_tools.py#L375)
   menginstruksikan: *"Cari fakta/berita web -> web_search; **jangan membuka
   browser hanya untuk pencarian**."* Ini keputusan lama demi latensi. Sekarang
   bertentangan langsung dengan keinginan Takeda dan harus dibalik secara sadar,
   bukan ditambal.

Modal yang sudah ada dan bisa dipakai: `jarvis/browser/agent_view.py` (panel
browser agent), tool `browser_navigate` / `browser_new_tab`, dan panel info
`jarvis/ui/info_panel.py`.

---

### S-4 — Interupsi suara mati, dan tidak aman dinyalakan apa adanya

Gejala Takeda: *"saya ingin jarvis bisa di interupt ... dan tidak terlalu
sensitiv pada noise atau suara disekitar."*

**Status sekarang: barge-in MATI.** [config.yaml:461](config.yaml#L461)
`voice.barge_in.enabled: false`, dengan alasan tertulis di komentar: *"speaker
echo can falsely interrupt playback"*. Sebuah test bahkan mengunci keadaan mati
itu (`tests/test_voice_barge_in.py:12`).

Detektornya [window.py:2348-2398](jarvis/ui/window.py#L2348-L2398) adalah
gerbang RMS ambang tetap:

| Parameter | Nilai | Masalah |
|---|---|---|
| `rms_threshold` | 0.14 | tetap — tidak menyesuaikan kebisingan ruangan |
| `min_ms` | 280 | satu-satunya penyaring transien |
| `cooldown_ms` | 2000 | hanya membatasi laju, bukan ketepatan |
| `tts_grace_ms` | 400 | hanya menutup echo di awal ucapan, bukan sepanjang ucapan |

Tidak ada: noise floor adaptif, pembeda suara-manusia vs bunyi, echo
cancellation, maupun konfirmasi kata. Menyalakannya apa adanya akan
menghasilkan persis kepekaan noise yang Takeda tolak — sehingga kedua bagian
permintaan itu **satu pekerjaan, bukan dua**.

**Preseden yang sudah ada di repo dan harus dipakai ulang:** detektor tepuk di
`config.yaml` sudah punya `noise_alpha: 0.05` (EMA noise floor adaptif),
`calibration_seconds: 1.5`, `crest_factor`, dan `spectral_ratio` untuk menolak
bunyi non-suara. Pola yang benar sudah terbukti di repo ini — hanya belum
dipasang di barge-in.

---

### S-5 — "Batas iterasi tercapai" (dan pesannya sendiri berbohong)

Gejala Takeda: `ERR: Agent native gagal: Batas iterasi tercapai sebelum tugas
tuntas. Progres tersimpan di sesi.`

Sumber: [loop.py:279-286](jarvis/agent/loop.py#L279-L286), klausa `else` dari
`for` — dijalankan hanya bila loop habis tanpa `break`.

**Batasnya jauh lebih ketat dari yang tertulis di Settings.**
[dispatch.py:369-371](jarvis/agent/dispatch.py#L369-L371) memaksa
`max_iterations=agent.interactive_max_iterations` = **12**, sementara
`agent.max_iterations` = 20 (nilai yang ditampilkan panel Settings sebagai
"Iterasi maks / tugas"). Semua tugas dari suara dan UI kena batas 12, dan
Takeda tidak punya cara mengubahnya dari Settings.

**Pesannya memuat klaim palsu kedua.** "Progres tersimpan di sesi"
mengisyaratkan ada cara melanjutkan. Tidak ada. Satu-satunya `resume` di
seluruh `jarvis/agent/` adalah `approval_continuations.resume()` untuk
persetujuan policy — bukan untuk loop yang kehabisan iterasi. Sesi memang
tersimpan, tetapi tidak ada jalur yang bisa memakainya kembali. Jadi cacat
kejujuran S-1 muncul lagi di sini, kali ini ditulis oleh kode kita sendiri,
bukan oleh model.

**Kenapa 12 iterasi habis.** Tiap giliran konfirmasi yang gagal atau timeout
(S-2) memakai satu iterasi, dan model mengulang. Alur panggilan WhatsApp yang
wajar sudah memakai `whatsapp_open` → `whatsapp_status` →
`whatsapp_list_contacts` → `whatsapp_call` → verifikasi = 5 iterasi sebelum
satu pun kesalahan terjadi.

Bukti pembanding dari audit ini: tugas normal selesai dalam **1-2 iterasi**.
Jadi batas 12 tidak salah untuk pekerjaan sehat — yang salah adalah tidak ada
eskalasi ketika batas tercapai, dan tidak ada partial result.

---

### S-6 — Kedua lane LLM sekarang melintasi jaringan tanpa enkripsi (KRITIS, naik dari T1)

T1 pada siklus lalu menyorot `http://` polos ke endpoint custom untuk lane
berat. **Sekarang lebih luas:**

```
routing.light.provider : custom     ← BARU (sebelumnya gemini)
routing.heavy.provider : custom
custom.base_url        : http://43.167.18.81:20128/v1
custom.api_key         : tersimpan plaintext di config/providers.json
```

Percakapan biasa, klasifikasi, kompresi konteks, seluruh schema tool, isi file
yang dibaca agent, dan hasil recall memori — semuanya kini melintas **cleartext
ke satu IP pihak ketiga**. Siklus lalu setidaknya lane percakapan masih di
Gemini over TLS. Cakupan paparan bertambah, bukan berkurang.

Ini keputusan Takeda, bukan bug — tetapi ruang lingkupnya berubah dan harus
dicatat ulang secara eksplisit.

---

### S-7 — Suite merah: test terikat pada nilai config milik user

```
FAILED tests/test_phase3_model_routing.py::test_config_yaml_routing_section_exists
AssertionError: assert 'custom' == 'gemini'
```

Test menuntut `config.get("routing.light.provider") == "gemini"`. Takeda
mengganti provider lane ringan ke `custom` — perubahan config yang sah dan
disengaja. Test ini menegaskan **nilai pilihan user**, bukan invarian struktur.
Yang seharusnya dikunci: section `routing` ada, punya kunci `light`/`heavy`,
dan nilainya menunjuk provider yang terdaftar.

---

### S-19 — Label bukti panggilan memakai kata yang salah — SELESAI ✅

**Bukti DOM saat panggilan Takeda BENAR-BENAR berdering** (probe linimasa
2026-08-05, detik ke-16 dan ke-17):

```
"Akhiri telepon"                              <- tombol putus
"Kontrol telepon"                             <- kontrol panggilan
"Pindahkan ke jendela baru"
"Izinkan akses kamera untuk beralih ke video"
pages = 1                                     <- overlay di halaman yang SAMA
```

`_HANGUP_SELECTORS` mencari `"akhiri panggilan"`, `"end call"`,
`data-icon="call-end"`. **WhatsApp Indonesia konsisten memakai "telepon",
bukan "panggilan".** Tidak satu pun cocok. Tiga akibat sekaligus:

* `_prove_call_started` selalu gagal — panggilan yang benar-benar berdering
  dilaporkan tidak terbukti;
* `_status_on_page` tidak pernah melaporkan `in_call`;
* **`whatsapp_hangup` tidak pernah menemukan tombolnya** — Jarvis tidak bisa
  menutup panggilan yang ia mulai sendiri.

Yang terakhir belum pernah terlihat karena panggilannya memang tidak pernah
dimulai (S-18). Ia akan muncul sebagai bug berikutnya begitu S-18 diperbaiki.

Hipotesis "overlay di jendela terpisah" **salah** — `pages=1`. Bagus sudah
dicek: probe kini memindai semua halaman context, jadi kalau kelak WhatsApp
memindahkannya (tombol "Pindahkan ke jendela baru" ada), kita akan tahu.

Yang dijaga: `test_call_proof_selectors_do_not_match_an_idle_chat` memastikan
label yang selalu ada ("Telepon", "Telepon suara") **tidak** dianggap bukti.
Bukti yang selalu benar bukan bukti — itu kegagalan arah sebaliknya dari S-1.

---

### S-18 — "Telepon" adalah pembuka menu, bukan tombol panggil — SELESAI ✅

Takeda menelepon lewat Jarvis; gagal dengan *"whatsapp_call tidak menghasilkan
keadaan panggilan yang terbukti"*. Satu fakta darinya memutus diagnosis:
**"hp honbrew tidak berdering"**. Berarti bukan sekadar bukti yang meleset —
panggilannya memang tidak pernah dimulai.

Probe saat tombol itu diklik:

```
{"aria_label": "Telepon"}        <- PEMBUKA MENU
{"aria_label": "Telepon video"}
{"aria_label": "Telepon suara"}  <- aksi panggilan suara
```

**Perbaikan S-16 justru menutupi ini.** Ia mencocokkan `"Telepon"` persis dan
melaporkan `call_button: COCOK`, sehingga alur yang masih putus tampak beres.
Jarvis mengklik pembuka menu lalu menunggu bukti yang tak akan pernah datang.

Alur benar sekarang: coba aksi suara langsung → bila tidak ada, buka menu →
cari `"Telepon suara"` → klik → baru buktikan. Bila menu terbuka tetapi
pilihan suara tidak ada, **berhenti dan melapor gagal** — menebak elemen lain
berisiko memulai panggilan VIDEO tanpa diminta.

---

### S-17 — Profil Chrome tertinggal mengunci WhatsApp Web — TERBUKA

Probe selesai normal, tetapi jendela Chrome-nya **tetap hidup**. `atexit` di
`whatsapp_web` memanggil `stop()`, jadi seharusnya tertutup — artinya
`launch_persistent_context(channel="chrome")` melahirkan Chrome yang lepas dari
kendali Playwright.

Akibat nyata di luar sesi debugging ini: **JARVIS tidak bisa memulai WhatsApp
Web bila ada sisa instance profil yang sama**, dengan pesan yang sama sekali
tidak menyebut profil terkunci:

```
BrowserType.launch_persistent_context: Opening in existing browser session.
This usually means that the profile is already in use by another instance.
```

Jadi satu crash atau penutupan paksa membuat panggilan berikutnya gagal dengan
sebab yang menyesatkan. **Belum diperbaiki.** Perbaikan yang tepat: deteksi
lock profil sebelum launch dan laporkan sebabnya secara spesifik, atau bersihkan
sisa proses profil sendiri sebelum mencoba.

---

### S-16 — Selector tombol panggilan meleset dari DOM sungguhan — SELESAI ✅

**Bukti DOM pertama yang benar-benar `live-proven`**, bukan fixture. Probe
read-only (`scripts/whatsapp_selector_probe.py`) terhadap profil Chrome Jarvis
yang login, chat honbrew terbuka, state `ready`. Satu-satunya tombol panggilan
yang ada:

```json
{"aria_label": "Telepon", "data_icon": "", "title": "", "tag": "button"}
```

`_CALL_SELECTORS` lama hanya mencari `"voice call"` dan `"panggilan suara"`.
**Tidak ada yang cocok.** Artinya `start_call` selalu gagal di "Tombol
panggilan suara tidak ditemukan" — panggilan tidak pernah benar-benar dimulai,
dan itu berlaku SEBELUM maupun SESUDAH Fase 13.

Ini melengkapi gambaran keluhan awal Takeda: toolnya gagal, lalu model
menarasikan sukses. Fase 14 kini menutup narasi palsunya; S-16 menutup
sebab teknisnya.

Diperbaiki dengan cocok **persis**, bukan substring — "Telepon" muncul juga di
dalam label lain, dan substring "panggilan" akan ikut menangkap tombol
panggilan VIDEO. Diverifikasi ulang lewat probe: `call_button: COCOK`.

**KOREKSI (2026-08-05, beberapa jam kemudian).** Kesimpulan di atas
**terlalu percaya diri**. Probe memang menemukan `aria-label="Telepon"` di DOM
asli, tetapi aku menyimpulkan itu tombol panggil — padahal ia PEMBUKA MENU
(lihat S-18). `call_button: COCOK` yang kulaporkan justru menutupi alur yang
masih putus. Yang membuktikannya bukan probe, melainkan satu kalimat Takeda:
*"hp honbrew tidak berdering"*.

Pelajarannya: label `live-proven` menuntut bukti bahwa **hasil yang diinginkan
terjadi**, bukan sekadar bahwa selector cocok dengan sesuatu di halaman.

**Yang saat itu belum tervalidasi:** `_HANGUP_SELECTORS`, `_ANSWER_SELECTORS`,
dan `_RINGING_SELECTORS`. Ketiganya hanya muncul saat panggilan berlangsung,
jadi butuh satu panggilan sungguhan. Konsekuensinya jujur dan sudah dirancang:
bila meleset, Fase 13 melaporkan keadaan **TIDAK DIKETAHUI** dan menyuruh
Takeda memeriksa jendelanya — bukan mengaku berhasil, bukan pula mengaku
gagal. Jalankan `python scripts/whatsapp_selector_probe.py --during-call`
saat panggilan aktif untuk menutupnya.

---

### S-15 — Laporan ucapan terpotong di tengah kata — SELESAI ✅

`test_typed_t2_speaks_ack_then_concrete_report` gagal satu kali dalam enam run
suite penuh. Teks yang diucapkan terpotong pada 44 karakter:

```
'Video "Deddy Corbuzier Episode 123" sudah dip'
```

Potongan **di tengah kata** — jadi ini truncation karakter, bukan batas kalimat
atau timing. `speech_limit()` seharusnya 900 dengan lantai 120
([interaction.py:30](jarvis/agent/interaction.py#L30)), sehingga 44 tidak
mungkin datang dari config yang sah.

Lima run berkas itu sendirian: bersih. Pasangan dengan
`test_phase3_model_routing` (yang memanggil `config.reload()`) dan dengan
`test_phase3_conversation_delivery`: bersih. Pencemarnya belum ditemukan.

#### Penyebabnya — ditemukan 2026-08-05

Petunjuk pertama: potongan itu **tidak berakhiran elipsis**. `sanitize_for_speech`
selalu menambahkan `…` saat memangkas, jadi bukan dia pelakunya.

Petunjuk kedua: test itu memakai delivery lifecycle dengan `naturalize=True`,
sementara `auxiliary.response_composer.enabled` bernilai **true** di config
repo dan test-nya **tidak menstub komposer**. Artinya test unit itu benar-benar
menembak provider LLM di tengah suite, dengan `max_tokens: 120`.

Generasi yang menabrak token cap berhenti di mana saja — kerap di tengah kata.
`_validated_speech` memeriksa panjang, anchor wajib, dan anchor terlarang,
tetapi **tidak pernah memeriksa apakah kalimatnya utuh**. Dibuktikan
deterministik, bukan dengan menunggu flake kambuh:

```
deterministik      : 'Video "Deddy Corbuzier Episode 123" sudah diputar, sir.'
anchors wajib      : ('Deddy Corbuzier Episode 123', '123')
kandidat terpotong DITERIMA? True -> 'Video "Deddy Corbuzier Episode 123" sudah dip'
```

Jadi ini **bug produksi, bukan flake tes**: setiap kali komposer menabrak token
cap, Jarvis mengucapkan setengah kalimat sebagai laporan.

#### Perbaikan

* `_looks_truncated()` menolak kandidat yang tidak berakhir tanda baca kalimat.
  Prompt komposer sendiri meminta "one or two natural sentences", jadi syarat
  itu wajar — dan menolak selalu aman karena teks deterministik yang sudah
  terverifikasi tetap dipakai. Komposer memang opsional; itulah gunanya.
* `test_typed_t2_speaks_ack_then_concrete_report` kini menstub komposer. Test
  unit tidak boleh memanggil LLM sungguhan.

**Diverifikasi dengan memblokir socket keluar**: `2227 lulus` dengan seluruh
koneksi non-lokal dilempar `OSError`. Suite tidak lagi bergantung pada
provider mana pun.

`auxiliary.response_composer.max_tokens: 120` sengaja **tidak** dinaikkan.
Menaikkannya hanya menggeser frekuensi; yang diperbaiki adalah penerimaan
hasil yang cacat.

---

### S-14 — Thread sweeper bocor — penyebab S-13 — SELESAI ✅

`SetupQueue.__init__` menjalankan thread sweeper **saat konstruksi**. Suite
membangun **21** queue dan hanya menutup 3, sehingga ~18 thread hidup sampai
proses berakhir, masing-masing bangun tiap ≤0,5 detik.

Ditemukan dengan menangkap traceback crash-nya, bukan dengan menebak:

```
Windows fatal exception: access violation
Thread 0x00008c74 ... jarvisgent
emote_setup.py", line 159 in _sweep_loop
Thread 0x00006d00 ... jarvisgent
emote_setup.py", line 159 in _sweep_loop
Thread 0x00000bc4 ... jarvisgent
emote_setup.py", line 159 in _sweep_loop
   … belasan lagi, semuanya sama
```

Diperbaiki: sweeper lahir pada `stage()` pertama dan **berhenti sendiri saat
antrean kosong**; `stage()` berikutnya menyalakannya lagi. Queue yang tidak
pernah dipakai kini berbiaya nol thread — dan itulah persis setiap test yang
membocorkannya. Kedaluwarsa otonom tetap berjalan, dikunci test lama yang tidak
berubah.

Setelah perbaikan: **6 run suite penuh berturut-turut, nol crash**.

Ini juga kandidat kuat penyebab kegagalan timing acak (kelas T8): belasan
thread yang bangun terus-menerus membuat scheduler Windows melewatkan tenggat
yang longgar sekalipun.

---

### S-13 — Crash native intermiten di suite penuh — SELESAI ✅ (lihat S-14)

Dua kali dalam belasan run suite penuh selama Fase 14:

```
Windows fatal exception: access violation
```

dan satu kali satu test gagal tanpa pola. **Delapan run berturut-turut
sesudahnya bersih**, jadi tidak bisa direproduksi sesuai permintaan.

Access violation adalah crash tingkat C, bukan Python; seluruh perubahan Fase
13-14 murni Python (kontrak, session, registry, selector). Kandidat penyebab
ada di pustaka native yang dipakai suite: Playwright/Chromium, sounddevice,
torch/onnx, mediapipe — kemungkinan besar pada shutdown interpreter dengan
thread native masih hidup.

**Terjawab saat Fase 16.** Dugaan awal (pustaka native: Playwright, sounddevice,
torch) **salah**. Menangkap traceback lengkapnya menunjukkan belasan thread
Python yang bocor dari `SetupQueue` — bukan pustaka native sama sekali. Lihat
**S-14**.

Pelajarannya: menebak penyebab dari "ini crash tingkat C, jadi pasti pustaka
native" akan menyesatkan penyelidikan sepenuhnya. Yang menyelesaikannya adalah
menjalankan suite berulang sampai crash tertangkap beserta jejaknya.

---

### S-12 — Seam bukti kontrak tidak pernah menerima hasil tool

Ditemukan saat hendak membangun Fase 14 **di atas** seam itu.

`dispatch._observe_session` mengumpulkan bukti dengan membungkus
`session.record_tool`. Satu-satunya pemanggil produksi metode itu adalah
[registry.py:218](jarvis/agent/registry.py#L218), yang sengaja menyerahkan
ToolResult **yang sudah diredaksi**:

```python
session_result = ToolResult(ok=res.ok, content=None, display=None,
                            error=safe_error, meta={})
```

Dibuktikan dengan menjalankan tool sungguhan lewat `registry.execute`:

```
tool ok= True | content type= str
EVIDENCE yang sampai ke validator kontrak:
  result.content = None
  result.display = None
  result.meta    = {}
```

Akibatnya `validate_youtube_latest_play` membaca `_result_mapping(...)` yang
selalu `{}` — sehingga **kontrak YouTube tidak pernah bisa lolos di produksi**.
Setiap permintaan "putar video terbaru dari X" dijamin berakhir "Verifikasi
alur YouTube gagal", seberapa benar pun pekerjaan agent.

Test yang ada hijau karena memanggil `session.record_tool(...)` langsung dengan
ToolResult utuh, **melewati** `registry.execute`. Yang terbukti hijau adalah
validatornya, bukan kabel yang menyuplainya — kelas bug yang sama dengan
"tes lolos, produksi rusak".

Diperbaiki dengan kanal terpisah `Session.record_evidence`: `record_tool` tetap
menerima hasil teredaksi untuk transkrip dan telemetry (redaksi itu benar dan
harus tetap), sedangkan bukti kontrak menerima hasil utuh, hidup di memori satu
run saja, tidak pernah ditulis ke disk atau log.

**Gerbang yang tidak pernah bisa dilewati tidak memverifikasi apa pun — ia
hanya memblokir.** Karena itu Fase 14 mengunci kedua arah: kontrak harus bisa
MENOLAK karangan, dan harus bisa MELOLOSKAN pekerjaan yang benar.

---

### S-11 — 3,45% call summary dibuang diam-diam sebagai "rahasia"

Ditemukan mengejar `test_integration_ring` yang gagal acak dengan `assert 0 == 1`
— tampak seperti flake test, ternyata bug produksi.

`CallSession` memberi `uuid.uuid4().hex` (32 karakter heks). Filter rahasia di
[call_memory.py:50](jarvis/core/call_memory.py#L50) menolak teks apa pun yang
memuat 12-19 digit berurutan — heuristik nomor kartu. Terukur:

```
uuid4().hex dengan 12+ digit berurutan: 6906 / 200000 = 3,453%
contoh: 4f4f8790482849258072e99f9f28767f  -> ditolak
```

Jadi ~1 dari 29 call summary yang sah **hilang tanpa pesan apa pun** —
`record()` mengembalikan `False` dan tidak ada yang membacanya.

Diperbaiki sempit: hex 32-karakter kanonik dikecualikan dari heuristik **digit
saja**. Penanda kata rahasia tetap berlaku untuk semua field, dan bentuk lain
seperti `4111111111111111` tetap ditolak persis seperti sebelumnya — test
lama yang mengunci penolakan itu tetap hijau.

**Pelajarannya sama dengan S-10:** kegagalan yang tampak seperti keributan tes
adalah satu-satunya alasan bug ini terlihat. Kalau ring test dilonggarkan agar
"tidak rewel", kerusakan produksinya tetap ada dan tak terlihat.

---

### S-10 — `embed()` mengembalikan vektor lebih sedikit daripada teks

Ditemukan **saat menjalankan backfill 13.0 pada DB nyata**, bukan dari
pembacaan kode. Jalur gemini di
[llm_client.py:203-234](jarvis/agent/llm_client.py#L203-L234) meneruskan apa pun
yang diberikan SDK apa adanya. Dengan google-genai 2.14.0 +
`gemini-embedding-2`, **16 teks masukan menghasilkan 1 embedding**:

```
len(batch)= 16   len(vecs)= 1   dims=[768]
```

Bahayanya bukan hasil yang kurang. Pemanggil menyandingkan vektor dengan teks
**berdasarkan posisi** — vektor yang lebih sedikit berarti satu memori mendapat
vektor milik memori lain, dan pencarian semantik salah tanpa satu pun error.
Tidak pernah terlihat karena `write()`/`update()` selalu mengirim tepat satu
teks; backfill adalah pemanggil batch pertama.

Guard paritas di backfill-lah yang menangkapnya — kalau backfill ditulis
percaya pada provider, 157 memori akan dapat vektor yang salah dan kerusakannya
tak terlihat.

---

### S-9 — Embedding mati selama lane ringan menunjuk `custom`

157 dari 212 memori tersimpan **tanpa vektor** (`semantic 73 · procedural 46 ·
reflective 38`) karena endpoint `custom` tidak melayani embedding. Lane ringan
sudah dikembalikan ke `gemini` dan embedding terbukti hidup lagi (`dim=768`),
tetapi baris lama tidak ikut pulih — tidak ada jalur backfill di repo.
Rincian dan pekerjaannya: **Fase 13.0**.

---

### S-8 — Catatan sehat (tidak perlu diperbaiki)

* 99 tool, 0 gagal import, 0 schema rusak, 0 tanpa capability descriptor.
* 9 tool `desktop_safe` sengaja tidak masuk schema tanpa execution context —
  perilaku benar sesuai `registry.schemas()`.
* `delegate_task` bekerja, dan penjagaannya benar: sub-agent tidak bisa
  delegate lagi maupun `task_start` ([loop.py:167](jarvis/agent/loop.py#L167)),
  batas iterasi sub-agent di-clamp ke 30, ringkasan dipangkas 6000 karakter.
* Failover provider berat berantai sudah terpasang dan tidak menelan error.

---

## Fase perbaikan Siklus 2

Urutan dipilih berdasar **bahaya lebih dulu, lalu frekuensi pemakaian**.
Kejujuran (S-1) mendahului kenyamanan (S-2), karena melonggarkan konfirmasi
sebelum klaim bisa dipercaya berarti mempercepat eksekusi yang tidak bisa
diverifikasi.

| Fase | Judul | Menutup | Prasyarat | Status |
|---|---|---|---|---|
| 13 | Kejujuran hasil panggilan (+ 13.0 backfill vektor memori) | S-1, S-9, S-10, S-11 | — | ✅ **SELESAI** 2026-08-05 |
| 14 | Kontrak bukti untuk aksi eksternal | S-1, S-12 | 13 | ✅ **SELESAI** 2026-08-05 |
| 15 | Konfirmasi bisa dijawab dengan suara | S-2 | 13 | ✅ **SELESAI** 2026-08-05 |
| 16 | Eksekusi panggilan tanpa gerbang ganda | S-2 | 14, 15 | ✅ **SELESAI** 2026-08-05 |
| 17 | Batas iterasi: jujur, bisa diatur, bisa dilanjut | S-5 | 14 | ✅ **SELESAI** 2026-08-05 |
| 18 | Sumber pencarian terbuka di browser | S-3 | — | ✅ **SELESAI** 2026-08-05 |
| 19 | Barge-in adaptif tahan noise | S-4 | — | ✅ **SELESAI** 2026-08-05 |
| S-7 | Perbaikan test config | S-7 | — | ✅ hijau sendiri setelah lane ringan dikembalikan |
| S-6 | Keputusan TLS | S-6 | — | ✅ diputuskan: diterima apa adanya |

---

### Fase 13 — Kejujuran hasil panggilan

**Menutup:** S-1 lapis 1 dan 3, plus S-9 (utang vektor memori).

#### 13.0 — pra-kerja: backfill vektor memori (S-9)

Tidak berhubungan dengan panggilan; ditempatkan di sini karena murah,
mendesak, dan tidak punya prasyarat. Dikerjakan lebih dulu supaya utangnya
berhenti bertambah.

**Temuan S-9.** Selama `routing.light.provider` menunjuk `custom`, embedding
mati total — endpoint OpenAI-compat itu tidak melayani `text-embedding-3-small`
yang diminta [llm_client.py:222-226](jarvis/agent/llm_client.py#L222-L226).
Dibuktikan: `light_client().embed([...])` → `None`, sedangkan gemini → `dim=768`.
Akibatnya di `memories`:

```
embedding ada  (3072 byte = 768 dim)  n=55
embedding NULL                        n=157
  semantic 73 · procedural 46 · reflective 38
```

Memori tanpa vektor tidak terjangkau pencarian semantik. Yang 38 `reflective`
adalah bahan blok "Pelajaran dari Kesalahan Sebelumnya" di system prompt —
Jarvis tidak bisa memanggil ulang pelajarannya sendiri.

`routing.light.provider` sudah dikembalikan ke `gemini` (2026-08-05, terverifikasi
`embed: dim=768`), jadi memori **baru** aman. Yang 157 tetap kosong: **tidak ada
jalur backfill mana pun di `jarvis/`**.

Pekerjaan:

* Fungsi backfill di `memory_store`: ambil baris `embedding IS NULL`, embed per
  batch lewat `_embed()` yang sudah ada, tulis balik. Jangan buat jalur embedding
  kedua — dimensi vektor harus tetap satu sumber.
* Idempoten dan aman diputus: kegagalan satu batch tidak boleh membatalkan batch
  yang sudah berhasil, dan menjalankan ulang tidak menghitung ulang yang sudah
  terisi.
* Hormati `_embed_unavailable_until` (cooldown 900 detik). Bila provider ringan
  tidak bisa embed, backfill **berhenti dan melapor** — bukan menulis vektor
  kosong atau berpura-pura selesai. Cacat kejujuran yang sama seperti S-1 tidak
  boleh masuk lewat pintu ini.

**Test:** DB berisi campuran baris NULL dan berisi → backfill mengisi **hanya**
yang NULL, jumlahnya benar, dan pemanggilan kedua melakukan nol embed. Provider
yang mengembalikan `None` → backfill melapor gagal dan **tidak** mengubah baris
mana pun.

##### Hasil 13.0 — SELESAI 2026-08-05

`memory_store.backfill_embeddings(batch_size, limit)` terpasang; 4 test di
`tests/test_memory_embedding_backfill.py`, **dibuktikan merah lebih dulu**
(`AttributeError: module ... has no attribute 'backfill_embeddings'`).

Jalankan pada DB nyata — percobaan pertama **GAGAL**, dan itu bagus:

```
{"pending": 157, "embedded": 0, "failed": true,
 "reason": "provider lane ringan tidak mengembalikan embedding"}
```

Guard paritas menolak menulis. Penyelidikan menemukan **S-10**: SDK gemini
mengembalikan 1 vektor untuk 16 teks. Diperbaiki di `llm_client.embed`
(pemeriksaan paritas + fallback per-teks + `None` bila tetap gagal), dikunci 6
test di `tests/test_embed_batch_parity.py`, juga dibuktikan merah lebih dulu.

Backfill diulang setelah backup `data/agent.sqlite.bak-fase13`:

```
{"pending": 0, "embedded": 157, "failed": false}   79.9 s
dim distribution: [(3072, 212)]      null: 0
```

212 memori, seluruhnya 768-dim seragam. Pencarian semantik menjangkau kembali
38 memori `reflective` yang dipakai blok "Pelajaran dari Kesalahan Sebelumnya".

**Kalau backfill ditulis percaya pada provider, 157 memori akan menerima vektor
yang salah dan kerusakannya tidak akan terlihat.** Guard yang terasa berlebihan
saat ditulis adalah satu-satunya alasan S-10 ketahuan.

#### 13.1 — pembuktian panggilan

1. `WhatsAppWebService.start_call` wajib **membuktikan keadaan setelah klik**:
   polling `_HANGUP_SELECTORS` / indikator ringing sampai batas waktu yang
   dapat dikonfigurasi (`whatsapp_web.call_confirm_timeout_s`, usul 8 detik).
   Kembalikan `{"state": "ringing"|"in_call"}` hanya bila terbukti; bila tidak,
   **lempar `WhatsAppError`** dengan sebab konkret.
2. `answer_call` mendapat pembuktian setara.
3. `WhatsAppCall.run` tidak lagi merangkai display sukses dari hasil klik.
   Ketika bridge audio gagal, itu **bukan** sukses parsial — nyatakan apa yang
   berhasil dan apa yang tidak, terpisah.
4. Tambahkan ke [prompts/system.md](jarvis/agent/prompts/system.md) aturan
   sekelas yang sudah ada di lane suara: dilarang menyatakan aksi eksternal
   berhasil sebelum hasil tool menyatakannya; bila tool gagal atau konfirmasi
   ditolak, laporkan apa adanya.

**Test yang harus merah dulu:** `start_call` pada halaman tiruan yang tombolnya
diklik tetapi tidak pernah memunculkan indikator panggilan → tool **gagal**,
bukan sukses.

##### Hasil 13.1-13.4 — SELESAI 2026-08-05

`tests/test_whatsapp_call_proof.py` (7 test) dibuktikan merah lebih dulu — 4
gagal karena `start_call` mengembalikan sukses tanpa bukti, 1 karena prompt
tidak memuat larangan, 1 karena kalimat display menyatukan dua fakta.

Yang berubah:

* `_RINGING_SELECTORS` baru + `_prove_call_started()` di `whatsapp_web.py`.
  Setelah klik, halaman **dibaca ulang** sampai tombol akhiri panggilan atau
  indikator memanggil terlihat, dibatasi `whatsapp_web.call_confirm_timeout_s`
  (default 8 detik). Tidak terbukti → `WhatsAppError`, bukan status lunak.
  State `"calling"` yang lama — yang lahir dari klik semata — **tidak bisa
  terbit lagi**; penggantinya `"ringing"` / `"in_call"` beserta `proven: True`.
* `answer_call` mendapat pembuktian setara.
* `_call_display()` memisahkan dua fakta yang dulu disatukan satu klausa:
  keadaan panggilan, lalu apakah Jarvis bisa bicara di dalamnya. Bentuk lama
  ("Memanggil X; virtual audio tidak siap") bisa dibaca dua arah yang
  sama-sama keliru.
* `prompts/system.md` aturan 7b: aksi eksternal tidak boleh dinyatakan berhasil
  tanpa hasil tool yang membuktikannya; konfirmasi ditolak berarti aksi TIDAK
  terjadi.

**Koreksi setelah review sendiri.** Pesan gagal versi pertama berbunyi *"Tidak
ada panggilan yang sedang berjalan."* Itu klaim yang tidak bisa kita ketahui:
bukti gagal bisa berarti selector tidak cocok dengan DOM WhatsApp, bukan
panggilan tidak dimulai — dan memutusnya otomatis mustahil, karena tombol
akhiri panggilan dicari dengan selector yang baru saja terbukti tidak cocok.
Menukar klaim palsu dengan klaim palsu arah sebaliknya bukan perbaikan. Pesan
sekarang menyatakan keadaan **TIDAK DIKETAHUI** dan menyuruh user memeriksa
jendelanya. Dikunci `test_failure_message_claims_only_what_is_knowable`.

**Batas jujur — dua, dan keduanya nyata:**

1. Aturan prompt adalah lapisan terluar, bukan penegakan. Model masih bisa
   mengarangnya. Yang menutup celah itu **Fase 14** — validasi bukti di
   `dispatch`, bukan kepatuhan model.
2. **Selectornya belum pernah diuji terhadap WhatsApp Web sungguhan.**
   `_HANGUP_SELECTORS` sudah ada sebelumnya dan dipakai `_status_on_page`;
   `_RINGING_SELECTORS` baru dan disusun tanpa melihat DOM asli. Label bukti
   repo ini: `focused-tested`, **bukan** `live-proven` — "LIVE-PROVEN" pada
   CLK `987864e` adalah tone loopback, bukan DOM panggilan.
   Risikonya berbalik arah: bila overlay asli tidak cocok dalam 8 detik, setiap
   panggilan nyata dilaporkan tidak terbukti padahal mungkin berdering. Karena
   itu pesannya dibuat "TIDAK DIKETAHUI", bukan "gagal". Menutupnya butuh satu
   panggilan nyata dengan approval live Takeda.

---

### Fase 14 — Kontrak bukti untuk aksi eksternal

**Menutup:** S-1 lapis 2. **Prasyarat:** Fase 13.

Mesin kontrak sudah ada dan terbukti (`YouTubeLatestPlayContract`). Yang perlu:

1. Generalisasi `task_contracts.prepare_task` agar dapat mengembalikan lebih
   dari satu jenis kontrak — pisahkan deteksi dari implementasi YouTube.
2. `ExternalCallContract` baru: bila tugas terdeteksi permintaan panggilan
   (pakai `_WHATSAPP_ACTION_RE` yang sudah ada di
   [router.py:262-274](jarvis/agent/router.py#L262-L274) sebagai sumber tunggal
   pola), maka teks sukses **hanya boleh terbit** bila bukti memuat
   `whatsapp_call` `ok=True` dengan `state` terbukti.
3. `_verified_success` sekarang di-hardcode ke kalimat YouTube
   ([dispatch.py:187-194](jarvis/agent/dispatch.py#L187-L194)) — jadikan milik
   kontrak masing-masing.

**Test:** sesi yang **tidak pernah** memanggil `whatsapp_call` tetapi
mengembalikan teks "sudah saya telepon" harus **gagal** validasi kontrak.

##### Hasil Fase 14 — SELESAI 2026-08-05

Dibuktikan merah lebih dulu di dua berkas: `test_contract_evidence_seam.py`
(seam) dan `test_external_call_contract.py` (kontrak).

**Seam dulu, karena kontraknya akan dibangun di atasnya.** S-12 ditemukan
sebelum satu baris kontrak ditulis: bukti yang sampai ke validator selalu
kosong. Membangun `ExternalCallContract` di atas seam itu akan menghasilkan
gerbang yang hanya bisa menolak. `Session.record_evidence` dipisah dari
`record_tool`; redaksi audit tetap utuh.

Yang berubah:

* `ExternalCallContract` — sukses hanya terbit bila bukti memuat
  `whatsapp_call` dengan `ok=True` **dan** state terbukti (`ringing`/`in_call`)
  **dan** `proven is True`. State `calling` lama sengaja tidak diterima.
* `prepare_task` kini menjalankan daftar detektor, bukan satu kontrak
  hardcoded; kontrak yang lebih spesifik diperiksa lebih dulu.
* `success_text` dan `failure_label` menjadi milik masing-masing kontrak.
  Sebelumnya `dispatch._verified_success` menuliskan kalimat YouTube secara
  hardcoded — kontrak kedua apa pun akan mengumumkan "video sudah diputar"
  setelah menelepon seseorang.
* Pola niat tetap tinggal di `router.py`: `WHATSAPP_START_CALL_RE` (sebut
  WhatsApp) dan `BARE_START_CALL_RE` (bentuk telanjang, dengan target
  ditangkap).

**Positif palsu yang tertangkap sebelum masuk:** sweep frasa nyata menunjukkan
"panggil taksi online lewat aplikasi Grab" ikut terkena kontrak — toolnya
dipersempit ke WhatsApp saja, jadi tugas yang wajar dijamin gagal. Bentuk
telanjang kini hanya berkontrak bila targetnya benar-benar **kontak allowlist**
(lewat `resolve_contact`, sehingga salah dengar STT seperti "honbru" tetap
tertangani). Menyebut "whatsapp" eksplisit tetap berkontrak apa pun namanya.

Sweep akhir:

```
ExternalCallContract      | telepon Honbrew
ExternalCallContract      | telepon honbru          (STT, fuzzy)
ExternalCallContract      | telepon Budi lewat whatsapp
-                         | panggil taksi online lewat aplikasi Grab
-                         | telepon customer service bank
-                         | kirim pesan whatsapp ke Honbrew
-                         | akhiri panggilan whatsapp
YouTubeLatestPlayContract | putar video terbaru dari Deddy Corbuzier
```

Sekarang klaim "sudah saya telepon" tanpa hasil tool **tidak bisa terbit**:
ia dihentikan oleh kode di `dispatch`, bukan oleh kepatuhan model. Batas jujur
Fase 13 nomor 1 tertutup; nomor 2 (selector belum diuji terhadap WhatsApp Web
nyata) **masih terbuka** dan tetap butuh satu panggilan sungguhan.

---

### Fase 15 — Konfirmasi bisa dijawab dengan suara

**Menutup:** S-2 (akar). **Prasyarat:** Fase 13.

1. Saat `ask_active()` benar, transkrip suara berisi kata setuju/tolak yang
   tegas (`ya`, `lanjut`, `setuju`, `benar` / `tidak`, `batal`, `jangan`)
   diterbitkan ke BUS `confirm`/`cancel` — jalur yang sama persis dengan
   ketikan. Kanal baru, gerbang lama.
2. Daftar kata disimpan di config, bukan di kode, agar bisa disetel tanpa
   menyentuh berkas frozen.
3. Hanya berlaku selama jendela `ask_active()`. Di luar itu, "ya" tetap
   percakapan biasa — jangan sampai kata setuju melayang menyetujui aksi yang
   belum ditanyakan.
4. Turunkan `agent.confirm_timeout_s` 300 → 45 detik untuk konfirmasi suara,
   dan **ucapkan pertanyaannya**, bukan hanya "Saya butuh konfirmasi Anda, sir"
   ([ui.py:127](jarvis/agent/adapters/ui.py#L127) sekarang membuang isi
   pertanyaan dari kanal suara — user mendengar bahwa ada pertanyaan tanpa
   mendengar pertanyaannya).

**Test:** "ya" di luar jendela ask **tidak** menerbitkan `confirm`; di dalam
jendela, menerbitkan tepat satu.

##### Hasil Fase 15 — SELESAI 2026-08-05

`tests/test_voice_confirmation.py` (37 test) dibuktikan merah lebih dulu.

Yang berubah:

* `jarvis/agent/voice_consent.py` — modul murni yang hanya memutuskan apakah
  SATU ucapan adalah jawaban tegas. Tidak menerbitkan apa pun, tidak menyentuh
  audio, tidak tahu tentang agent. Pemanggilnya yang memegang gerbang.
* `MainWindow._handle_spoken_confirmation` menerbitkan event BUS
  `confirm`/`cancel` — **event yang sama persis** dengan kata yang diketik.
  Kanal baru, gerbang lama.
* Dipasang di `_voice_intercept` **setelah** `reply_flow.handle_utterance`.
  ReplyFlow hanya melahap ucapan saat state-nya `CONFIRM`, jadi selama flow itu
  aktif "ya" tetap miliknya dan dua konteks konfirmasi tidak saling mencuri.
* `UIAdapter.ask` kini **mengucapkan pertanyaannya**. Bentuk lama mengucapkan
  "Saya butuh konfirmasi Anda, sir" dan membuang isi pertanyaan ke panel teks
  — mustahil dijawab tanpa melihat layar.
* `agent.confirm_timeout_s` 300 → **45**, dan daftar katanya pindah ke config
  (`agent.confirm.voice_yes` / `voice_no`, kosong = pakai bawaan).

**Asimetri yang disengaja.** Hanya ucapan yang SELURUHNYA berupa jawaban yang
dihitung; sapaan ("sir", "jarvis") dan pengisi ("tolong", "dong") boleh
menempel. Kalimat berkualifikasi jatuh ke `None`:

```
confirm | ya · iya sir · lanjut · oke · boleh · setuju · ya tolong · gas
 cancel | tidak · jangan · batal · stop · ga usah · nanti saja
   None | ya sudah jangan jadi · boleh tapi nanti · iya kalau perlu
   None | ok sekarang buka spotify · benarkah begitu
```

Melewatkan persetujuan berarti bertanya sekali lagi. Melewatkan penolakan
berarti tidak terjadi apa-apa. **Menyetujui aksi eksternal yang tidak pernah
disetujui adalah satu-satunya kesalahan yang tidak bisa ditarik kembali** —
jadi saat ragu, jawabannya `None`. Dikunci
`test_false_confirm_is_the_only_unsafe_direction`.

**Efek samping yang ditemukan:** satu test lama membangun fake parsial
`MainWindow` lewat `SimpleNamespace` dan pecah begitu metode baru dipanggil.
Fake-nya yang diperbaiki, bukan kodenya dilemahkan dengan `getattr` — pelemahan
itu justru akan menyembunyikan kabel yang benar-benar putus.

---

### Fase 16 — Eksekusi panggilan tanpa gerbang ganda

**Menutup:** S-2 (keinginan eksplisit Takeda). **Prasyarat:** Fase 14 dan 15.

Baru aman dikerjakan setelah klaim sukses terverifikasi (14) dan konfirmasi
bisa dijawab dengan suara (15).

1. Kunci config baru `whatsapp_web.call_confirmation` dengan tiga nilai:
   `always` (perilaku sekarang) · `allowlisted_only` (**usul default**:
   kontak yang sudah di-allowlist langsung dieksekusi; selain itu tetap
   bertanya) · `never`.
2. `WhatsAppCall.needs_confirmation(**kwargs)` — override dinamis yang sudah
   didukung `Tool` ([base.py:68](jarvis/agent/base.py#L68)) — membaca kunci itu
   dan meresolusi kontak. **Bukan** menghapus `requires_confirmation`.
3. Yang **tidak** dilonggarkan, dan alasannya:
   * `whatsapp_send_message` — isi pesan tidak dapat ditarik kembali dan tidak
     terikat allowlist sebagaimana identitas kontak.
   * `allow_direct_numbers` tetap `false`. Melonggarkan konfirmasi **dan**
     nomor bebas sekaligus berarti STT yang salah dengar bisa menelepon nomor
     acak.
4. Setiap panggilan tanpa konfirmasi wajib punya jejak: baris log level info
   dan baris terminal panel yang terlihat, plus tombol putus yang sudah ada
   (`whatsapp_hangup`, kill switch CLK) tetap satu klik.

**Test:** kontak allowlist → nol `adapter.ask`. Kontak di luar allowlist →
tetap ditanya. Mode `always` → perilaku lama utuh.

##### Hasil Fase 16 — SELESAI 2026-08-05

`tests/test_whatsapp_call_gate.py` (14 test) dibuktikan merah lebih dulu.

Permintaan Takeda dipenuhi: **kontak allowlist langsung ditelepon, tanpa
dialog**. Kontak itu sudah melewati satu gerbang manual ketika dimasukkan ke
`data/whatsapp_contacts.json`; bertanya lagi setiap kali adalah gerbang kedua
pada risiko yang sama.

Perilaku nyata terhadap allowlist sungguhan:

```
mode = allowlisted_only
  needs_confirmation('Honbrew')     = False
  needs_confirmation('honbru')      = False   ← salah dengar STT, resolver sama
  needs_confirmation('Ibu')         = True
  needs_confirmation('Orang Asing') = True
  needs_confirmation('')            = True
```

Yang dijaga:

* `requires_confirmation` **tidak dihapus** — mode `always` mengembalikan
  perilaku lama utuh, dan jalur mana pun yang tidak mengenal mode ini tetap
  bertanya.
* Nilai config tak dikenal (`"longgar"`, kosong, angka) **gagal tertutup** ke
  `always`. Salah ketik tidak boleh diam-diam menghapus konfirmasi.
* Gerbang memakai `resolve_contact` — **resolver yang sama** dengan yang
  mengeksekusi panggilan. Gerbang yang lebih ketat daripada eksekusi hanya akan
  bertanya untuk kontak yang toh tetap ditelepon.
* `whatsapp_send_message` **tidak dilonggarkan** pada mode apa pun: isi pesan
  tidak bisa ditarik kembali dan tidak terikat allowlist sebagaimana identitas
  kontak.
* `allow_direct_numbers` tetap `false`. Melonggarkan konfirmasi **dan** nomor
  bebas sekaligus berarti satu salah dengar STT bisa menelepon nomor acak.
* `whatsapp_answer` sengaja **di luar cakupan** — tetap bertanya sampai
  diputuskan terpisah. Dikunci test agar keputusannya eksplisit, bukan
  terlupakan.

**Jejak yang terlihat.** Menghapus dialog boleh; menghapus kesempatan Takeda
menyadari panggilan sedang berjalan tidak. Sebelum dial, tool mengumumkan
`📞 Menelepon <kontak> via WhatsApp (kontak allowlist — tanpa konfirmasi)`
ke panel lewat `adapter.progress`, plus log `whatsapp.call.auto_approved`.
Tombol putus (`whatsapp_hangup`) tetap satu langkah.

**Efek samping yang ditemukan:** `test_tools_require_confirmation_for_external_actions`
lulus hanya karena "Ibu" kebetulan tidak ada di allowlist nyata — lulus tanpa
menguji apa pun. Dibuat eksplisit: mode dipilih sengaja, dan ditambah test
kedua untuk perilaku default.

---

### Fase 17 — Batas iterasi: jujur, bisa diatur, bisa dilanjut

**Menutup:** S-5. **Prasyarat:** Fase 14.

1. **Hapus klaim palsunya lebih dulu** — pesan tidak boleh menjanjikan
   "progres tersimpan" selama tidak ada cara melanjutkan. Ganti dengan laporan
   konkret: berapa iterasi terpakai, langkah terakhir apa, apa yang sudah
   berhasil.
2. Kembalikan **hasil parsial**, bukan hanya kegagalan. Loop sudah memegang
   `session.record_turn` dan bukti tool — ringkas apa yang sudah tuntas.
3. Naikkan `agent.interactive_max_iterations` 12 → 20 agar setara
   `agent.max_iterations`, dan **tampilkan kunci yang benar di Settings** —
   sekarang panel menampilkan `agent.max_iterations` yang tidak dipakai jalur
   interaktif ([settings_service.py:315](jarvis/core/settings_service.py#L315)).
   Satu nilai yang bohong lebih buruk daripada dua nilai yang jujur.
4. Eskalasi di ambang batas: pada 80% iterasi, minta keputusan user
   (lanjutkan / hentikan / persempit) alih-alih menabrak dinding diam-diam.
5. Kurangi pemborosan iterasi di sumbernya: konfirmasi yang ditolak tidak boleh
   memicu percobaan ulang identik. Pesan gagal saat ini sudah berbunyi *"jangan
   ulangi tanpa diminta"* — tegakkan di kode, jangan menitipkannya pada
   kepatuhan model.

**Test:** loop yang menabrak batas mengembalikan ringkasan parsial dan **tidak**
memuat frasa "Progres tersimpan di sesi".

##### Hasil Fase 17 — SELESAI 2026-08-05

`tests/test_iteration_limit_honesty.py` (10 test) dibuktikan merah lebih dulu.

**1. Klaim palsu dibuang.** "Progres tersimpan di sesi" hilang. Penggantinya
fakta yang bisa diperiksa:

```
Batas 20 iterasi tercapai sebelum tugas tuntas (terpakai 20).
Yang sudah berjalan: web_search, web_extract. 1 pemanggilan tool gagal.
Tugas ini tidak dilanjutkan otomatis — minta lagi bila ingin saya teruskan.
```

Kalimat terakhir menyatakan batasnya secara terbuka alih-alih menyiratkan
kelanjutan yang tidak ada.

**2. Hasil parsial dikembalikan**, bukan hanya kegagalan. Jejak tool sudah
dipegang loop; membuangnya berarti membuang pekerjaan yang benar-benar
selesai. Saat belum ada yang berhasil, itu pun dinyatakan apa adanya.

**3. Angka Settings tidak lagi bohong.** `agent.interactive_max_iterations`
12 → **20**, setara `agent.max_iterations`, dan **kedua kunci kini muncul di
panel** dengan label berbeda — jalur suara/UI memakai kunci kedua, jadi
menampilkan hanya yang pertama berarti panel menunjukkan angka yang tidak
berlaku bagi perintah sehari-hari.

**4. Eskalasi sebelum menabrak dinding.** Pada 80% iterasi, peringatan progres
selalu terbit; pada run interaktif Jarvis menawarkan berhenti. **Tidak menjawab
bukan berarti berhenti** — pekerjaan lanjut sampai batas, karena memblokir
tugas gara-gara user sedang tidak di meja adalah kegagalan yang lebih buruk.
Run non-interaktif (cron, sub-agent) tidak pernah ditanya.

**5. Penolakan konfirmasi ditegakkan di kode.** Pesan lama sudah berbunyi
"jangan ulangi tanpa diminta", tetapi itu menitipkan jaminan pada kepatuhan
model — padahal tiap pengulangan memakan satu iterasi, dan begitulah 12 iterasi
habis tanpa satu pun pekerjaan nyata. `Session.denied_confirmations` kini
menyimpan permintaan yang ditolak, dan permintaan **identik** (tool + argumen)
langsung gagal tanpa bertanya lagi. Penolakan mengikat satu permintaan, bukan
seluruh tool selamanya: kontak berbeda tetap ditanyakan.

**Efek samping yang ditemukan di tes sendiri:** fixture autouse menambal
`registry.execute` untuk seluruh modul, sehingga dua test yang justru menguji
guardrail konfirmasi asli malah menguji tiruan — dan lulus tanpa arti. Referensi
aslinya ditangkap sebelum penambalan lalu dipulihkan di kedua test itu.

---

### Fase 18 — Sumber pencarian terbuka di browser

**Menutup:** S-3.

1. Perbaiki dulu cacat data: kartu mode `news` **harus** menyertakan URL sumber
   ([web.py:98-102](jarvis/agent/tools/web.py#L98-L102)). Tanpa ini, membuka
   browser pun tidak ada yang bisa dibuka.
2. Kunci config `agent.search.open_sources` (usul default: `on_request` —
   dibuka bila user menyebut "sumber", "buktikan", "tunjukkan"; `always` dan
   `never` tersedia).
3. Saat aktif, buka **panel browser agent** (`jarvis/browser/agent_view.py`,
   `browser_new_tab`) ke sumber peringkat teratas. Jangan browser sistem —
   panel agent sudah punya lifecycle, lease, dan pelepasan yang benar
   ([dispatch.py:206-217](jarvis/agent/dispatch.py#L206-L217)).
4. Balik instruksi lama yang bertentangan di
   [voice_native_tools.py:375](jarvis/integrations/voice_native_tools.py#L375)
   secara sadar, dan catat alasannya di komentar agar tidak "diperbaiki"
   kembali ke perilaku lama oleh siklus berikutnya.
5. Batasi: satu tab per pencarian, bukan satu tab per hasil.

**Test:** pencarian mode `news` menghasilkan kartu yang memuat URL; permintaan
"cari X, tunjukkan sumbernya" memicu tepat satu navigasi.

##### Hasil Fase 18 — SELESAI 2026-08-05

`tests/test_search_sources.py` (23 test) dibuktikan merah lebih dulu.

**Cacat data diperbaiki lebih dulu.** Kartu mode `news` membuang `href`
sepenuhnya — tanpa itu, membuka browser pun tidak ada yang bisa dibuka.

**Pembukaan sumber** lewat `agent.search.open_sources`:
`always` · `on_request` (**default**) · `never`, nilai tak dikenal jatuh ke
`on_request`. Yang dibuka adalah **panel browser agent** lewat
`registry.execute("browser_new_tab", …)` — bukan memanggil internal browser —
supaya lease, lifecycle, dan pelepasannya tetap ditangani jalur yang sudah ada
dan sudah teruji.

Batasan yang disengaja:

* **Satu tab per pencarian**, bukan satu per hasil. Enam tab tiap Takeda
  bertanya berarti merebut layarnya.
* Tanpa sesi (cron, sub-agent) → tidak membuka apa pun. Jendela tidak boleh
  muncul diam-diam dari pekerjaan latar.
* Kegagalan browser **tidak menggagalkan pencarian**. Menampilkan sumber itu
  bonus; hasil yang sudah benar tidak boleh hilang karenanya.

**Positif palsu yang tertangkap sebelum masuk.** Sweep frasa nyata menunjukkan
"apa sumber energi terbarukan" ikut memicu pembukaan tab — padahal "sumber" di
situ TOPIK, bukan permintaan. Kata telanjang `sumber`/`link`/`tautan` kini baru
dihitung permintaan bila berimbuhan pemilik ("sumbernya") atau didahului kata
kerja meminta ("sebutkan/tampilkan/sertakan/buka … sumber"):

```
False | cari harga gpu
False | apa sumber energi terbarukan
False | cari sumber protein nabati
False | cari link aja deh
False | jelaskan sumber daya alam indonesia
 True | cari harga gpu dan tunjukkan sumbernya
 True | buktikan dari mana beritanya
 True | cari data itu dan sertakan sumber
 True | cari beritanya lalu tampilkan link
 True | cari referensi soal transformer
```

**Aturan lama dicabut secara sadar.** `voice_native_tools` dulu berbunyi
*"jangan membuka browser hanya untuk pencarian"* — larangan yang bertentangan
langsung dengan permintaan Takeda. Diganti, dan alasan pencabutannya ditulis di
tempatnya agar siklus berikutnya tidak "memperbaikinya" kembali ke perilaku
lama. Dikunci `test_voice_rules_no_longer_forbid_opening_sources`.

---

### Fase 19 — Barge-in adaptif tahan noise

**Menutup:** S-4. Kedua bagian permintaan Takeda diselesaikan bersama — barge-in
tidak boleh dinyalakan sebelum tahan noise.

1. **Noise floor adaptif** menggantikan ambang tetap 0.14. Pakai pola yang
   sudah terbukti di detektor tepuk: kalibrasi awal + EMA (`noise_alpha`).
   Ambang menjadi *relatif* terhadap kebisingan ruangan saat itu.
2. **Pembeda suara vs bunyi.** Tepukan, pintu, dan dengung tidak boleh memotong
   Jarvis. Preseden `crest_factor` dan `spectral_ratio` sudah ada di
   `config.yaml` untuk tujuan sebaliknya (menerima transien) — di sini dipakai
   untuk menolaknya.
3. **Echo guard sepanjang ucapan, bukan hanya 400 ms pertama.** Cacat ini yang
   membuat barge-in dimatikan sejak awal. Perkirakan echo dari amplitudo TTS
   yang sedang diputar dan naikkan ambang secara proporsional selama itu.
4. Naikkan `min_ms` 280 → ~450 dan wajibkan blok berurutan di atas ambang,
   bukan sekadar durasi kumulatif.
5. Baru setelah 1-4 terpasang: `voice.barge_in.enabled` boleh `true` sebagai
   default, dan `tests/test_voice_barge_in.py` diperbarui — **beserta alasan
   tertulis** mengapa penguncian lamanya (echo kalibrasi) sudah terjawab.
6. Sediakan `voice.barge_in.sensitivity` (`low`/`medium`/`high`) sebagai satu
   kenop yang bisa Takeda putar tanpa menyentuh lima angka mentah.

**Test:** derau broadband pada level ruangan **tidak** memicu interupsi; nada
mirip-suara di atas noise floor **memicu** dalam < 600 ms.

##### Hasil Fase 19 — SELESAI 2026-08-05

`tests/test_barge_in_adaptive.py` + `tests/test_voice_barge_in.py` (30 test)
dibuktikan merah lebih dulu.

Keputusan interupsi pindah dari callback audio ke modul murni
`jarvis/core/barge_in.py` — bisa diuji tanpa perangkat audio sama sekali.

**Ambangnya dibalik dari preseden, dan itu intinya.** Detektor tepuk
(`wake.py`, FROZEN — dibaca, tidak disentuh) mencari transien: crest TINGGI,
broadband. Suara manusia justru sebaliknya: berkelanjutan, crest RENDAH, energi
terkonsentrasi di bawah 1 kHz. Primitif sama, keputusan berlawanan.

Empat pengaman:

1. **Noise floor adaptif** — kalibrasi 1,5 detik + EMA. Ambang = `noise_floor
   × pengali`, bukan angka mati 0.14. Ruangan berisik konsisten pada level
   0.18 (di atas ambang lama!) tidak memicu apa pun.
2. **Pembeda suara vs bunyi** — crest factor menolak pintu/tepukan, rasio pita
   suara menolak desis broadband.
3. **Echo guard sepanjang ucapan**, bukan hanya 400 ms pertama. Ini cacat yang
   membuat barge-in dimatikan sejak awal.
4. **Sustain berturut-turut** 450 ms; satu jeda mengembalikan hitungan ke nol.

Satu kenop: `voice.barge_in.sensitivity` = `low` | `medium` | `high`.

**Lubang yang kutemukan pada rancanganku sendiri.** Versi pertama memakai
worst-case: bila level playback tidak terukur, anggap volume penuh. Hasilnya
ambang melonjak ke 0.635 dan **tidak ada tingkat suara wajar yang bisa
memotong** — barge-in "menyala" tetapi mati dalam praktik, kegagalan yang sama
dengan wajah berbeda. Terlihat hanya karena aku menjalankan matriks perilaku
dengan config nyata, bukan karena ada test yang merah.

Diperbaiki dengan **mengukur, bukan mengasumsikan**:
`jarvis/integrations/voice_playback_level.py` menyadap potongan audio yang
benar-benar diputar lewat seam `_play_audio` yang sudah terbukti (dipakai
`whatsapp_voice`), dengan peluruhan 0,45 detik. Worst-case 1.0 kini hanya
dipakai bila tap belum terpasang — echo yang tak terukur tetap lebih berbahaya
daripada interupsi yang terlewat.

Matriks perilaku dengan config nyata:

```
level suara |  Jarvis diam  |  Jarvis bicara keras
      0.15  |  POTONG       |  diam
      0.25  |  POTONG       |  diam
      0.40  |  POTONG       |  diam
      0.70  |  POTONG       |  diam
```

**Batas jujur:** selama Jarvis bicara keras TANPA jeda, suara volume normal
tidak akan memotong — perlu lebih keras atau menunggu celah. Karena level
meluruh dalam 0,45 detik dan TTS punya jeda antar potongan, celah itu sering
ada dalam praktik. Diuji dengan sinyal sintetis; **belum diuji dengan suara
Takeda di ruangan Takeda**, dan `sensitivity` adalah kenop untuk itu.

---

### S-7 — perbaikan test config (kecil)

Ganti `assert config.get("routing.light.provider") == "gemini"` menjadi
pemeriksaan invarian: section `routing` ada, memuat `light` dan `heavy`, dan
tiap `provider` menunjuk nama provider yang terdaftar di `providers.list_names()`.
Nilai pilihan user tidak boleh membuat suite merah.

---

### S-6 — KEPUTUSAN DIAMBIL 2026-08-05: diterima apa adanya

Takeda memilih **membiarkan endpoint plaintext apa adanya**, dengan risiko
diketahui dan diterima. Dicatat sebagai keputusan sadar, bukan temuan terbuka —
audit berikutnya tidak perlu mengangkatnya lagi sebagai masalah.

Yang berlaku sekarang:

```
routing.light.provider : gemini    (TLS)  — dikembalikan 2026-08-05
routing.heavy.provider : custom    http://43.167.18.81:20128/v1
```

Cakupan paparan yang diterima: system prompt beserta memori yang di-recall,
90 schema tool, dan setiap hasil tool — isi file, keluaran terminal, snapshot
browser, nama kontak. Percakapan biasa, kompresi konteks, dan embedding TIDAK
lagi termasuk sejak lane ringan kembali ke gemini.

Peringatan runtime tetap menyala (`agent.llm.insecure_base_url` + panel
Settings); tidak dimatikan, supaya keputusan ini tetap terlihat dan bisa
ditinjau ulang kapan saja dengan mengganti satu baris `routing.heavy.provider`.

#### Catatan asli

Repo sudah memperingatkan (T1 siklus lalu: log + panel Settings). Yang berubah:
lane ringan **juga** melintasi endpoint plaintext sekarang, jadi paparannya
mencakup percakapan biasa. Pilihan yang tersedia: TLS di sisi endpoint,
terowongan (SSH/WireGuard), atau kembalikan `routing.light.provider` ke
provider ber-TLS. Tidak ada yang bisa diselesaikan dari dalam repo.

---

## Aturan yang berlaku untuk seluruh Siklus 2

Sama dengan siklus lalu, ditegaskan ulang karena temuan S-1 dan S-5:

1. **Test merah dulu.** Setiap fase menyebutkan test yang harus gagal sebelum
   perbaikan dan lulus sesudahnya. Test yang tidak pernah terbukti merah tidak
   membuktikan apa pun.
2. **Berkas FROZEN tidak disentuh.** `main.py` dan `ui.py` hanya dibungkus dari
   luar lewat seam `install()` yang sudah terbukti.
3. **Jangan menitipkan jaminan pada kepatuhan model.** Aturan prompt adalah
   lapisan terluar, bukan penegakan. Setiap fase yang bergantung pada model
   berperilaku benar wajib punya pemeriksaan di kode.
4. **Kejujuran mendahului kenyamanan.** Fase 16 (eksekusi langsung) tidak boleh
   didahulukan atas Fase 13-14 (bukti). Mempercepat aksi yang belum bisa
   diverifikasi adalah memperbesar S-1, bukan memperbaikinya.
5. `ruff check .` dan `verify_frozen.py` hijau di akhir setiap fase.

---

## Kondisi "selesai" untuk Siklus 2

- [ ] 157 memori tanpa vektor terisi ulang; pencarian semantik menjangkaunya lagi *(13.0)*
- [ ] Panggilan yang gagal dilaporkan **gagal** — klaim sukses mustahil tanpa bukti tool *(13, 14)*
- [x] "telepon Honbrew" lewat suara dieksekusi tanpa pindah ke keyboard *(15, 16)*
- [x] Konfirmasi yang tersisa bisa dijawab dengan suara *(15)*
- [x] Batas iterasi memberi hasil parsial dan tidak menjanjikan resume yang tidak ada *(17)*
- [x] Nilai iterasi di Settings adalah nilai yang benar-benar dipakai *(17)*
- [x] Pencarian menampilkan sumber — dan mode berita memuat URL sama sekali *(18)*
- [x] Jarvis bisa dipotong bicara secara natural *(19)*
- [x] Kebisingan ruangan tidak memotong Jarvis *(19)*
- [x] `pytest tests/ -q` hijau penuh kembali *(S-7 + seluruh fase)*
- [x] Keputusan TLS diambil *(S-6 — diterima apa adanya, 2026-08-05)*

---
---

# SIKLUS 3 — temuan lapangan (2026-08-05, sore)

**Pemicu:** Takeda memakai Jarvis sungguhan setelah Siklus 2 dan menemukan
empat hal yang tidak tersentuh audit sebelumnya. Semuanya ditemukan dengan
MEMAKAI, bukan membaca kode — dan tiga di antaranya tidak akan pernah terlihat
dari test.

**Status: SEMUA BELUM DIKERJAKAN.**

| Fase | Judul | Menutup | Status |
|---|---|---|---|
| 20 | `close_app` menyebut apa yang benar-benar ditutup | S-20 | ✅ **SELESAI** 2026-08-05 |
| 21 | Jarvis melihat & mengendalikan Chrome milik Takeda | S-21 | ✅ **SELESAI** 2026-08-05 |
| 22 | Interupsi suara terbukti hidup; test berhenti mencemari log | S-22 | ⚠ **SEBAGIAN** — log & diagnostik selesai; bukti hidup menunggu sesi nyata |
| 23 | Rekomendasi membuka SUMBERNYA, bukan transkrip | S-23 | ✅ **SELESAI** 2026-08-05 |

---

## S-20 — `close_app` menutup aplikasi yang salah, lalu mengulang kata user

Takeda: *"perintah untuk menutup browser, jarvis hanya memberikan klaim palsu
kalau dia sudah berhasil menutup browser."*

Diperiksa langsung terhadap proses yang benar-benar berjalan:

```
'browser'       -> 1 proses: Tabbit Browser.exe (pid 19844)
'chrome'        -> 2 proses: chrome.exe 2108, chrome.exe 36080
app_registry.resolve('browser') -> None
```

Kata "browser" **tidak menunjuk Chrome**. Pencocokan proses mendarat di
**Tabbit Browser** — aplikasi lain sama sekali.

Lalu pesannya, [close_app.py:219](actions/close_app.py#L219):

```python
f"{target.title()} ditutup."
```

`target` adalah **kata yang diucapkan user**, bukan yang benar-benar tertutup.
User bilang "browser" -> dijawab "Browser ditutup." Nama proses yang sungguh
ditutup ada di `closed=`, tetapi tidak pernah masuk kalimat.

**Melaporkan permintaan, bukan hasil.** Penyakit S-1 di tempat baru: kali ini
bukan model yang mengarang, melainkan kode kita sendiri yang menggemakan input.

---

## S-21 — Jarvis mengendalikan browser yang berbeda dari milik Takeda

Takeda: *"perintah untuk pause youtube tapi jarvis tidak mengetahui jika
browser ada banyak tab yang terbuka."*

Bukan bug — keputusan desain yang bertabrakan dengan harapan.
[browser.py:41-47](jarvis/agent/tools/browser.py#L41-L47), komentarnya sendiri:

> *"Direktori profil Chrome khusus JARVIS (**terisolasi dari profil user**) …
> tidak pernah bentrok profile-lock dengan Chrome user"*

`browser_media`, `browser_tabs`, `browser_navigate` bekerja pada Chrome milik
AGENT. YouTube Takeda ada di Chrome pribadinya (31 proses terpisah). Jadi
"pause youtube" tidak gagal — Jarvis memeriksa browsernya sendiri yang kosong,
dan jujur melaporkan tidak ada media.

Isolasi itu punya alasan sah (lock profil, tab user tidak dirusak agent).
Menghapusnya begitu saja akan mengembalikan masalah lama. Fase 21 harus
menambah AKSES ke Chrome user tanpa membuang isolasi yang ada.

---

## S-22 — Tidak ada bukti barge-in pernah berjalan untuk suara sungguhan

Takeda: *"voice interupt tidak berfungsi, saya tidak bisa menyela jarvis."*

Log sempat tampak menjanjikan — `barge_in.triggered` 52 kali. Hampir
disimpulkan "deteksi jalan, interupsinya yang gagal". Timestampnya:

```
00:49:20.416   00:49:20.444   00:49:20.468   00:49:20.580
```

Selisih **milidetik**. Itu bukan orang bicara — itu **pytest**. Suite menulis
ke log produksi yang sama.

Jadi: **nol bukti** barge-in pernah aktif untuk suara nyata, dan temuan kedua
yang lebih luas — **log produksi tercemar test**, sehingga diagnosis runtime
apa pun tidak bisa dipercaya sampai itu dipisah.

Pembeda yang belum dijawab: **apakah ESC menghentikan ucapan Jarvis?**
Ya -> jalur interupsi sehat, barge-in yang tidak memicu. Tidak -> masalahnya di
jalur interupsi, dan barge-in sepeka apa pun tidak akan menolong.

---

## S-23 — Rekomendasi membuka transkrip user, bukan sumbernya

Takeda: *"ketika jarvis memberi rekomendasi … memberikan opsi untuk menampilkan
informasi itu di chrome, baik sumber itu berupa web, social media atau map.
Bukan menampilkan apa yang saya ucapkan di chrome."*

Bukti fisik dari judul jendela Chrome miliknya:

```
'kan saya restoran yang - Search - Google Chrome'
```

Itu pencarian Google atas **potongan transkrip** ("…kan saya restoran yang…").
Mekanismenya [window.py:1112-1122](jarvis/ui/window.py#L1112-L1122):

```python
result = open_external_url(search_url(query))
```

`query` jatuh ke `c.slots.get("query", spoken)` — ucapan mentah — lalu dikirim
ke browser sistem sebagai URL pencarian. Tidak ada tawaran, tidak ada sumber.

Perhatikan bedanya dengan **Fase 18**: di sana sumber teratas dibuka di panel
browser AGENT setelah `web_search`. Jalur yang dipakai Takeda sama sekali lain
— intercept suara legacy -> `Intent.SEARCH_WEB` -> browser sistem. Fase 18
tidak menyentuhnya sama sekali.

---

## Fase 20 — `close_app` menyebut apa yang benar-benar ditutup

**Menutup:** S-20.

1. Pesan sukses menyebut **proses yang sungguh ditutup** (`closed`), bukan kata
   yang diminta. "Tabbit Browser ditutup" — bukan "Browser ditutup".
2. Kata ambigu yang tidak diresolusi `app_registry` ("browser") dan target yang
   cocok ke banyak proses -> **tanya**, jangan tebak. Jalur `STATUS_AMBIGUOUS`
   sudah ada; yang kurang adalah menempuhnya untuk kasus ini.
3. Kontrak bukti untuk aksi desktop, memakai mesin Fase 14: sukses hanya terbit
   bila bukti tool menunjukkan proses target benar-benar hilang.
4. "browser" dipetakan ke browser default user bila itu memang maksudnya —
   diputuskan bersama Fase 21.

**Test merah dulu:** menutup dengan nama ambigu -> bertanya, bukan menutup
aplikasi acak; pesan sukses memuat nama proses nyata.

### Hasil Fase 20 — SELESAI 2026-08-05

`tests/test_close_app_honesty.py` (12 test) dibuktikan merah lebih dulu.

**Cacat 1 — tebakan longgar diperlakukan sebagai kepastian.** `_names_the_app()`
baru: permintaan dianggap MENYEBUT aplikasi hanya bila `app_registry` memetakan
namanya, ATAU nama proses kandidat sama persis. Selain itu Jarvis menyebutkan
apa yang ia temukan lalu **bertanya** — tidak menutup milik user atas dasar
substring.

**Cacat 2 — pesan menggemakan permintaan.** `f"{target.title()} ditutup."`
diganti dengan nama yang benar-benar tertutup dari daftar `closed`. Bila
Jarvis menutup Tabbit Browser, ia mengatakan **Tabbit Browser**, bukan
"Browser".

Diverifikasi terhadap proses yang benar-benar berjalan di mesin Takeda:

```
'browser'        -> 1 cocok, menyebut-aplikasi=False  ['Tabbit Browser.exe']  BERTANYA
'tabbit browser' -> 1 cocok, menyebut-aplikasi=True                           tutup
'notepad'        -> 2 cocok (notepad++ & Notepad)                             BERTANYA
```

Kasus persis yang menghasilkan klaim palsu kini berhenti dan bertanya.

**Seam lama dipertahankan.** Versi pertama mengganti `_matches()` dengan
`_matches_scored()` dan memecahkan empat test di `test_process_guard.py` yang
menambal `_matches`. Diperbaiki dengan menjaga `_matches()` apa adanya dan
menaruh penilaian kualitas di fungsi terpisah — mengubah empat test yang sehat
demi kenyamanan refactor adalah arah yang salah.

**Yang TIDAK dikerjakan di fase ini** (butuh Fase 21): memetakan "browser" ke
browser default user. Sampai itu ada, "tutup browser" akan bertanya — jujur,
tetapi belum yang Takeda inginkan.

---

## Fase 21 — Jarvis melihat & mengendalikan Chrome milik Takeda

**Menutup:** S-21. **Fase terbesar di siklus ini.**

Isolasi profil agent **tidak dibuang** — ia menyelesaikan masalah nyata. Yang
ditambah: kemampuan meng-*attach* ke Chrome user.

1. Chrome user dijalankan dengan remote debugging port, atau Jarvis meluncurkan
   ulang dengan port itu **atas persetujuan** (menutup Chrome user adalah aksi
   yang harus diminta, bukan diambil).
2. Tool baru yang eksplisit menyasar browser user — daftar tab, media, dan
   navigasi — terpisah dari `browser_*` milik agent supaya tidak ada
   kebingungan target.
3. Prompt dan router harus tahu bedanya: "pause youtube" berarti browser USER;
   riset multi-langkah tetap di browser agent.
4. Batas jujur: bila port debug tidak tersedia, katakan **itu** — jangan
   melaporkan "tidak ada media".

**Test merah dulu:** perintah media saat browser user tak terjangkau -> pesan
yang menyebut sebabnya, bukan "tidak ada video".

### Hasil Fase 21 — SELESAI 2026-08-05

`tests/test_user_browser.py` (19 test) dibuktikan merah lebih dulu.

**Kendala keras yang membentuk seluruh fase.** Diperiksa di mesin Takeda:

```
port 9222 terbuka : False
remote-debugging  : TIDAK ADA
```

Chrome yang **sudah berjalan tidak bisa di-attach belakangan** — ia harus
dimulai dengan `--remote-debugging-port`. Ini fakta teknis, bukan pilihan
desain. Jadi Jarvis hanya punya dua jalur jujur: memakai port bila ada, atau
mengatakan port itu tidak ada.

**Isolasi browser agent TIDAK dibuang.** Ia menyelesaikan masalah nyata (lock
profil, tab user tidak dirusak agent). Yang ditambah jalur kedua:

* `jarvis/integrations/user_browser.py` — attach CDP per operasi. Koneksi
  berumur panjang akan basi begitu user menutup Chrome; attach murah karena
  tidak meluncurkan browser.
* Tool terpisah: `user_browser_status`, `user_browser_tabs`,
  `user_browser_media`, `user_browser_open`. **Dua browser, dua nama tool** —
  menyatukannya membuat target ambigu, dan target ambigu adalah cara tercepat
  kembali ke "pause youtube" yang memeriksa browser yang salah.
* Grup toolgroup sendiri, sehingga Takeda bisa mematikan akses ke browsernya
  tanpa ikut mematikan otomasi browser agent.
* Aturan lane suara menyebut perbedaannya eksplisit.

**Yang paling penting: dua kegagalan yang BERBEDA.** Diverifikasi terhadap
Chrome nyata tanpa port:

```
Saya tidak bisa melihat Chrome Anda: tidak ada yang menjawab di
remote-debugging-port 9222. Chrome yang sudah berjalan tidak bisa
disambungkan belakangan — ia harus dijalankan dengan
--remote-debugging-port=9222. Ini BUKAN berarti tidak ada video yang
sedang diputar; saya memang belum bisa melihatnya.
```

Dikunci `test_media_without_a_port_does_not_claim_there_is_no_video`:
"tak terjangkau" dan "tidak ada yang memutar" wajib menghasilkan alasan yang
berbeda. Menyamakannya membuat Jarvis menyatakan fakta tentang browser yang
tidak pernah ia lihat — S-1 lagi.

**Dua cacat di tes buatanku sendiri**, keduanya membuat test lulus/gagal tanpa
arti: fake merekam skrip JS alih-alih aksinya (dan `_MEDIA_JS` memuat kata
"pause" di badannya, sehingga assertion selalu gagal), dan pemeriksaan substring
"tidak ada video" justru menabrak kalimat yang *menyangkal* klaim itu. Diganti
dengan membandingkan dua alasan kegagalan secara langsung.

**Guard yang bekerja:** `test_toolgroups_usage` menangkap empat tool baru yang
belum terpetakan ke grup mana pun. Itu test lama yang persis dibuat untuk ini.

**BELUM AKTIF sampai Takeda menjalankan Chrome dengan port debug.** Sampai itu,
setiap perintah media/tab akan menjelaskan sebabnya, bukan berbohong.
`user_browser.auto_relaunch` sengaja TIDAK dibuat: menutup Chrome user berisi
tab kerjanya adalah aksi yang harus diminta, bukan diambil diam-diam.

---

## Fase 22 — Interupsi suara terbukti hidup

**Menutup:** S-22.

1. **Pisahkan log test dari log produksi** lebih dulu. Selama keduanya
   bercampur, tidak ada diagnosis runtime yang bisa dipercaya — termasuk
   diagnosis fase ini sendiri.
2. Jawab pembeda ESC, lalu perbaiki lapisan yang benar.
3. Bila barge-in memang tidak memicu: kalibrasi di ruangan Takeda, bukan
   menurunkan ambang membabi buta — kepekaan berlebihan adalah keluhan
   aslinya.
4. Bukti hidup: satu sesi nyata dengan `voice.barge_in` tercatat dari ucapan
   Takeda, bukan dari pytest.

### Hasil Fase 22 — SEBAGIAN 2026-08-05

`tests/test_log_isolation_and_barge_diag.py` (10 test) dibuktikan merah dulu.

**1. Log dipisah — SELESAI.** `log.is_test_run()` + `logging.test_file`.
Dibuktikan dengan menjalankan suite dan mengukur kedua berkas:

```
jarvis-test.log : 183 KB  <- 29 entri barge_in, semuanya milik pytest
jarvis.log      : tumbuh 15 KB, dan itu dari JARVIS yang sedang berjalan
```

Sejak sekarang `barge_in.triggered` di `jarvis.log` pasti berasal dari ucapan
sungguhan.

**2. Rantai interupsi dikunci — SELESAI.** Diperiksa di kode, bukan ditebak:
`main.py:641` `ui.set_state("SPEAKING")` → facade → `_apply_state`; `main.py:572`
`ui.on_interrupt = self.interrupt` → facade setter → `_win.on_interrupt` →
`_do_interrupt`. Dua test mengunci keduanya, termasuk urutan yang tidak boleh
dibalik: **memotong ucapan menang atas menutup panel.**

**3. Diagnostik agar sesi nyata menjawab sendiri — SELESAI.** Barge-in dulu
hanya mencatat saat MEMICU, sehingga "tidak pernah memicu" dan "tidak pernah
jalan" sama-sama terlihat sunyi. Sekarang ada `mic_meter.started` saat stream
terbuka, dan `barge_in.diagnostics` tiap 20 detik selama Jarvis bicara:
`noise_floor`, `threshold`, `blocks_while_speaking`,
`peak_rms_while_speaking`, `triggers`.

**4. Bukti hidup — BELUM.** Ini yang membuat fase ini *sebagian*.

Dua kali dalam fase ini kesimpulan hampir diambil dari **ketiadaan** di log:

* `mic_meter.unavailable` ×5 sempat terbaca sebagai "mic meter mati" — semuanya
  bertanggal **2026-08-04** dengan sebab `No module named 'sounddevice'`, sudah
  lewat. Sesi hari ini bersih dan `barge_in.calibrated` terbit
  (`noise_floor: 0.0039`), jadi mic meter memang hidup.
* Nol baris berisi `"SPEAKING"` sempat terbaca sebagai "Jarvis tidak pernah
  masuk state bicara" — padahal `set_state` memang **tidak menulis log sama
  sekali**. Grep itu tidak membuktikan apa pun.

Keduanya kesalahan yang sama bentuknya: **sunyi bukan bukti.** Karena itu
pekerjaan fase ini diarahkan ke membuat sunyi menjadi mustahil, bukan
menurunkan ambang berdasarkan tebakan.

**Yang dibutuhkan untuk menutupnya:** jalankan ulang JARVIS (agar diagnostik
termuat), bicara menimpa Jarvis saat ia bicara, lalu baca `jarvis.log`:

* tidak ada `mic_meter.started` → thread mic tidak jalan;
* ada, tetapi `blocks_while_speaking` 0 → state SPEAKING tidak pernah tercapai;
* ada blok, `peak_rms_while_speaking` **di bawah** `threshold` → ambang terlalu
  tinggi untuk ruangan Takeda; putar `sensitivity` ke `high`;
* di atas ambang tetapi `triggers` 0 → penolakan crest/pita suara yang perlu
  disetel.

---

## Fase 23 — Rekomendasi membuka SUMBERNYA, bukan transkrip

**Menutup:** S-23.

1. Berhenti mengirim transkrip mentah ke browser sistem. Kalau tidak ada sumber
   yang bisa dibuka, jangan buka apa pun.
2. Sumber harus berasal dari **hasil tool**, bukan dari kata-kata user: URL
   hasil `web_search`, tautan media sosial, atau lokasi Maps.
3. **Bertipe** sesuai rekomendasi — untuk tempat makan, Google Maps adalah
   sumber yang benar (lokasi, jam buka, rating), bukan halaman hasil pencarian.
4. **Tawarkan, jangan langsung buka** — Takeda meminta "opsi". Satu tab untuk
   sumber yang dipilih, bukan semua sekaligus.
5. Dibuka di Chrome Takeda (butuh Fase 21) supaya ia benar-benar melihatnya.

**Test merah dulu:** rekomendasi tempat -> tawaran memuat sumber bertipe
(web/sosial/map); tidak ada jalur yang mengirim transkrip mentah sebagai kueri.

### Hasil Fase 23 — SELESAI 2026-08-05

`tests/test_recommendation_sources.py` (27 test) dibuktikan merah lebih dulu.

`jarvis/agent/sources.py` baru. Aturannya satu kalimat: **setiap URL dibangun
dari HASIL TOOL, tidak pernah dari kata-kata user.** Tanpa hasil, tidak ada
yang dibuka — diam lebih jujur daripada memantulkan ucapan ke layar.

* Sumber **bertipe** dari host, bukan tebakan kata: `map` / `social` / `web`.
* Permintaan tempat mendahulukan peta. Bila hasil tool tidak memuat baris
  Maps, satu sumber peta **disintesis dari nama tempat pada judul hasil** —
  tetap dari hasil tool, bukan dari kalimat user.
* **Tawaran, bukan aksi.** Takeda meminta "opsi": `offer_text()` bertanya,
  tidak membuka.
* Dibuka di **Chrome Takeda** lewat Fase 21; bila tak terjangkau, sebabnya
  yang disebut.

Perilaku nyata:

```
'carikan saya restoran yang enak di dekat sini'
   tempat? True  | urutan: map, web, social
   "Mau saya buka peta lokasinya, halaman resminya, atau media sosialnya
    di Chrome Anda?"

'cari resep warung bu tini'
   tempat? False | urutan: web, social
```

Baris kedua itu koreksi terhadap versi pertamaku: regex tempat menangkap
"warung" pada permintaan RESEP, sehingga peta didahulukan padahal yang dicari
konten. Kata benda konten (resep, harga, menu, review) kini membatalkan
pembacaan tempat — kecuali ada penanda kedekatan, yang selalu berarti lokasi.

**Kontrak P0 lama dicabut dengan alasan tertulis.**
`test_voice_search_command_opens_system_browser` mengunci "pencarian suara
membuka browser sistem dengan kuerinya" — persis perilaku yang menghasilkan
`'kan saya restoran yang - Search - Google Chrome'`. Diganti, dan alasannya
ditulis di tempatnya. Yang **tidak** berubah: membuka URL yang jelas ("buka
example.com") tetap lewat browser sistem, karena di sana tidak ada transkrip
yang dipantulkan.

**Crash yang KUBUAT SENDIRI, lalu kutemukan.** Setelah `run_search` dialihkan
ke `_run_web_lookup`, suite mulai crash `Windows fatal exception: access
violation` di `jarvis/ui/stage.py`. Sebabnya perubahanku: test routing kini
menjalankan thread `web_search` dengan **jaringan sungguhan**, dan thread itu
menyentuh objek Qt setelah window dibongkar. Sekaligus merusak jaminan
"suite tidak butuh jaringan" yang baru dibuktikan di S-15. Diperbaiki dengan
menambal pekerjaannya di test routing — yang diuji di sana memang ROUTING,
bukan pengambilan data.

Diverifikasi **3 run berturut dengan socket keluar diblokir**: 2348 lulus,
nol crash. Terlihat hanya karena suite dijalankan ulang setelah hijau, bukan
karena ada test yang merah.

---
---

# SIKLUS 4 — eksekusi instan tanpa kehilangan kecerdasan (2026-08-06)

**Pemicu:** ide Takeda — *"bagaimana caranya agar jarvis bisa secara instant
mengeksekusi perintah dan tetap pintar mengetahui apa jenis perintahnya."*

## Ke mana waktunya pergi sekarang

Terukur di mesin Takeda, 2026-08-05:

```
LLM berat, chat mentah        3,6 s
LLM berat + schema tool       1,3 s
agent loop tanpa tool         2,5 s   (1 iterasi)
agent loop dengan tool        7,0 s   (2 iterasi; web_search 3,4 s)
sub-agent delegate            3,0 s
router deterministik          ~0 ms   <- SUDAH instan
ACK                           <1 ms   <- SUDAH instan
```

**Router sudah instan.** Jarvis sudah tahu jenis perintah tanpa LLM untuk
perintah yang jelas. Yang lambat adalah EKSEKUSI — sebagian besar berupa
menunggu model memutuskan hal yang sebenarnya sudah bisa ditebak.

## Gagasan inti

Bagi lane berdasarkan **seberapa mahal kalau salah**, bukan berdasarkan
kerumitan.

| Sifat | Contoh | Boleh instan? |
|---|---|---|
| Reversible sepenuhnya | pause, volume, buka tab, baca | **ya — jalankan dulu** |
| Terlihat tetapi bisa dibatalkan | buka aplikasi, navigasi | ya, dengan jejak |
| Tidak bisa ditarik kembali | telepon, kirim pesan, hapus | tidak — verifikasi dulu |

Perintah reversible tidak perlu menunggu model sama sekali. Itu sebagian besar
pemakaian harian, dan di situlah "instan" benar-benar terasa.

| Fase | Judul | Status |
|---|---|---|
| 24 | Ukur dulu: rincian latensi per tahap | ✅ **SELESAI** 2026-08-06 |
| 25 | Memori perintah TERVERIFIKASI | ⬜ |
| 26 | Routing berbasis embedding, lokal | ⬜ |
| 27 | Eksekusi spekulatif untuk aksi reversible | ⬜ |
| 28 | Satu antrean bicara | ✅ **SELESAI** 2026-08-06 |
| 29 | Sesi model hangat | ⬜ |

**Urutan disarankan semula: 24 → 28 → 25 → 26 → 27 → 29.**
**Diperbarui setelah Fase 24:** 26 (embedding lokal) NAIK — ia ada di
jalur kritis setiap giliran, bukan hanya routing. Urutan sisa:
**26 → 25 → 27 → 29.**
24 lebih dulu karena tanpa rincian latensi, sisanya menebak — sesi ini sudah
dua kali membuktikan tebakan arsitektur bisa meleset total (S-13 dikira
pustaka native, ternyata thread bocor; S-22 dikira ambang, ternyata echo guard
sendiri). 28 berikutnya karena paling murah dan paling terasa.

---

## Fase 24 — Ukur dulu, jangan tebak

Belum ada rincian latensi per tahap. Stempel waktu yang dibutuhkan: transkrip
final → router → pemilihan tool → panggilan LLM pertama → tool pertama →
ucapan pertama.

Tanpa ini, Fase 25-29 mengoptimalkan bagian yang belum tentu lambat.

### Hasil Fase 24 — SELESAI 2026-08-06

`jarvis/core/latency.py` + `tests/test_latency_breakdown.py` (15 test), merah
lebih dulu. Penanda dipasang di `dispatch` (buka saat ACK — titik user mulai
menunggu) dan `loop` (`setup`, `first_llm`, `first_tool`).

**Penanda pertama menyesatkan, dan pengukuran sendiri yang menunjukkannya.**
Versi awal hanya menandai satu titik sebelum panggilan model, sehingga
"persiapan" dan "durasi LLM" tercampur jadi satu angka yang tidak bisa
ditindaklanjuti. Dipecah menjadi `setup` dan `first_llm`.

Hasil pertama:

```
tanpa tool  | total 8,19s | setup 3,75s | first_llm 4,42s
dengan tool | total 5,64s | setup 0,47s | first_llm 1,86s | first_tool 1,78s
```

**Setup 3,75 detik SEBELUM model dipanggil sama sekali.** Bongkar isinya:

```
memory_store.search    3250 ms dingin,  422 ms hangat   <- pelakunya
registry.schemas        328 ms dingin,   46 ms hangat
persona / skills          ~0 ms
```

`memory_store.search` memanggil embedding — **round trip jaringan ke Gemini
pada setiap giliran, sebelum model ditanya**.

**Ini membantah asumsi roadmap Siklus 4 sendiri.** Rencana menempatkan
panggilan LLM sebagai biaya dominan dan menaruh embedding lokal di Fase 26.
Pengukuran menunjukkan recall memori yang mendominasi giliran pertama. Persis
alasan Fase 24 didahulukan — dan alasan ketiga dalam siklus ini di mana tebakan
arsitektur meleset (setelah S-13 dan S-22).

**Perbaikan langsung yang mengikuti bukti:** recall semantik diberi TENGGAT
(`agent.memory.embed_deadline_s`, default 0,4 s). Lewat tenggat, giliran
memakai pencarian keyword FTS5 yang sepenuhnya lokal dan memang sudah ada
sebagai fallback. Permintaan yang telat tidak dibatalkan — hasilnya diabaikan,
dan tidak pernah menahan giliran.

```
SEBELUM | setup 3,75s
SESUDAH | setup 1,08s
```

Jawaban yang sedikit kurang kaya jauh lebih baik daripada menunggu tiga detik
sebelum Jarvis mulai berpikir.

**Akibat bagi urutan Siklus 4:** embedding lokal (Fase 26) naik peringkat —
ia bukan hanya soal routing, melainkan berada di jalur kritis SETIAP giliran.
`registry.schemas` 328 ms dingin memperkuat Fase 29.

**Yang BELUM terukur:** rentang transkrip suara → dispatch. Penanda saat ini
dibuka di ACK, sedangkan waktu antara Takeda selesai bicara dan ACK terbit
masih gelap. Itu pekerjaan berikutnya bila "instan" masih terasa kurang setelah
Fase 28.

---

## Fase 25 — Memori perintah TERVERIFIKASI

Perintah yang **terbukti** berhasil (memakai kontrak bukti Fase 14) disimpan:
ucapan ternormalisasi → tool + argumen. Perintah sama besok dieksekusi tanpa
LLM sama sekali.

Bergantung pada pekerjaan yang sudah selesai: hanya yang buktinya sah yang
disimpan, sehingga cache tidak pernah mengabadikan klaim palsu.
`memory_store` + embedding 768-dim hidup lagi sejak Fase 13.

**Batas keras:** aksi yang tidak bisa ditarik kembali TIDAK boleh dijalankan
dari kemiripan. "telepon Honbrew" boleh; "telepon Honbru" yang mirip tidak
boleh langsung jalan dari cache.

### Hasil Fase 25 — SELESAI 2026-08-08

**Batas kerasnya dipenuhi lewat kunci pencocokan, bukan lewat daftar
pengecualian.** Kunci replay adalah aliran token ternormalisasi
(`local_embed.tokens`, dibangun di Fase 26), bukan skor kemiripan. Kesopanan
dan imbuhan boleh berbeda — "tolong bukakan kameranya" *adalah* "buka kamera" —
tetapi setiap kata isi harus sama persis. Karena itu "telepon Honbru" tidak
pernah menjawab rencana "telepon Honbrew", dan "buka kamera depan" bukan "buka
kamera". Tidak ada daftar aksi-berbahaya yang harus dipelihara; satu huruf yang
berbeda sudah cukup untuk membatalkan replay.

Yang dikerjakan:

* `jarvis/agent/command_plan.py` — tabel SQLite, maks 200 baris, maks 3 langkah.
* `Session.record_plan` + pemanggilan di `registry._log_call`. **Ini perlu
  kanal sendiri:** `record_tool` DAN `record_evidence` sama-sama menerima
  argumen yang sudah lewat `_audit_args`. Membonceng salah satunya berarti
  menyimpan rencana berisi nilai bertopeng lalu mengeksekusinya besok —
  kegagalan yang tidak akan pernah terlihat sampai ia terjadi.
* `dispatch._replay_plan` — dicoba sebelum `agent_loop.run`.

**Tiga hal yang sengaja tidak boleh disimpan**, masing-masing dengan ujinya:

| Ditolak | Alasan |
|---|---|
| rencana yang argumennya berubah saat diaudit | menjalankan nilai bertopeng lebih buruk daripada tidak menyimpan |
| hasil lebih dari 200 karakter | modelnya sedang MERANGKAI jawaban, bukan bertindak — merangkai tidak bisa diulang |
| kalimat hasil kemarin | bisa memuat fakta kemarin ("cuacanya 30 derajat"); yang diucapkan harus hasil run hari ini |

**Replay tetap lewat `registry.execute`.** Konfirmasi, policy, dan audit
berlaku persis sama. Ada uji yang menolak bila `_replay_plan` sampai membawa
tanda "sudah disetujui". Tujuh fase dihabiskan membuat klaim Jarvis jujur;
kecepatan tidak dibeli dengan melewati satu pun dari itu.

**Kasus yang paling mudah salah, dan bagaimana ditanganinya.** Bila langkah
gagal, jawabannya berbeda tergantung *di mana*:

* gagal di langkah **pertama** — belum ada yang terjadi, aman diserahkan ke
  model, rencananya dibuang;
* gagal di **tengah** — langkah sebelumnya SUDAH berjalan. Mengulang lewat
  model berarti mengerjakannya dua kali, jadi Jarvis berhenti dan mengatakan
  apa adanya: langkah mana yang gagal, kenapa, dan bahwa sisanya tidak diulang.

**Satu cacat rancanganku ditangkap suite, bukan oleh uji fase ini.**
`_collect_plan` menuntut sesi punya `record_plan`, sehingga `_FakeSession`
milik `test_phase2_browser_lease` menjatuhkan tiga tes. `registry` sudah
memakai kanal itu secara defensif dan dispatch seharusnya sama: belajar itu
kenyamanan, dan kenyamanan tidak boleh menjatuhkan tugas yang seharusnya
berjalan. Ada uji regresinya sekarang.

**Bukti:** `focused-tested` — 24 uji di `tests/test_command_plan.py`, 2496
lulus seluruh suite, ruff bersih, FROZEN utuh. **Belum `live-proven`:**
rencananya kosong sampai Takeda memakai Jarvis sungguhan, dan giliran pertama
sebuah perintah selalu lewat model.

---

## Fase 26 — Routing berbasis embedding, lokal

Perintah yang tidak cocok regex kini jatuh ke LLM. Ganti dengan tetangga
terdekat atas perintah yang pernah dipakai, memakai model embedding **lokal**
(ONNX MiniLM, ~20 ms) — bukan jaringan, karena jaringan justru yang sedang
dihindari.

Sekaligus menjawab keluhan lapangan: pemilihan tool belajar dari pemakaian
Takeda, bukan dari regex yang harus ditulis satu per satu.

### Hasil Fase 26 — SELESAI 2026-08-08

**Rencana awal salah di satu titik dan itu diperbaiki, bukan disembunyikan.**
Rencana menyebut ONNX MiniLM ~20 ms. Tidak ada model teks di repo — hanya
`yolov8n.onnx` untuk visi — dan MiniLM berarti unduhan ~90 MB. Itu keputusan
Takeda, bukan keputusan kode. Yang dibangun karena itu adalah embedder
**leksikal**: token kata + bigram + n-gram karakter yang di-hash. Bukan
pemahaman semantik, dan tidak berlagak begitu. Antarmukanya (`embed`,
`similarity`) sengaja sempit supaya model neural bisa menggantikannya kelak
tanpa menyentuh satu pun pemanggil.

Yang dikerjakan:

* `jarvis/core/local_embed.py` — embedder lokal, **0.066 ms** per perintah
  (bandingkan 422 ms hangat / 3250 ms dingin lewat jaringan pada Fase 24).
  Hash memakai `zlib.crc32`, **bukan** `hash()` bawaan: hash string Python
  diacak ulang tiap proses, jadi indeks yang ditulis hari ini tidak akan cocok
  dengan yang dibaca setelah restart. Ada uji subprocess yang mengunci ini.
* `jarvis/agent/command_index.py` — tabel SQLite (maks 400 baris, yang paling
  lama tak dipakai dibuang), tidak pernah melempar.
* `jarvis/agent/tool_selection.py` — `_learned_tool_names` dipakai **hanya**
  saat regex kategori tidak menemukan apa pun atau menemukan terlalu banyak
  (>3). Kategori deterministik tetap menang. Saran yang menyebut tool yang
  sudah tidak ada diabaikan seluruhnya, bukan disaring sebagian.
* `jarvis/agent/dispatch.py` — belajar di jalur `result.ok`.

**Dua kesalahan rancanganku yang ditangkap ukuran, bukan oleh uji hijau.**

1. Sumber pembelajaran mula-mula kupakai daftar bukti kontrak. Bukti itu hanya
   dikumpulkan untuk tugas **berkontrak** (YouTube, panggilan), jadi Jarvis
   nyaris tidak akan pernah belajar apa pun. Diganti ke `session.tool_calls`
   yang selalu terisi dan sudah teredaksi — hanya nama tool dan statusnya.

2. Ukuran pertama pada perintah lapangan sungguhan membantah embeddernya:

   | pasangan | skor lama |
   |---|---|
   | `buka kamera` ~ `tutup kamera` (**lawan kata**) | 0.483 |
   | `buka kamera` ~ `tolong bukakan kameranya` | 0.336 |
   | `telepon honbrew lewat whatsapp` ~ `telpon honbrew via wa` | 0.419 |

   Lawan kata lebih dekat daripada parafrasanya sendiri. Uji awalku lulus
   karena frasa ujinya pendek dan tumpang tindih ("pause youtube" / "pause
   yt") — bukan seperti cara Takeda benar-benar bicara. Penyebabnya: imbuhan
   ("bukakan", "kameranya") dan kata sopan ("tolong", "via") memecah n-gram,
   sementara kata kerja yang menentukan tool cuma satu token melawan puluhan
   n-gram objek yang sama. Perbaikannya: buang stopword, petakan sinonim
   (`wa`→`whatsapp`, `telpon`→`telepon`), kupas imbuhan, dan beri kata bobot
   4× di atas n-gram karakter.

**Ambang diukur, bukan ditebak.** Setelah perbaikan, atas 10 pasangan satu
tool dan 10 pasangan beda tool: parafrasa terendah **0.814**, beda-tool
tertinggi **0.649** (`putar lagu di spotify` ~ `hentikan lagu di spotify`).
Ambang 0.62 dari rencana awal jatuh **di dalam** wilayah beda-tool — perintah
berhenti akan dirutekan ke tool putar. Ambang dipasang **0.75**, di celahnya,
dan condong ke atas: saran yang meleset hanya mengembalikan perilaku lama,
saran yang salah mematahkan perintah. Uji `test_the_threshold_sits_inside_a_
real_gap` mengunci celah itu (>0.1), bukan cuma angka ambangnya — tanpa itu
satu perubahan pembobotan bisa merapatkan kedua kelompok sampai berimpit
sementara semua uji lain tetap hijau.

**Bukti:** `focused-tested` — 44 uji di `tests/test_local_embed_routing.py`,
2471 lulus seluruh suite, ruff bersih, FROZEN utuh. **Belum `live-proven`:**
indeks baru terisi setelah Takeda memakai Jarvis sungguhan; manfaatnya nol
pada perintah yang belum pernah berhasil sekali pun.

---

## Fase 27 — Eksekusi spekulatif untuk aksi reversible

Jalankan jalur deterministik **segera**, tanyakan model **paralel**. Bila model
tidak setuju sebelum aksi selesai, batalkan. Aksi tak-tertarik tetap menunggu
kesepakatan.

Inilah yang membuat "instan tapi tetap pintar" mungkin — bukan memilih salah
satu di antara keduanya.

### Hasil Fase 27 — DIUKUR, TIDAK DIBANGUN 2026-08-08

**Premisnya tidak berlaku, dan itu terlihat dari ukuran — bukan dari
pendapat.** Fase ini mengandaikan jalur deterministik sedang MENUNGGU model.
Yang terukur:

| perintah | tier | keputusan |
|---|---|---|
| `buka spotify` | T0 | 0,17 ms |
| `pause youtube` | T1 | 0,01 ms |
| `cari berita hari ini` | T1 | 0,02 ms |
| `telepon honbrew lewat whatsapp` | T2 | 0,02 ms |
| `buatkan ringkasan rapat tadi` | T2 | 0,02 ms |

`router.llm_fallback = False`, jadi tidak ada satu pun panggilan model di
jalur klasifikasi. Jalur deterministik sudah berjalan **seketika**; model
hanya ditanya justru di tempat yang TIDAK punya jalur deterministik. Irisan
tempat spekulasi berguna karena itu kosong:

* perintah yang persis berulang → sudah ditangani Fase 25, tanpa model;
* perintah yang cocok aturan → sudah instan, tanpa model;
* sisanya → memang butuh model, tidak ada apa pun untuk dijalankan paralel;
* aksi tak-tertarik → dilarang berspekulasi oleh aturan rencananya sendiri.

Membangunnya berarti menambah balapan pembatalan dan risiko aksi ganda demi
keuntungan yang tidak bisa ditunjukkan angkanya. Fase ini ditutup sebagai
**diukur dan sengaja tidak dibangun**, bukan sebagai pekerjaan tertunda.

### S-31 — dua router tidak sepakat, dan yang lebih pintar tidak dipakai

Ini temuan nyata yang muncul dari pengukuran di atas, bukan bagian dari
rencana mana pun.

`jarvis/agent/router.py` menyimpulkan `pause youtube` adalah **T1, "single
browser media action"**, dalam 0,01 ms. Tetapi jalur perintah UI memakai
`IntentRouter` di `jarvis/core/router.py`
([window.py:1042](jarvis/ui/window.py#L1042)), yang menyimpulkan **CHAT** →
`_chat()` → pipeline model. Hal yang sama terjadi pada `kirim pesan ke
honbrew` dan `telepon honbrew lewat whatsapp`.

Jadi Jarvis SUDAH tahu jawabannya secara deterministik, lalu membuangnya dan
bertanya ke model. Ini persis "instan tapi tetap pintar" yang Takeda minta —
tanpa spekulasi sama sekali, karena tidak ada yang perlu ditebak.

**Belum dikerjakan dengan sengaja:** menjembatani kedua router mengubah jalur
perintah utama untuk setiap ucapan, dan itu keputusan cakupan milik Takeda,
bukan efek samping dari fase yang isinya ternyata kosong.

---

## Fase 28 — Satu antrean bicara

Keluhan lapangan Takeda: *"suara tumpang tindih dan saling memotong membuat
saya bingung apa yang sedang dikerjakan."*

ACK, narator progres, dan hasil akhir bisa berbunyi bersamaan. Satu antrean
dengan prioritas; yang lebih baru membatalkan yang basi. ACK menyebut RENCANA
yang terurai ("Menelepon Honbrew…") sehingga Takeda bisa mengoreksi sebelum
aksinya berjalan.

Ini juga pekerjaan latensi: yang perlu instan adalah UMPAN BALIKNYA, bukan
pekerjaannya.

### Hasil Fase 28 — SELESAI 2026-08-06

`jarvis/core/speech_queue.py` + `tests/test_speech_queue.py` (18 test), merah
lebih dulu.

**Sebabnya terukur di kode, bukan ditebak:** `MainWindow._speak_line`
melahirkan **thread baru untuk setiap kalimat**, dan ada **42 pemanggil** —
ACK, narator progres, hasil akhir, konfirmasi, ringkasan pencarian. Tidak ada
satu pun yang menyerialkan mereka.

Semua kini lewat satu pintu. Tetapi yang membuatnya berguna bukan pengurutan,
melainkan **apa yang DIBUANG**:

| Jenis | Perlakuan |
|---|---|
| `confirm` | mendahului antrean, **tidak pernah** dibuang |
| `final` | membatalkan progres dan ACK giliran yang sama |
| `ack` | dibuang bila hasilnya sudah tiba |
| `progress` | digantikan progres yang lebih baru |

Progres basi yang terdengar SETELAH hasilnya ada persis penyebab kebingungan
"apa yang sedang dikerjakan". Pembatalan mengikat SATU giliran, bukan seluruh
antrean — pekerjaan latar milik giliran lain tidak ikut bungkam.

Pertanyaan konfirmasi sengaja jadi satu-satunya yang kebal: pertanyaan yang
hilang membuat user menunggu jawaban yang tidak pernah diminta.

**Ditemukan lewat test:** fake `_speak_line` di test Fase 15 tidak menerima
argumen `kind` baru, sehingga pemanggilannya melempar dan **ditelan `try/except`
di `ask`** — test lulus/gagal tanpa arti. Fake diperbaiki dan assertion
diperkuat: pertanyaan konfirmasi kini juga diperiksa jenisnya, bukan hanya
isinya. Kelas kesalahan yang sama sudah muncul di Fase 15, 19, 21, dan 24 —
fake parsial yang tertinggal dari bentuk aslinya.

**Yang BELUM dikerjakan dari rencana fase ini:** ACK yang menyebut rencana
terurai ("Menelepon Honbrew…"). Antreannya sudah siap menerimanya; teks ACK-nya
sendiri masih milik `ack_composer` dan belum sadar-kontrak.

---

## Fase 29 — Sesi model hangat

90 schema tool dikirim ulang tiap panggilan. Shortlist sudah ada; tambahkan
cache serialisasi + prompt caching, dan pertahankan sesi per lane.

### Hasil Fase 29 — SELESAI 2026-08-08

**Premis rencananya salah dan pengukuran memperbaikinya.** Rencana menuduh
schema "dikirim ulang tiap panggilan"; `schemas()` ternyata dipanggil **sekali
per tugas** ([loop.py:193](jarvis/agent/loop.py#L193)), di luar loop iterasi.
41 ms, bukan 500 ms. Biaya yang sebenarnya ada di tempat lain, dan hanya
terlihat setelah diukur di proses baru:

| tahap | dingin |
|---|---|
| `import llm_client` | 235 ms |
| `client()` | 248 ms |
| **SDK dibangun (import + ctor)** | **1577 ms** |
| `all_tools()` (103 tool) | 319 ms |
| `schemas()` (94 schema) | 49 ms |
| **total sebelum model ditanya apa pun** | **2427 ms** |

Itulah yang Takeda tunggu pada perintah pertama setelah boot. Tidak satu pun
bergantung pada isi perintah — jadi tidak ada alasan menunggu perintah untuk
mengerjakannya.

| | sebelum | sesudah |
|---|---|---|
| jalur perintah pertama | 2427 ms | **1,3 ms** |
| boot terblokir oleh pemanasan | — | 0,8 ms |
| `schemas()` hangat | 41,6 ms | **0,28 ms** |
| `descriptor_for_tool` × 103 | 16,5 ms | 0,07 ms |

Yang dikerjakan: `jarvis/agent/prewarm.py` (thread latar, dipasang di
`jarvis/main.py` di sebelah `app_registry.refresh_async`), cache schema per
tool di `registry`, dan satu snapshot descriptor per `schemas()`.

**Cache yang SENGAJA tidak dibuat, dan kenapa.** Versi pertamaku meng-cache
indeks `descriptor_for_tool` lintas panggilan. Itu menjatuhkan empat tes lama —
dan penyebabnya bukan tesnya. Tanda tangan cache apa pun yang cukup murah
hanya menangkap **id** descriptor, bukan isinya, sehingga descriptor yang
didaftar ulang dengan id sama tetapi `risk` berbeda dijawab dari salinan lama.
Nilai itu masuk ke `policy.decide`. Kecepatannya nyata, tetapi harganya adalah
izin yang dinilai dengan angka yang sudah tidak berlaku, diam-diam. Biaya
O(n²)-nya ternyata datang dari `schemas()` yang memanggil fungsi itu 103 kali;
diselesaikan dengan satu indeks **lokal** yang mati bersama fungsinya —
manfaat penuhnya, tanpa satu pun jawaban basi yang bisa bertahan. Ada uji
regresi khusus untuk skenario `risk` berubah itu.

Karena alasan yang sama, apa pun yang bergantung `context` atau policy tidak
di-cache sama sekali: `exposed_tool_names` menjalankan `policy.decide` per
descriptor dan tetap dihitung segar.

**Yang TIDAK dikerjakan, dan kenapa.** Prompt caching ada di rencana tetapi
tidak dikerjakan. Lane berat memakai endpoint OpenAI-compatible generik; SDK
OpenAI tidak punya tombol cache di sisi klien (server yang memutuskan), dan
`cache_control` Anthropic hanya berlaku untuk jalur Anthropic yang tidak
aktif — menambahkannya berarti mengirim kode yang tidak bisa dibuktikan
jalan dari sini. Dicatat, bukan ditebak.

**Bukti:** `focused-tested` + `runtime-wired` — 22 uji di
`tests/test_prewarm_and_schema_cache.py`, 2518 lulus seluruh suite, ruff
bersih, FROZEN utuh. Angka di atas diukur ulang setelah perubahan.
**Sisa yang jujur:** bila Takeda bicara dalam ~2,4 detik pertama setelah boot,
pekerjaannya tetap harus terjadi — pemanasan hanya menumpangkannya, dan
`_lock` registry memastikan penemuan tool tidak berjalan dua kali (ada
ujinya).

---

## Yang sebaiknya TIDAK dilakukan

* **Jangan melonggarkan konfirmasi demi kecepatan.** Tujuh fase dihabiskan
  untuk membuat klaim Jarvis jujur. Cepat tetapi berbohong lebih buruk
  daripada lambat.
* **Jangan cache aksi tak-tertarik berdasarkan kemiripan.**
* **Jangan kejar instan di lane berat.** Riset multi-langkah memang lambat;
  yang perlu instan adalah umpan baliknya.

## Tuas terbesar yang bukan kode

Endpoint `custom` di `http://43.167.18.81` — tiap panggilan melewati internet
ke IP pihak ketiga; chat mentah 3,6 detik. **Model lokal untuk lane ringan**
(klasifikasi, ACK, kompresi) memangkas lebih banyak latensi daripada seluruh
Fase 25-29 digabung, sekaligus menutup S-6 yang diterima apa adanya.

Keputusan perangkat keras, bukan kode — tetapi bila tujuannya "instan", itu
tuas terbesar yang tersedia.

---

# SIKLUS 5 — permintaan yang belum tersentuh & fitur yang mati diam-diam (2026-08-08)

Siklus 4 menutup seluruh fase bernomor. Yang tersisa adalah satu permintaan
Takeda yang **belum pernah dijadikan fase sama sekali**, satu temuan dari
pengukuran Fase 27, dan tiga fitur yang mati tanpa mengeluarkan suara.

Urutannya bukan urutan kemudahan, melainkan urutan **apa yang Takeda rasakan**.

| Fase | Isi | Menutup |
|---|---|---|
| 30 | Jarvis mengenali suara Takeda | permintaan lapangan yang belum pernah difasekan |
| 31 | Pakai jawaban deterministik yang sudah ada | S-31 |
| 32 | WebEngine diimpor sebelum `QApplication` | T4 |
| 33 | Memori semantik: hidup, atau mati dengan jujur | T5 |
| 34 | Tunggu keadaan, bukan tidur tetap | T8 |

---

## Fase 30 — Jarvis mengenali suara Takeda

Permintaan aslinya: *"saya ingin jarvis bisa mengenali suara saya seperti siri
dan hanya merespon suara saya ketika pertama kali booting."*

**Tap-nya sudah ada.** `MainWindow._mic_meter` memegang `sd.InputStream`
16 kHz mono, blok 1024 sampel, dan file itu tidak FROZEN. Tidak ada jalur
audio baru yang perlu dibuka.

**Batas jujur, dinyatakan di muka.** Tidak ada model speaker di repo, dan
ECAPA/Resemblyzer berarti unduhan puluhan MB — keputusan Takeda, bukan
keputusan kode. Yang dibangun di sini adalah sidik suara spektral memakai
numpy saja. Ia bisa memisahkan dua suara yang jelas berbeda pada mikrofon dan
ruangan yang sama; ia **tidak** setara pengenal suara neural, dan tidak akan
berpura-pura begitu. Antarmukanya dibuat sempit supaya model neural bisa
menggantikannya tanpa mengubah pemanggil.

**Keputusan rancangan yang paling penting: gerbangnya MATI dulu.**
Verifikasi suara yang keliru membuat Jarvis TULI terhadap pemiliknya sendiri —
kegagalan yang jauh lebih buruk daripada menjawab orang lain sesekali. Karena
itu fase ini default-nya **mengamati saja**: skor tiap ucapan dihitung dan
dicatat, tanpa menolak apa pun. Ambangnya diambil dari suara Takeda di
mikrofon Takeda, persis seperti S-25 mengajarkan — bukan dari nada sintetis.
Gerbangnya dinyalakan Takeda setelah angkanya terlihat.

**Dan bila kelak menolak, penolakannya harus TERLIHAT.** Perintah yang
diabaikan diam-diam adalah kelas bug yang tujuh fase dihabiskan untuk
memberantasnya.

### Hasil Fase 30 — SELESAI (mengamati) 2026-08-08

`jarvis/core/speaker_id.py` + `tests/test_speaker_id.py` (36 uji), merah lebih
dulu. Sidik suara: selubung rata-rata dan sebarannya di 32 pita mel,
dinormalisasi terhadap kekerasan suara, numpy saja, tanpa unduhan.

Terpasang di `MainWindow._mic_meter` — stream yang sama sudah memegang seluruh
audio mic, jadi tidak ada jalur audio kedua yang dibuka. `Listener` menyatukan
blok 64 ms menjadi satu ucapan dan menutupnya saat sunyi; menilai per blok
tidak mungkin mengenali siapa pun.

**Pengukuran membantah ambang bawaanku, dan itu bagian terpenting fase ini.**
Angka awal 0.82 kupilih sebelum mengukur. Hasilnya:

| | skor |
|---|---|
| pemilik, take lain | 1.000 |
| pemilik, +derau 5× | 0.994 |
| pemilik, f0 geser 10% (flu/lelah) | 0.984 |
| **penutur lain, suara rendah** | **0.903** ← LOLOS |
| **penutur lain, formant beda** | **0.860** ← LOLOS |
| penutur lain, suara tinggi | 0.618 |

Dua dari tiga "penutur lain" lolos ambang tetap. Sebaliknya take pemilik
semuanya 1.000 — sinyal sintetis terlalu bersih untuk melahirkan ambang apa
pun. Ini jebakan S-25 yang sama persis. Karena itu ambangnya sekarang
**dikalibrasi saat pendaftaran**: tiap take dibandingkan dengan take lainnya
(leave-one-out), dan ambangnya ditaruh sedikit di bawah take pemilik yang
paling buruk — yaitu seberapa jauh suara Takeda bisa menyimpang dari dirinya
sendiri, pada mikrofon itu, di ruangan itu. `DEFAULT_THRESHOLD` tinggal
cadangan terakhir.

**Tiga keadaan yang sengaja TIDAK pernah menolak**, masing-masing berujinya:

| keadaan | alasan |
|---|---|
| belum terdaftar | tidak ada yang bisa dibandingkan |
| audio tak terpakai (sunyi/terlalu pendek) | bukan bukti bahwa itu orang lain; menolaknya membuat Jarvis membisu tiap kali mikrofonnya buruk |
| profil rusak | satu berkas cacat tidak boleh membuat Jarvis tuli |

**Bukti:** `focused-tested` + `runtime-wired` — 36 uji, 2554 lulus seluruh
suite, ruff bersih, FROZEN utuh.

**Yang uji-uji ini TIDAK buktikan, dan ini harus dibaca sebelum menyalakan
gerbangnya:** seluruh angka di atas berasal dari suara sintetis. Ia
membuktikan pipanya — determinisme, batas, penanganan sampah, penolakan yang
terlihat, kalibrasi yang bekerja — dan **tidak** membuktikan akurasi pada
suara manusia. Variasi suara manusia yang sama jauh lebih besar daripada 1.000
yang terlihat di tabel. Karena itu `voice.speaker_id.gate` **default False**:
Jarvis menghitung dan mencatat skor tiap ucapan tanpa menolak apa pun, sampai
Takeda melihat `speaker_id.observed` di lognya sendiri dan memutuskan.

---

## Fase 31 — Pakai jawaban deterministik yang sudah ada (S-31)

`jarvis/agent/router.py` menyimpulkan `pause youtube` sebagai **T1, single
browser media action**, dalam 0,01 ms. Jalur perintah UI memakai
`IntentRouter` yang menyimpulkan **CHAT** lalu menyerahkannya ke pipeline
model. Jarvis sudah tahu jawabannya, lalu membuangnya.

Ini "instan tapi tetap pintar" tanpa spekulasi sama sekali — tidak ada yang
perlu ditebak, hanya jawaban yang sudah ada dan tidak dipakai.

**Risikonya nyata dan harus dibatasi:** ini jalur SETIAP ucapan. Jembatannya
hanya boleh bekerja ketika router tier yakin DAN ada tool yang jelas untuk
niat itu; selain itu perilakunya harus identik dengan hari ini.

### Hasil Fase 31 — SELESAI 2026-08-08

`router.deterministic_tool(text)` mengembalikan `(tool, args)` atau `None`,
dipasang **tepat sebelum** `_chat()` di `MainWindow._dispatch_command`
— bukan di depan segalanya. Jembatan yang duduk di depan akan mendahului
aturan yang sudah benar untuk SETIAP ucapan; di sini ia hanya mengisi celah
yang tadinya jatuh ke model. Ada uji yang mengunci urutan itu.

Polanya memakai `_BROWSER_MEDIA_RE` yang **sama** dengan yang menggerakkan
keputusan tier. Salinan kedua sebuah regex akan menyimpang diam-diam — tier
bisa bilang T1 sementara jembatannya bilang tidak tahu, tanpa ada yang
menyadarinya. Ada ujinya juga.

**Satu cacat nyata ditemukan saat mengerjakannya.** Aturan medianya menuntut
`video`, sehingga akhiran yang selalu Takeda pakai tidak pernah cocok:

| perintah | sebelum | sesudah |
|---|---|---|
| `jeda videonya` | fallback percakapan, tanpa tool | T1 media → `user_browser_media` |
| `pause videonya` | fallback percakapan | T1 media → `user_browser_media` |
| `lanjutkan videonya` | fallback percakapan | T1 media → `user_browser_media` |

Jadi aturan itu selama ini nyaris tidak pernah kena pada cara Takeda benar-benar
bicara. Diperbaiki di regex bersamanya, bukan di salinan.

**Celah yang sengaja dibiarkan.** `skip iklannya` diakui tier sebagai aksi
media, tetapi `user_browser_media` hanya punya pause/play/toggle/mute/unmute.
Mengarang aksi "skip" berarti menjalankan sesuatu yang tidak ada, jadi
jembatannya mengembalikan `None` dan perintahnya tetap ke model. Ada ujinya
supaya ini terbaca sebagai keputusan, bukan kelalaian.

**Bukti:** `focused-tested` + `runtime-wired` — 21 uji di
`tests/test_deterministic_bridge.py`, 2574 lulus seluruh suite, ruff bersih,
FROZEN utuh. **Belum `live-proven`:** `user_browser_media` butuh Chrome yang
dijalankan dengan `--remote-debugging-port=9222`; tanpa itu tool-nya melapor
"tidak terjangkau" — dan sejak Fase 23 itu memang dibedakan dari "tidak ada
video", yang diuji ulang di sini.

---

## Fase 32 — WebEngine diimpor sebelum `QApplication` (T4)

Direproduksi di dua proses bersih: sebelum `QApplication` dibuat, cek
mengembalikan `QtWebEngine ready`; sesudahnya `system browser ready; no embed
driver`. Boot memeriksanya sesudah, jadi driver embed benar-benar tidak
tersedia — bukan salah deteksi.

`QApplication` lahir di jalur UI dan `main.py`/`ui.py` FROZEN, jadi ini harus
lewat seam.

### Hasil Fase 32 — SELESAI 2026-08-08

**T4 ternyata jauh lebih besar daripada satu baris status.** Qt sendiri
menyebutkan sebabnya, dan pesannya sekaligus perbaikannya:

```
QtWebEngineWidgets must be imported or Qt.AA_ShareOpenGLContexts must be set
before a QCoreApplication instance is created
```

`jarvis/browser/agent_view.py` dan `jarvis/browser/embed.py` mengimpor
`QWebEngineView` secara **lazy** — yaitu sesudah `QApplication` ada — sehingga
importnya SELALU gagal di aplikasi yang berjalan. Jadi browser agent tertanam
tidak pernah bisa hidup, dan satu-satunya jejaknya adalah `DEGRADED` yang
terbaca seperti hal sepele. Kelas bug yang sama dengan insiden utama dokumen
ini: fitur mati tanpa mengeluarkan suara.

**Perbaikan yang TIDAK diambil, dan kenapa.** Mengimpor WebEngine lebih awal
akan menyelesaikannya — dan melanggar MK50 §7 yang sengaja membuang QtWebEngine
dari jalur boot, lengkap dengan `tests/test_phase5_stage_home.py` yang
menjaganya. Itu berarti memuat Chromium ~100 MB pada setiap boot demi fitur
yang jarang dipakai. Yang dipasang justru hanya **atributnya**:
`jarvis/ui/qt_webengine.enable_shared_gl()`, dipanggil satu baris sebelum
`QApplication` dibuat di `jarvis/ui/window.py`. Ada uji yang membuktikan tidak
satu pun modul WebEngine ikut termuat.

| | sebelum | sesudah |
|---|---|---|
| `_check_browser` di urutan nyata | `DEGRADED — no embed driver` | `QtWegEngine ready` |
| import lazy `QWebEngineView` | selalu `ImportError` | berhasil |
| modul Chromium termuat saat boot | 0 | 0 |

**Dan bila terlambat, ia mengatakannya.** `enable_shared_gl()` mengembalikan
`False` bila `QApplication` sudah ada, dengan log yang menyebut akibatnya —
mengembalikan `True` di situ berarti berbohong tentang keadaan yang sudah
tidak bisa diubah.

**Bukti:** `focused-tested` + `runtime-wired` — 8 uji di
`tests/test_webengine_boot_order.py`, semuanya menjalankan proses bersih agar
yang diukur adalah urutan yang sungguhan, bukan proses kosong. 2583 lulus
seluruh suite, ruff bersih, FROZEN utuh. **Belum `live-proven`:** browser agent
tertanam sendiri belum dicoba Takeda setelah perbaikan ini.

---

## Fase 33 — Memori semantik: hidup, atau mati dengan jujur (T5)

`memory.faiss_missing` muncul tiap boot dan `faiss-cpu` tidak terdaftar di
extra mana pun — hanya di komentar `pyproject.toml`. Satu fitur mati
diam-diam, kelas yang sama dengan insiden utama dokumen ini.

Dua jalan sah: pasang dependensinya, atau nyatakan matinya di tempat yang
Takeda benar-benar lihat. Yang tidak sah adalah keadaan sekarang: mati, tetapi
hanya sebaris peringatan di log yang tidak ada yang baca.

### Hasil Fase 33 — SELESAI 2026-08-08

**Pengukuran membantah separuh temuan T5.** Ada DUA penyimpanan memori, dan
peringatannya bicara tentang yang salah:

| store | pakai FAISS? | keadaan nyata |
|---|---|---|
| `jarvis/agent/memory_store.py` (dipakai agent) | tidak — SQLite + cosine | **298/298 baris punya embedding** |
| `jarvis/core/memory.py` (indeks lama) | ya | `data/memory.faiss` tidak pernah ada |

Jadi Jarvis berkata *"Semantic memory disabled"* setiap boot sementara memori
semantik yang benar-benar dipakainya hidup sepenuhnya. Itu **kegagalan palsu**
— kelas kesalahan yang sama dengan klaim palsu yang diberantas Siklus 2, hanya
arahnya terbalik. FAISS tidak dipasang: yang salah pesannya, bukan
dependensinya.

Yang dikerjakan:

* Pesannya kini menyebut persis apa yang mati dan apa yang tidak, sebagai
  konstanta `FAISS_MISSING_DETAIL` supaya bisa diuji tanpa menebak teks
  sumber. Tingkatnya turun dari `warning` ke `info` — ini memang bukan
  peringatan.
* `core.memory` menjadi subsistem boot, sehingga keadaannya muncul di deret
  status yang sama dengan `core.llm`/`core.vision`. Satu baris di log 41 MB
  bukan "terlihat". Dijalankan sungguhan sekarang:
  `core.memory ONLINE — 298/298 memori punya embedding`.
* Empat keadaan dibedakan: kosong (bukan rusak), sebagian punya embedding
  (degraded), nol embedding (degraded, pencarian jatuh ke teks), dan tidak
  bisa dibaca (**failed** — tidak bisa dibaca bukan sama dengan kosong).

**Satu pelajaran metode.** Tiga uji pertamaku memeriksa TEKS SUMBER, dan
langsung terpicu oleh komentarku sendiri yang mengutip kalimat lama. Uji
semacam itu lemah dua arah: ia gagal karena hal yang benar, dan ia akan lulus
untuk kode yang salah asal kata-katanya cocok. Diganti menjadi uji perilaku —
konstanta pesannya, dan `_memory_counts` dijalankan terhadap basis data
sungguhan.

**Bukti:** `focused-tested` + `runtime-wired` — 10 uji di
`tests/test_memory_visibility.py`, 2593 lulus seluruh suite, ruff bersih,
FROZEN utuh.

---

## Fase 34 — Tunggu keadaan, bukan tidur tetap (T8)

`test_play_audio_mengeluarkan_semua_chunk_dan_drain` menunggu
`asyncio.sleep(0.15)` dengan `tail_grace_s=0.02`. Di mesin yang sedang
terbebani suite penuh, 0,15 detik bisa tidak cukup.

Menaikkan angka tidurnya hanya menggeser ambangnya. Yang benar adalah menunggu
KEADAAN yang ditunggu, dengan batas waktu longgar.

### Hasil Fase 34 — SELESAI 2026-08-08

`_wait_until(predicate, timeout_s=10)` menggantikan `asyncio.sleep(0.15)`.
Yang ditunggu adalah giliran benar-benar ditutup (`live.speaking[-1] is
False`), bukan berlalunya waktu. Batas waktunya longgar dengan sengaja: uji
ini memeriksa bahwa ekor audionya tidak hilang, **bukan** seberapa cepat
mesinnya.

Dan bila batas itu benar-benar habis, uji gagal dengan kalimat yang
membedakannya dari mesin yang lambat — sebuah `assert` terpisah sebelum
`task.cancel()`. Tanpa itu, kehabisan waktu akan lolos diam-diam sebagai
"lulus", yang justru mengubah tes rapuh menjadi tes buta.

Menunggu keadaan juga membuatnya **lebih cepat**, bukan lebih lambat: berkas
ini kini selesai ~0,38 detik, karena tidak ada lagi yang menunggu 0,15 detik
penuh setelah pekerjaannya sudah selesai. 5 ulangan berturut-turut lulus,
ditambah suite penuh.

**Bukti:** 2593 lulus seluruh suite, ruff bersih, FROZEN utuh. **Batas
jujurnya:** kegagalan aslinya muncul SATU kali di bawah beban, jadi tidak ada
jumlah ulangan yang bisa membuktikan ia hilang selamanya. Yang bisa
dinyatakan: penyebabnya — tenggat waktu tetap — sudah tidak ada lagi di kode.

---
