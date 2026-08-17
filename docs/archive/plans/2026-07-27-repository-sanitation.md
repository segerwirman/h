# DELETION_PLAN — Sanitasi Repo

Berbasis temuan terverifikasi di [`AUDIT_FINDINGS_CODE.md`](../../AUDIT_FINDINGS_CODE.md),
bukan asumsi. Setiap baris di tabel AMAN HAPUS punya bukti nol-pemanggil yang
sudah disilangkan dengan **keempat mekanisme pemuatan dinamis** di repo ini.

| | |
|---|---|
| **Tanggal** | 2026-07-27 |
| **Baseline** | `859 passed` · `FROZEN integrity: OK (10 files)` |
| **Aturan** | Tidak ada berkas FROZEN yang disentuh. Tidak ada penghapusan tanpa bukti. |

---

## ⚠️ Verifikasi yang mengoreksi instruksi awal

Tiga hal ditemukan saat verifikasi dan **mengubah rencana**:

1. **`AUDIT_REPORT.md` di root BUKAN audit lama.** Tidak ada versi lama yang
   tersisa — `AUDIT_REPORT.md:7` menyatakan dirinya *"menggantikan"* audit
   2026-07-17, dan `AUDIT_REPORT.md:15` menandainya REVISI 2. Memindahkannya ke
   `docs/history/AUDIT_2026-07-17.md` akan **mengarsipkan audit yang aktif dengan
   tanggal yang salah**. → **TIDAK DIPINDAHKAN.**
2. **M-3 (README menyesatkan) sudah selesai.** `readme.md` sudah berisi README
   MK50 Hybrid yang baru; tidak ada lagi instruksi `git clone …FatihMakes…`.
   Yang tersisa hanya kapitalisasi nama berkas.
3. **Regex verifikasi path absolut di instruksi tidak berfungsi** — mengembalikan
   nol hasil karena escaping. Setelah diperbaiki, ditemukan 5 lokasi nyata
   (lihat §4).

---

## 1. 🗑️ AMAN HAPUS

Semua sudah diverifikasi: nol pemanggil di kode, tes, config, dan keempat
mekanisme dinamis (`pkgutil` auto-discovery, `__import__` tabel NLP,
`__import__` provider, `importlib.util.find_spec`).

### 1a. Disetujui eksplisit — dieksekusi

| Berkas | Baris | Status git | Bukti nol-pemanggil | Risiko |
|---|---:|---|---|---|
| `mw.txt` | 750 | ter-track | `rg "mw\.txt"` → nol hit kode. Bukan modul Python; salinan mentah `class MainWindow` yang akan terus menyimpang dari `ui.py` | **Nol** |
| `patch_ui.py` | 88 | ter-track | `rg "patch_ui"` → nol hit kode (hanya `MIGRATION_NOTES.md:1404` sebagai catatan sejarah). Menulis ke **path di luar pohon**: `patch_ui.py:4` `ui_file = r"e:\Jarvis\mark48\Mark-XLVIII-main\ui.py"` | **Negatif** — menghapusnya *menghilangkan* risiko |

### 1b. Terverifikasi aman, **menunggu konfirmasi user** — belum dieksekusi

Ini di luar daftar eksplisit instruksi. Bukti sudah lengkap, tetapi penghapusan
tidak dilakukan tanpa persetujuan.

