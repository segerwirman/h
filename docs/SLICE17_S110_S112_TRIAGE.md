# Fase 35 Slice 17 — audit raw S110/S112 inventory

**Baseline:** `e7b3b17`
**Branch:** `fase13-kejujuran-panggilan`
**Scope:** targeted raw inventory; audit-only, zero runtime migration

## Verdict

Slice 17 menjalankan ulang authoritative raw inventory dan menilai hanya finding yang
benar-benar muncul pada parent checkout saat ini. Hasilnya tetap:

```text
RAW_EXIT=1
RAW_MATCHES=141 FILES=42 S110=118 S112=23
```

Tidak ada source block yang lolos seluruh boundary Slice 17. Dengan demikian slice ini
**audit-only**: tidak ada perubahan source, tidak ada test RED artifisial, dan tidak ada
instrumentasi baru. Raw Ruff tetap nonzero karena 141 finding masih ada; angka tersebut
bukan status green dan Fase 35 tetap **SEBAGIAN**.

## Measurement and preflight

Perintah authoritative yang digunakan:

```text
ruff check --select S110,S112 --isolated --no-cache --output-format json .
```

Output JSON dihitung sebagai satu array penuh dengan parser JSON, sehingga jumlah match,
file, dan rule tidak terdistorsi oleh PowerShell array unrolling. Exit `1` diperlakukan
sebagai hasil yang diharapkan selama debt masih tersisa.

Target-scoped checks yang diverifikasi:

```text
ruff check --select S110,S112 --isolated --no-cache --output-format json actions/code_helper.py
TARGET_EXIT=1 TARGET_MATCHES=2
S110 actions/code_helper.py:490
S110 actions/code_helper.py:509

ruff check --select S110,S112 --isolated --no-cache --output-format json jarvis/nlp/predictive.py
PREDICTIVE_EXIT=0 PREDICTIVE_MATCHES=0
```

Preflight parent juga menghasilkan:

```text
HEAD=e7b3b17
BRANCH=fase13-kejujuran-panggilan
FROZEN integrity: OK (10 files, baseline 094b696)
IMPORT_SMOKE=ok actions.code_helper jarvis.nlp.predictive
```

`ruff check .` configured gate lulus. `git diff --check` tetap menjadi gate wajib setelah
artifact dibuat. Working tree user-dirty dan preserved untracked paths tidak menjadi bagian
dari slice dan tidak boleh diubah.

## Candidate review

### Rejected: `actions/code_helper.py` (2 raw S110)

Kedua finding berada di `_screen_debug_action` dan menelan kegagalan cleanup:

- sekitar baris 488–491: `screenshot_path.unlink()` setelah analisis Gemini berhasil;
- sekitar baris 507–510: `screenshot_path.unlink()` di handler exception analisis.

Operasinya memang local `Path.unlink`, tetapi tidak dapat dipisahkan secara aman dari
boundary yang mengelilinginya:

- function membuat screenshot melalui `pyautogui` dan memiliki ownership atas Desktop temp
  artifact;
- success cleanup berada di dalam provider/screen-analysis `try`; telemetry yang gagal
  dapat mengubah return analysis menjadi `Screen analysis failed` dan melewati fixed-code
  save;
- failure cleanup berada langsung di provider/network/credential exception path; telemetry
  yang gagal dapat keluar dari function dan mengganti fallback string menjadi exception;
- cleanup ordering, artifact ownership, fail-open return value, dan lifecycle exception
  behavior harus tetap utuh.

Menambah logger baru atau mengganti `pass` tanpa characterization tidak memenuhi boundary.
Karena itu dua finding ini dicatat sebagai `source-present`, tetapi ditolak untuk migrasi
Slice 17. Jika kelak diperlukan, keduanya memerlukan slice screen-debug temp-file lifecycle
tersendiri dengan test dan verifikasi boundary yang khusus.

### Rejected: `actions/system_monitor.py`

Finding S112 pada loop NVML candidate loading (`_load`/`nvmlInit_v2`) menyentuh DLL/GPU
hardware availability. Offline slice tidak boleh memaksa loading atau menginstrumentasi
hardware discovery.

### Rejected: `jarvis/vision/process.py`

