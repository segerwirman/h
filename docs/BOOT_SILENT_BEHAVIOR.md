# Boot Sequence — Silent by Design (Decision Documented)

**Status:** ✅ Confirmed as expected behavior  
**Date:** 2026-08-21  
**Decision:** Opsi 3 — biarkan silent boot, tidak ada perubahan  

---

## Ringkasan Keputusan

**Permintaan user:** "Sebelum lanjut ke opsi A, kenapa suara jarvis tidak terdengar saat booting coba periksa apa penyebabnya."

**Diagnosa:** Boot sequence tidak pernah mengucapkan apa-apa secara default karena fitur briefing adalah **opt-in** untuk privacy/security. `BootSequence` hanya menampilkan animasi visual ("BOOTING" → "CORE ONLINE"), tidak trigger speaker.

**Keputusan:** Biarkan silent boot sebagai **behavior yang diharapkan**. Tidak ada source/config changes diperlukan.

---

## Akar Masalah (Technical Trace)

### 1. Konfigurasi Briefing Disabled by Default

```yaml
# config.yaml line 232-238
briefing:
  on_boot:
    calendar: false       # ← OFF
    email_content: false  # ← OFF
    monitor: false        # ← OFF
  telegram:
    send_summary: false
```

### 2. Jalur Kode yang Menyebabkan Silent

```python
# jarvis/main.py line 351-364
def on_boot_done(_ready: str, results) -> None:
    ui.write_log("SYS: CORE ONLINE — command input ready.")
    
    # ← HANYA bicara jika briefing.enabled == True
    try:
        from jarvis.integrations import boot_briefing
        boot_briefing.start_if_enabled(
            lambda text: (
                ui._win._record_task_result("HASIL", text),
                ui._win._speak_line(text, kind="final"),  # ← Trigger suara
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("boot.briefing_unavailable", error=type(exc).__name__)
```

```python
# jarvis/integrations/boot_briefing.py line 31-34
def start_if_enabled(deliver) -> bool:
    """Schedule local briefing after boot without delaying readiness/UI."""
    if not briefing.boot_briefing_enabled():  # ← Return False by default
        return False
```

**Kesimpulan:** Suara hanya akan terdengar jika salah satu dari `calendar`, `email_content`, atau `monitor` di-enable. Design intent adalah **privacy-first**: tidak ada automatic speech saat boot kecuali user explicitly opt-in.

---

## Mengapa Silent Boot Adalah Behavior yang Benar

| Aspek | Penjelasan |
|-------|------------|
| **Privacy** | Tidak ada audio otomatis yang mungkin mengandung informasi sensitif (kalender, email, monitor) |
| **Security** | Tidak ada trigger TTS tanpa user consent, mencegah unexpected audio di environment shared/public |
| **UX Control** | User punya kendali penuh: silent boot = focus mode; enabled briefing = proactive assistant |
| **Design Intent** | Fase 17D secara eksplisit mendefinisikan briefing sebagai opt-in feature |
| **Code Contract** | Line 344 docs/main.py: "cinematic boot: visual-only readiness checks, never a briefing" |
| **Return Value** | BootSequence passes `_ready` string that is intentionally unused (blind callback) |

---

## Verifikasi Komponen Terkait

Meskipun silent boot adalah expected behavior, komponen audio path tetap diverifikasi:

- ✅ `_check_tts()` di `boot.py` line 72-85: Validasi output device via `sounddevice`
- ✅ Voice pipeline (`_start_voice_pipeline`) tetap di-launch setelah `BootSequence` dimulai
- ✅ `voice.audio.output_device: null` → default speaker aktif
- ✅ Boot cinematic animation ("BOOTING" → "CORE ONLINE") berfungsi tanpa audio

**Label evidence:** `configured` untuk TTS device check; `silent-boot-expected` untuk behavior.

---

## Langkah Selanjutnya

Setelah konfirmasi bahwa silent boot adalah expected behavior:

**Option A:** Lanjut ke P8-B layout density improvements (zone heights -8px each, icon spacing -4px)  
**Option B:** Pause visual expansion, kembali ke Phase 35 batch closure (cari file candidate berikutnya)  
**Option C:** Stop sementara semua perubahan, evaluasi roadmap direction  

Karena user memilih opsi 3 (biarkan silent boot), tidak ada code/config changes yang diperlukan. Tinggal pilih next phase.

---

*Documented after diagnostic trace: no changes required, behavior confirmed as designed.*

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