| Berkas | Baris | Status git | Bukti nol-pemanggil |
|---|---:|---|---|
| `core/llm_client.py` | 586 | ter-track | Relik **"MARK XL"** (`:2`). Semua hit `llm_client` di repo menunjuk `jarvis/agent/llm_client.py` — berkas **berbeda dan hidup**. Nol importer untuk yang di `core/` |
| `core/installer.py` | 138 | ter-track | Relik **"MARK XL"** (`:2`). Rujukan hanya di `Tutorial.MD:77,579` (dokumen, sedang dipindah). Nol importer |
| `scripts/verify_hermes.py` | 102 | ter-track | Nol importer. `tests/test_hermes_integration.py:5` menyebutnya **hanya di docstring modul** (baris 5, sebelum blok `import` di baris 7) — tidak diimpor, tidak dieksekusi. Juga **satu-satunya pemanggil `HermesBridge.get()` tanpa penjaga flag** (`:28`) → menghapusnya mengurangi risiko |
| `actions/youtube_video.py.bak` | 680 | ter-track | `.bak` — tak bisa diimpor Python |
| `jarvis/agent/tools/google_youtube.py.bak` | 202 | ter-track | `.bak` di dalam folder auto-discovery. `pkgutil.iter_modules` **hanya menghasilkan `.py`** → tidak dimuat. Tapi membayangi nama modul hidup di setiap grep/IDE |
| `create_jarvis_profile.py.bak` | 98 | **untracked** | Sintaks **rusak** di `:50` (`"profile_color_seed": 680Kilau,`) — akan `SyntaxError` bila diimpor |

**Total 1b: 1.806 baris.**

### 1c. Kode mati **di dalam berkas hidup** — jangan hapus berkasnya

| Lokasi | Temuan |
|---|---|
| `actions/screen_processor.py:397` `screen_process()`, `:445` `warmup_session()`, `:208` `class _VisionSession` | Tak terjangkau di produksi — `main.py:870` mengimplementasikan ulang tool itu **inline**, dan `main.py:50` hanya mengimpor `_capture_camera, _capture_screen`. Pemanggil satu-satunya adalah blok `__main__` modul itu sendiri (`:458`, `:462`) |
| `dashboard/server.py:103-311` `_ensure_network_access()` | Kode mati (nol pemanggil) yang **meminta elevasi UAC** dan **mereklasifikasi Public→Private** se-host. Sudah sengaja diputus (`jarvis/core/dashboard_security.py` mengunci `needs_firewall=False`) |

Keduanya perlu penghapusan **di dalam berkas**, bukan penghapusan berkas —
ditunda ke fase perbaikan, bukan fase sanitasi.

---

## 2. 📦 PINDAHKAN — tidak dihapus

| Dari | Ke | Alasan |
|---|---|---|
| `JARVIS_HERMES_PARITY_v2.md` (841) | `docs/history/HERMES_PARITY_v2.md` | Merujuk `hermes-agent-main/` yang gitignored — historis, bukan operasional |
| `jarvis.md` (353) | `docs/history/SPEC_MK50.md` | Spesifikasi asal MK50 |
| `MARK-XLIX.md` (104) | `docs/MARK-XLIX.md` | Masih berguna (hotkey, gestur, catatan arsitektur) |
| `MIGRATION_NOTES.md` (1483) | `docs/MIGRATION_NOTES.md` | Log kerja aktif |
| `Tutorial.MD` (672) | `docs/TUTORIAL.md` | **Sekalian perbaiki `.MD` → `.md`** — menggigit di filesystem case-sensitive (Linux/CI) |

### Tidak dipindahkan — dengan alasan

| Berkas | Keputusan |
|---|---|
| **`AUDIT_REPORT.md`** (1343) | **TETAP DI ROOT.** Ini audit **aktif** (REVISI 2), bukan yang lama. Lihat §Verifikasi di atas |
| `readme.md` (646) | **TETAP DI ROOT** — hanya kapitalisasi yang perlu diperbaiki (`readme.md` → `README.md`) |
| `JARVIS_MK50_MASTER_SPEC.md` (758) | ⚠️ **BUTUH KEPUTUSAN USER.** Tidak ada di daftar instruksi. Masih **dirujuk aktif** oleh `MIGRATION_NOTES.md` dan `docs/JARVIS_CONVERSATION_ACCEPTANCE.md`, jadi memindahkannya akan memutus dua tautan |
| `JARVIS_CHROME_PROFILE.md` (19) | Untracked, dokumentasi operator untuk `create_jarvis_profile.py`. Biarkan sampai nasib skripnya diputuskan |

---

## 3. ✋ TAHAN DULU — punya pemanggil

