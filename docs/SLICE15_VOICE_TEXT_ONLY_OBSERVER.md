# Fase 35 special slice — voice text-only observer

**Baseline:** `1a48c0a`
**Branch:** `fase13-kejujuran-panggilan`
**Scope:** one excluded-category diagnostic block; bounded offline migration

## Verdict

Slice ini memindahkan satu raw S110 dari kategori voice yang sebelumnya
dikecualikan: kegagalan penulisan diagnostic text-only ke UI pada
`jarvis/integrations/voice_text_only_observer.py`, function `observe`.

Block tersebut tetap fail-open. Perubahan hanya menambahkan warning terstruktur
dengan event stabil `voice.text_only.write_failed` dan exception type bounded.
Observer tetap mengembalikan `None`; tidak ada audio, voice session, hardware,
atau Gemini Live yang dibuat oleh test maupun verification offline.

Ini **bukan** clearance untuk seluruh kategori voice atau excluded debt lain.
Raw S110/S112 masih tersisa dan Fase 35 tetap **SEBAGIAN**.

## Boundary selection

Target memenuhi seluruh boundary slice:

- tracked-clean dan non-FROZEN pada preflight;
- `live` merupakan parameter injected sehingga fake lokal dapat menjalankan
  exception path tanpa sesi eksternal;
- `_logger` sudah dimiliki module sehingga tidak ada import/provider/config baru;
- kegagalan UI log sengaja ditelan dan tidak mengubah callback order, retry,
  ownership, lifecycle, fallback, atau return value;
- disabled observer, audio-present turn, dan empty text tetap no-op.

Kandidat lain tetap ditolak: Telegram/cron delivery dan lifecycle, Hermes
callback/subprocess, UI adapter callback ownership, YouTube OAuth/keyring,
dan voice notice requeue. Jalur tersebut memerlukan boundary delivery,
credential, subprocess, GUI, network, atau lifecycle yang tidak dapat dibuktikan
secara aman dalam offline slice ini.

Proposal dari isolated snapshot yang tidak ada dalam parent raw inventory tidak
digunakan.

## RED/GREEN characterization

Test baru:

`tests/test_voice_text_only_observer_quiet.py`

RED dijalankan sebelum source migration dan gagal hanya pada assertion bahwa
`voice.text_only.write_failed` belum tercatat. Tidak ada import, fixture, Qt,
provider, network, credential, audio, camera, hardware, atau live failure.

GREEN focused run mencakup test baru, observer tests, voice L1 hook, dan voice
routing integration:

```text
39 passed in 3.89s
```

Test merekam hanya event dan fields bounded; exception text privat tidak masuk
assertion atau output. Test juga memastikan return tetap `None`.

## Verification evidence

Raw isolated command:

```text
ruff check --select S110,S112 --isolated --no-cache --output-format json .
```

Preflight:

```text
142 matches / 43 files / 119 S110 / 23 S112
```

Post-migration aktual:

```text
141 matches / 42 files / 118 S110 / 23 S112
```

Raw Ruff exit tetap nonzero karena debt lain masih ada; ini bukan green.
Target `voice_text_only_observer.py` tidak lagi muncul pada raw inventory.

Other gates:

```text
Configured Ruff: All checks passed!
IMPORT_SMOKE=ok jarvis.integrations.voice_text_only_observer
FROZEN integrity: OK (10 files, baseline 094b696)
git diff --check: passed
```

Full offline pytest dijalankan dengan `PYTHONDONTWRITEBYTECODE=1`,
`-p no:cacheprovider`, dan unique `--basetemp` di luar repository. Hasil aktual:

```text
3137 passed, 1 skipped, 1 warning in 227.96s (0:03:47)
```

Satu skip berasal dari privilege symlink Windows pada
`tests/test_file_sandbox_boundary.py`; warning adalah
`StarletteDeprecationWarning` dari dependency FastAPI yang terpasang. Tidak ada
failure pada suite offline.

Tidak ada provider, browser, network, credential/keyring, microphone, speaker,
audio session, camera, hardware, Telegram, WhatsApp, dashboard, atau Gemini
Live yang diakses.

## Evidence and status (actual offline run)

Bukti slice dibatasi pada `source-present` dan `focused-tested` untuk perubahan
ini, serta gate offline yang benar-benar dijalankan. Existing turn-boundary
wiring tetap ada, tetapi slice tidak mengklaim `live-proven`; tidak ada sesi
Gemini Live nyata. `runtime-wired` tidak digunakan sebagai klaim baru.

Fase 35 tetap **SEBAGIAN**: 141 raw S110/S112 findings masih tersisa. Satu
successful diagnostic carve-out bukan bukti semua raw debt atau kategori voice
sudah aman.
