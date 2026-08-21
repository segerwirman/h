# P8E — Voice Behavior Fix: Narasi Diam + Headroom Iterasi

**Status:** ✅ Implemented, committed `c57c923`
**Date:** 2026-08-22
**Type:** Perubahan perilaku agent (config + satu wiring adapter), diverifikasi offline

---

## Executive Summary

Tiga keluhan perilaku suara ditangani dalam satu lingkup terotorisasi:

1. **Narasi progres dibisukan** — JARVIS tidak lagi menyela dengan frasa progres ("Mengecek ingatan saya.", "Membaca berkasnya.") saat bekerja tanpa perintah bicara. Log panel tetap jalan (visual-only).
2. **Headroom iterasi dinaikkan** — 20 → 30, agar tugas kompleks tidak terpotong dinding iterasi (log menunjukkan run mencapai 16–17 dari 20).
3. **Eskalasi interaktif dimatikan** — pertanyaan "Lanjutkan/Hentikan?" di ambang 80% batas dinonaktifkan; JARVIS hanya bicara bila merespons perintah.

Jawaban terhadap perintah (ACK, konfirmasi, hasil akhir) **sengaja tidak disentuh** — yang dimatikan hanya interjensi tanpa perintah.

---

## Keluhan User dan Pemetaan Akar Masalah

Laporan user (2026-08-22): *"output suara jarvis masih terasa kaku ketika mengecek ingatannya, batas iterasi masih menghalangi jarvis menyelesaikan satu tugas. saya tidak ingin jarvis berbicara saat sedang tidak ada perintah, saya ingin jarvis hanya merespon ketika ada perintah."*

| Keluhan | Akar masalah | Solusi di lingkup ini |
|---------|--------------|----------------------|
| Interjensi saat cek ingatan | `ProgressNarrator` mengucapkan frasa tool (max 4/tugas, jeda 12 s) | `agent.interaction.speaker_enabled: false` → `max_spoken=0` |
| Batas iterasi menghalangi | `agent.max_iterations` = 20; log: distribusi run memuncak mendekati 20 | Dinaikkan ke 30 (kedua kunci tetap sama, aturan kejujuran §17) |
| Pertanyaan eskalasi di tengah tugas | `_iteration_escalation()` bertanya pada adapter interaktif di 80% batas | `agent.iteration_escalation.enabled: false` |
| "Suara kaku" (kualitas) | Semua ucapan dirutekan lewat jalur suara live (`on_speech_command` / pembungkus `on_text_command` di `window_voice.py:_speak_now`) | **Tidak diubah** — wilayah audio/voice live; di luar otorisasi offline. Efek samping positif: interjensi kaku hilang total karena narasi dibisukan |

Catatan jujur: label bukti untuk perubahan ini `focused-tested` / `configured`, **bukan** `live-proven`. Kualitas suara TTS hanya bisa dinilai dengan observasi runtime berotorisasi terpisah.

---

## Perubahan

### config.yaml (blok `agent:`)

```yaml
max_iterations: 30            # P8E: dinaikkan dari 20 untuk tugas kompleks
interactive_max_iterations: 30   # P8E: disamakan (aturan kejujuran §17)
iteration_escalation:
  enabled: false              # P8E: dinonaktifkan — tidak bicara tanpa perintah
...
  interaction:
    # Presence: ... P8E: silent narration — speaker disabled, visual-only logging
    progress_min_interval_s: 12.0
    progress_max_spoken: 4
    speaker_enabled: false    # P8E: silent narration switch (wired into ui.py)
```

Catatan teknis: kunci `speaker_enabled` **harus** berada langsung di bawah blok `interaction:` yang sudah ada — percobaan awal membuat blok `interaction:` baru (nested `progress:`) gagal terbaca karena YAML duplicate-key (blok belakangan menimpa). Perbaikan final menyatu ke blok yang ada, tidak ada kunci duplikat.

### jarvis/agent/adapters/ui.py (`UIAdapter.__init__`)

```python
speaker_enabled = bool(_config.get("agent.interaction.speaker_enabled", True))
self._narrator = ProgressNarrator(
    min_interval_s=float(_config.get(
        "agent.interaction.progress_min_interval_s", 12.0)),
    max_spoken=0 if not speaker_enabled else int(_config.get(
        "agent.interaction.progress_max_spoken", 4)),
)
```

Default `True` dipertahankan bila kunci absen (perilaku lama tetap hidup bila config dihapus) — saklar hanya berlaku bila eksplisit `false`.

---

## Bukti Verifikasi (offline)

1. **Config load:** `agent.interaction.speaker_enabled` → `False`; `agent.max_iterations` → `30`; `agent.interactive_max_iterations` → `30`; `agent.iteration_escalation.enabled` → `False` — semua terbaca via `config.get()`.
2. **Wiring:** `UIAdapter(task_id='t1')._narrator._max_spoken` → `0` (narator diam total; `should_speak()` selalu False).
3. **Regresi fokus:** `tests/test_progress_narrator.py`, `tests/test_speech_queue.py`, `tests/test_task_speech_scoping_characterization.py`, `tests/test_ui_adapter_exceptions_handled_gracefully.py` → **39 passed** in 2.92 s (offscreen, `JARVIS_NO_MIC_METER=1`, basetemp di luar repo).
4. **FROZEN integrity:** OK (10 files, baseline 094b696) sebelum commit.
5. **git diff --cached:** hanya `config.yaml` (+6 −4) dan `jarvis/agent/adapters/ui.py` (+4 −1). Tidak ada CDP block atau path user-dirty lain ikut ter-commit.

### Known test failure (by design)

`tests/test_iteration_limit_honesty.py::test_interactive_run_offers_to_stop_before_the_wall` kini **gagal sesuai desain** — test itu mengasertikan pertanyaan eskalasi yang justru diminta user untuk dimatikan. File test sengaja **tidak diedit** (butuh otorisasi terpisah untuk mengubah ekspektasi test Fase 17). Sembilan test lain di file itu tetap hijau, termasuk `test_settings_shows_the_real_limit` (kedua kunci iterasi tetap sama: 30 == 30).

---

## Preservation Review

- ✅ FROZEN integrity OK (baseline 094b696), diverifikasi sebelum commit
- ✅ Path user-dirty tidak disentuh (CDP block config tetap dirty di tempatnya, `providers.py`, `image_gen_service.py`, `boot.py`, `window_actions.py` — perubahan pihak lain dibiarkan sebagai dirty terpisah)
- ✅ Tidak ada perubahan semantic/routing/BUS subscriber
- ✅ Staging eksplisit dua file; tidak ada `git add .` / `-A`
- ✅ Tidak ada akses provider/network/audio/kamera/hardware selama pekerjaan

---

## Yang Tidak Dijalankan

- Observasi GUI/suara live (`python main.py`) — validasi rasa "benar-benar diam saat bekerja" butuh runtime, otorisasi terpisah
- Perubahan kualitas TTS ("suara kaku") — jalur audio live, di luar lingkup offline
- Test iterasi loop penuh dengan client nyata — hanya fake client offline

---

## Rekomendasi Berikutnya

Satu langkah sempit dan aman: **jalankan `python main.py`, beri satu tugas yang memicu memory search, dan konfirmasi (a) tidak ada lagi interjensi suara saat bekerja, (b) hasil akhir/ACK masih terdengar.** Bila hijau, fase berikutnya bisa berupa observasi GUI live berotorisasi terpisah atau arah fitur P12+ sesuai pilihan user.

---

*Dokumen implementasi P8E. Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>*