| Target | Blokir oleh | Bukti |
|---|---|---|
| **`core/social_manager.py`, `core/social_ui.py`** | `ui.py:19-20` — **bukan** hanya `patch_ui.py` | `ui.py:19 from core.social_manager import SocialManager`; `ui.py:1362` menginstansiasinya; `ui.py:1363 self.social_manager.start_polling()`. `ui.py` hidup lewat `main.py:38`, dan **keduanya FROZEN**. Menghapus → `ImportError` di jalur suara produksi. **Klaim `AUDIT_REPORT.md §7.3` lama SALAH** |
| `core/reactor.py`, `core/camera_vision.py`, `core/voice_listener.py`, `core/settings_ui.py` | idem `ui.py:16-21` | Rantai proteksi yang sama |
| `core/stt.py` | `jarvis/agent/adapters/jarvis_voice.py:40` | Dipakai transkripsi voice-note Telegram. Juga **FROZEN** |
| **13 modul `jarvis/agent/tools/`** | Auto-discovery `pkgutil` | `jarvis/agent/registry.py:42-47`. `clarify.py`, `code_exec.py`, `cron_tools.py`, `file_ops.py`, `food.py`, `google_drive.py`, `session_tools.py`, `spotify.py`, `todo.py`, `vision.py` punya **nol referensi impor** tapi semuanya **hidup**. Menghapus salah satunya menghilangkan kapabilitas **tanpa `ImportError` sebagai peringatan** |
| **19 dari 20 modul `actions/`** | `main.py:43-61` + **MK50 sendiri** | `jarvis/agent/adapters/telegram_light.py:38,89`; `jarvis/ui/window.py:587,808,855`. Delapan modul **tanpa padanan MK50** — menghapus = kehilangan kapabilitas |
| `actions/hermes_action.py` | 4 referensi tes | `tests/test_hermes_disabled.py:4`, `tests/test_hermes_integration.py:199,212,233`. Satu-satunya modul `actions/` yang inert secara desain (`:48`), tapi tesnya harus ikut dihapus |
| `jarvis/integrations/hermes/**` | 4 penghambat | (B1) `jarvis/core/router.py` masih memproduksi `Intent.HERMES_TASK` dan `window.py:721-725` masih men-dispatch-nya ke jalur **Telegram native yang hidup**; (B2) `boot.py:149`; (B3) 67 asersi tes; (B4) `panels.py:1024` `MessagingPanel` |
| `jarvis/nlp/agent.py` (`HermesAgent`) | **Diinstansiasi tiap boot** | `jarvis/main.py:86-88` → `jarvis/nlp/assistant.py:40,51`. Nama-nya saja yang legacy — isinya orkestrator ReAct mandiri, tak menyentuh bridge |
| `qt.conf` | Konvensi Qt | Dimuat **berdasarkan nama berkas**, bukan impor. Ketiadaan referensi **tidak membuktikan apa pun**. Butuh uji DPI manual |
| `jarvis/core/notify_hub.py` (191) | Keputusan produk | Nol referensi, tapi docstring `:1` menyebut *"NotificationHub (Mark L Change 1)"* — fitur **dibangun tapi belum disambung** |
| `jarvis/integrations/youtube_capability.py` (111) | Keputusan produk | Nol referensi, tapi isinya **invarian keamanan** (API key ≠ izin posting). Menghapus membuang penjaga |
| 17 modul "matang tapi belum tersambung" | Importer tunggal = tes | `plugins/*`, `gateway/platforms/*`, `runtime/evaluation.py` (punya runbook di `docs/EVALUATION_RUNBOOK.md`), dll. **Jangan hapus massal** |

---

## 4. Hasil verifikasi lain

### Path absolut hardcoded
Regex di instruksi awal **tidak berfungsi** (nol hasil karena escaping). Setelah
diperbaiki:

| Lokasi | Sifat |
|---|---|
| `patch_ui.py:4` | **Satu-satunya penulisan ke mesin lain** → dihapus di §1a |
| `actions/dev_agent.py:317` | `rf"C:\Users\{Path.home().name}\..."` — merekonstruksi home dari `.name` alih-alih `Path.home()`. Patah pada profil yang diganti nama/akun domain |
| `actions/dev_agent.py:318` | Fallback VS Code Windows; loop `continue` — tidak fatal |
| `ui.py:106`, `actions/system_monitor.py:39` | Probe NVML Windows, berpenjaga `try/except` — portabilitas saja |