Finding S110 berada pada camera worker, pyautogui cursor control, multiprocessing queues,
worker stop, dan lifecycle paths. Instrumentasi dapat mengubah ownership, queue delivery,
callback ordering, atau shutdown behavior; seluruh file ditolak untuk slice ini.

### Rejected: remaining raw inventory

Finding lain berada pada satu atau lebih boundary provider/auth/keyring, browser/network,
remote delivery (Telegram/WhatsApp/Hermes/dashboard), audio/voice ownership, camera or
hardware, GUI/desktop automation, subprocess/OS control, scheduler/callback/lifecycle,
FROZEN/protected files, atau preservation boundary user-dirty. Tidak ada finding tambahan
yang dapat dipilih hanya untuk mengisi kuota maksimum lima.

### Not a raw candidate: `jarvis/nlp/predictive.py::_save`

`PredictiveText._save` masih memiliki fallback `except OSError: pass`, tetapi target-scoped
isolated Ruff menghasilkan `PREDICTIVE_MATCHES=0`. Slice 17 sengaja tidak mengulang
instrumentasi Type-A yang tidak muncul pada raw matcher.

## RED-first decision

Tidak ada migration target yang memenuhi boundary, sehingga RED-first source migration tidak
dijalankan. Membuat test yang mengharapkan event baru untuk block yang sengaja ditolak akan
menjadi RED artifisial dan dapat mendorong perubahan behavior pada provider, GUI, hardware,
atau lifecycle path. Tidak ada source/test migration pada slice ini.

## Verification evidence

Evidence untuk audit ini dibatasi pada hasil yang benar-benar diperoleh secara offline:

- `source-present`: 141 raw findings, termasuk dua target `code_helper.py` dan rejected
  hardware/camera/process examples;
- `configured`: `ruff check .` lulus;
- import smoke lulus untuk `actions.code_helper` dan `jarvis.nlp.predictive`;
- FROZEN integrity lulus untuk 10 file dengan baseline `094b696`;
- focused-tested: `tests/test_quiet.py` dan `tests/test_slice13_quiet.py` menghasilkan
  `25 passed in 0.95s`;
- full offline pytest: `3137 passed, 1 skipped, 1 warning in 220.00s`;
- `git diff --check` lulus setelah artifact dibuat; preservation status tetap berisi
  hanya artifact baru di samping perubahan lokal pengguna yang sudah ada.

Full pytest warning/skip aktual: satu symlink test skip karena privilege Windows pada
`tests/test_file_sandbox_boundary.py`; satu `StarletteDeprecationWarning` berasal dari
installed FastAPI/Starlette test dependency. Tidak ada test failure.

Perintah test yang dipakai tetap offline:

```text
PYTHONDONTWRITEBYTECODE=1 .venv\\Scripts\\python.exe -m pytest \\
  -p no:cacheprovider --basetemp="$TEMP/jarvis-slice17-focused" \\
  tests/test_quiet.py tests/test_slice13_quiet.py

PYTHONDONTWRITEBYTECODE=1 .venv\\Scripts\\python.exe -m pytest \\
  -p no:cacheprovider --basetemp="$TEMP/jarvis-slice17-full"
```

Tidak ada provider, browser, network, credential/keyring, audio, camera, hardware, atau
Gemini Live yang diakses selama verification.

Semua test/verification Slice 17 wajib memakai `PYTHONDONTWRITEBYTECODE=1`, pytest
`-p no:cacheprovider`, dan `--basetemp` di luar repository. Tidak ada provider, browser,
network, credential/keyring, microphone, speaker, audio session, camera, hardware, GUI,
subprocess eksternal, Telegram, WhatsApp, dashboard, atau Gemini Live yang diakses.

Tidak ada klaim baru `runtime-wired`, `fixture-accepted`, atau `live-proven`. Tidak ada sesi
Gemini Live nyata pada slice ini.

## Status fase

Slice 17 menghasilkan audit artifact tanpa source migration. Raw inventory tetap:

```text
141 matches / 42 files / 118 S110 / 23 S112
```

Fase 35 tetap **SEBAGIAN**. Zero qualifying migration candidate bukan bukti bahwa seluruh
raw S110/S112 debt sudah aman atau selesai; ia hanya membatasi pekerjaan pada evidence dan
boundary yang dapat dibuktikan offline.