### Rahasia di berkas ter-track
Dua hit, **keduanya nilai dummy di tes** — bukan kredensial:
`tests/test_providers.py:84` (`sk-super-rahasia`) dan
`tests/test_phase6_secrets_oauth.py:26`. Seluruh berkas kredensial nyata
(`config/api_keys.json`, `config/providers.json`, `config/youtube_oauth.json`,
`memory/long_term.json`, `.env`) dikonfirmasi **tidak ter-track**.

### Tool duplikat berdasarkan nama berkas
`comm -12` → **nol**. Tumpang tindih `actions/` ↔ `jarvis/agent/tools/` bersifat
**kapabilitas**, bukan nama berkas — jadi perintah `comm` di instruksi tidak bisa
mendeteksinya. Pemetaan sebenarnya (2 SAMA / 10 PARSIAL / 8 tanpa padanan) ada di
`AUDIT_FINDINGS_CODE.md` §1c.

### Jalur Hermes
302 baris cocok di 36 berkas, tetapi `main.py` dan `ui.py` root: **nol**. Gerbang
flag lengkap dan gagal-tertutup (`bridge.py:35-42` memakai `is True`). Detail dan
urutan pensiun bertahap: `AUDIT_FINDINGS_CODE.md` §5.

---

## 5. Status eksekusi

Semua di branch `chore/repo-sanitation`, satu commit per langkah.

| Langkah | Status | Commit |
|---|---|---|
| 1. Verifikasi | ✅ baseline `859 passed`, FROZEN OK | — |
| 2. `DELETION_PLAN.md` | ✅ dokumen ini | `928b59e` |
| 3. Hapus §1a + pindahkan §2 | ✅ | `928b59e` |
| §1b — 6 berkas, 1.806 baris | ✅ disetujui & dieksekusi | `d7084a1` |
| 4. Field rahasia `config.yaml` | ✅ dihapus, didokumentasikan sbg env | `96fc4ac` |
| 5. Rename `setup.py` + perbaiki isi | ✅ | `d96ca9c` |
| 6. `pyproject.toml` + extras | ✅ | `98be3e7` |
| 7. `.github/workflows/ci.yml` | ✅ | `1db42d2` |

**Verifikasi setelah setiap langkah:** `859 passed` (nol regresi di seluruh
tujuh langkah) · `python -m jarvis.main --no-voice` boot normal ·
`FROZEN integrity: OK (10 files)`.

### Sisa yang belum dikerjakan — sengaja

| Item | Alasan |
|---|---|
| `JARVIS_MK50_MASTER_SPEC.md` (758) | Butuh keputusan user — masih dirujuk aktif oleh `docs/MIGRATION_NOTES.md` dan `docs/JARVIS_CONVERSATION_ACCEPTANCE.md` |
| `readme.md` → `README.md` | Hanya kapitalisasi; isinya sudah benar (M-3 selesai). Rename case-only di Windows perlu dua langkah — belum dilakukan agar tidak mengacaukan riwayat tanpa diminta |
| `log_tail.txt` | Berkas nyasar di root, belum diverifikasi asalnya |
| `requirements.txt`, `requirements-xlix.txt` | **Sengaja dipertahankan** sampai user mengonfirmasi instalasi bersih dari `pyproject.toml` berhasil |
| 6 pelanggaran lint di kode warisan | Didaftarkan di `pyproject.toml` `per-file-ignores` dengan alasan per berkas — bukan disembunyikan. Perbaikannya menyentuh perilaku (`except:` → `except Exception:`) di berkas di luar lingkup sanitasi |
| Kode mati §1c | `actions/screen_processor.py` (3 simbol) dan `dashboard/server.py:103-311` — penghapusan **di dalam** berkas, masuk fase perbaikan |
