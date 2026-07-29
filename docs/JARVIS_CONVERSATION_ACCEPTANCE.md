# JARVIS Conversation & Platform Acceptance Contract

**Status:** Baseline / Fase 0

Dokumen ini merekam acceptance contract untuk program pematangan Jarvis **pasca-MK50** yang diminta user pada 2026-07-21. Ini bukan pengganti `JARVIS_MK50_MASTER_SPEC.md`; master spec tetap menjadi batas arsitektur dan zona FROZEN, kecuali user secara eksplisit mengubahnya.

## 1. Identitas yang harus dipertahankan

Jarvis tetap merupakan asisten personal yang:

- voice-first dan responsif;
- memiliki persona profesional, ringkas, dan sedikit witty bila sesuai konteks;
- mempertahankan wake/activation, audio transport, interruption, orb, tema, dan layout dasar;
- dapat mengontrol desktop dan melakukan pekerjaan agent secara native, tanpa runtime Hermes.

Tidak ada fase dalam program ini yang boleh mengganti Gemini Live/Charon, STT/TTS/wake pipeline, tema visual, aset orb, atau layout utama tanpa arahan user baru.

## 2. Kontrak percakapan natural

Untuk task agent T2+:

1. Jarvis memberi ACK segera setelah task diterima secara valid.
2. ACK menyebut niat atau tindakan yang akan dilakukan; tidak hanya mengulang frasa template generik.
3. Hasil task memiliki dua bentuk:
   - **spoken brief:** paling banyak dua kalimat pendek, sesuai bahasa user;
   - **display report:** detail hasil yang telah diverifikasi untuk UI dan messaging.
4. Nama, angka, judul, path, URL, dan sebab kegagalan penting dipertahankan sebagai fakta; respons natural tidak boleh menambah klaim keberhasilan.
5. Respons task yang sama tidak boleh memakai template ACK identik secara berulang bila alternatif aman tersedia.
6. Konfirmasi tindakan sensitif dan error yang membutuhkan wording tepat boleh memakai mode deterministik/verbatim.
7. Jarvis tidak wajib menambahkan pertanyaan penutup pada setiap respons; follow-up hanya muncul bila ada kelanjutan yang relevan.

## 3. Kontrak OAuth dan multi-provider

- OAuth OpenAI tetap memakai PKCE loopback dan `jarvis.core.secrets_store`; token tidak boleh muncul pada file konfigurasi, log, UI, telemetry, atau test failure.
- Status OAuth hanya boleh memuat informasi aman: connected, needs reauth, refresh due, dan error category.
- HTTP 401 dapat memicu refresh dan retry identik **maksimum satu kali**.
- Provider memiliki peran eksplisit: `voice_transport`, `light`, `heavy`, `conversation`, dan `auxiliary`.
- Tugas heavy tidak boleh diam-diam turun ke lane light; bila tidak ada provider heavy yang siap, Jarvis memberi laporan jujur.
- Fallback hanya dijalankan untuk kategori kegagalan yang ditetapkan policy dan harus menghasilkan telemetry aman.

## 4. Kontrak capability, skill, plugin, dan ingress

- Tool hanya terlihat/berjalan bila berada dalam toolset aktif dan diizinkan oleh surface asalnya.
- Skill memiliki provenance tervalidasi: `bundled`, `hub`, atau `agent-created`; status lifecycle: `active`, `stale`, `archived`, dengan pin/restore milik user.
- Plugin bersifat opt-in, manifest-validated, capability-bounded, dan tidak boleh membaca secrets, melewati confirmation, atau memodifikasi core policy secara langsung.
- Setiap platform ingress memakai transport-neutral contract, idempotency key, delivery status, dan default toolset yang terbatas.
- Telegram harus dimigrasikan ke gateway formal terlebih dahulu sebelum menambah platform baru.

## 5. Kriteria UI dan surface management

- Orb tetap menjadi home/default experience.
- Tools Browser, Skills Browser, Provider Health, dan Session Browser merupakan management surface opt-in melalui ContentStage/Command Palette.
- Dashboard web berbagi safe state model yang sama dengan desktop UI.
- UI tidak memanggil agent/tool blocking dari UI thread dan tidak menampilkan secret atau raw authorization data.

## 6. Feature flags dan rollback

Perilaku baru harus memiliki default yang backward-compatible dan rollback aman:

```yaml
conversation:
  naturalizer_enabled: false
  style: balanced
  max_spoken_sentences: 2
  max_spoken_chars: 260
routing:
  conversation:
    provider: auto
    model: ""
```

Jika naturalizer gagal, lambat, atau tidak tervalidasi, Jarvis mengirim `ConversationDelivery` deterministik. OAuth yang gagal tidak memblokir fallback yang secara eksplisit dikonfigurasi.

## 7. Baseline test yang telah diverifikasi

Pada 2026-07-21, sebelum perubahan runtime program pasca-MK50, suite berikut lulus:

```bash
unset PYTHONPATH && python -m pytest -q \
  tests/test_openai_oauth.py tests/test_phase6_secrets_oauth.py \
  tests/test_providers.py tests/test_phase3_model_routing.py \
  tests/test_phase2_interactivity.py tests/test_phase2_ingress.py \
  tests/test_voice_routing_integration.py
```

**Result:** `66 passed in 6.61s`.

## 8. Fase aktif dan decision gate

- **Fase 0:** dokumentasi acceptance, baseline test, dan catatan migrasi — selesai.
- **Fase 1:** hardening OpenAI OAuth — selesai pada 2026-07-21. Mencakup safe status, klasifikasi error, refresh/retry satu kali untuk HTTP 401, cache reset pada login/logout/reauth, capability `chat`/`tools`/`streaming`, dan status UI aman. Regression terkait: **72 passed in 6.96s**.
- **Fase 2:** multi-provider policy — selesai pada 2026-07-21. Role `voice_transport`, `light`, `heavy`, `conversation`, dan `auxiliary` kini eksplisit; `conversation=auto` mengikuti light, heavy tetap tidak turun diam-diam ke light, capability tidak dikenal dianggap unavailable, dan Settings menampilkan ringkasan role aman. Regression terkait: **83 passed in 6.21s**.
- **Fase 3:** deterministic ConversationDelivery — selesai pada 2026-07-21. Result terverifikasi kini dipisah menjadi `display_text`, `speech_text`, dan factual anchors; brief suara dibatasi dua kalimat/260 karakter, sementara desktop UI dan Telegram mempertahankan report detail. Root Gemini Live tidak lagi menerima instruksi literal `PERSIS`. Regression terkait: **120 passed in 8.33s**.
- **Fase 4:** naturalizer LLM opsional — selesai pada 2026-07-21. Composer hanya dapat mengubah `speech_text` pada success path root Gemini Live dan typed desktop; `display_text`, full factual anchors, error/failure, dan Telegram tetap deterministik. Default `auxiliary.response_composer.enabled=false`; provider/model/timeout/max-tokens tersedia di Settings. Output harus menjaga anchor spoken secara exact, menolak URL/path yang sebelumnya tidak dibaca, dibatasi dua kalimat/260 karakter, dan timeout/failure fallback ke object `ConversationDelivery` asli. Regression terkait: **143 passed**.
- **Fase 5:** unified delivery lifecycle/telemetry — selesai pada 2026-07-21. Root Gemini Live, typed desktop, dan Telegram kini melewati `delivery_lifecycle` untuk ACK, success, dan failure. EventBus menerima hanya source/outcome/mode serta ukuran report/brief dan jumlah anchor—tanpa task, raw result, URL, path, atau error mentah. Voice/typed tetap boleh naturalize `speech_text`; Telegram tetap memakai `display_text` deterministik. Regression terkait: **150 passed**.
- **Fase 6:** session continuity/follow-up context — selesai pada 2026-07-21. Buffer in-memory bounded dipisahkan dari durable memory/archive; hanya last intent dan `speech_text` safe dari success yang disimpan. Voice, typed desktop, dan Telegram memakai scope context terpisah; Telegram mengikuti session ID per-chat yang resettable. Referensi exact `lanjutkan`, `yang tadi`, dan `buka hasilnya` memperoleh block context hanya bila session yang sama memiliki success unambiguous. URL, path, display report raw, dan failure tidak disimpan/dimasukkan. Regression terkait: **153 passed**.
- **Fase 9:** Skills Hub/lifecycle safety — selesai pada 2026-07-21. Provenance tetap eksplisit dari sidecar (`bundled`, `hub`, `agent-created`); usage hanya bertambah setelah operasi skill sukses. Curator kini review-first: default dry-run, pinned dan bundled tidak bertransisi, dan scheduled pass hanya menandai stale. Pengarsipan fisik tetap aksi eksplisit/recoverable melalui `archive_skill`/`unarchive_skill`; tidak ada delete otomatis. Regression terfokus: **22 passed in 1.07s**.
- **Fase 10:** management control-plane read-only — selesai pada 2026-07-21. Shared snapshot hanya memuat metadata session, provider configured/model, dan jumlah active task; task/result/error/base URL/auth tidak keluar. Registry surface capability-gated menolak panel yang dimatikan. Dashboard mendapat endpoint bearer-authenticated `/api/control-plane`; formatter Sessions/Provider Health hanya memakai snapshot aman. Regression terfokus: **4 passed in 0.63s**.
- **Fase 11:** trusted-local plugin and Telegram gateway foundation — selesai pada 2026-07-21. Plugin manifest divalidasi sebelum import, hanya local paths, disableable, tanpa marketplace/network/auto-update; deklarasi tools wajib berada dalam toolset plugin. Gateway Telegram kini memiliki dedup inbound bounded dan default toolset `messaging`; outbound helper retry dibatasi satu retry sesuai caller. Tidak ada platform kedua ditambahkan. Regression terfokus: **17 passed in 0.64s**.
- **Fase 12:** release controls dan verification report — selesai dengan blocker terdokumentasi pada 2026-07-21. `release_controls` default-off untuk naturalizer/plugins/gateway dan rollback selalu mempertahankan deterministic delivery. Focused cross-phase regression: **29 passed in 1.47s**. Suite `tests/` belum hijau penuh karena kontrak curator legacy mengharapkan auto-archive yang kini dilarang, serta frozen manifest mendeteksi perubahan `main.py` Fase 3–6 terhadap baseline MK50; manifest tidak ditulis ulang.
- **Fase berikutnya:** menunggu decision gate/approval; transport Gemini Live dan kontrak deterministic delivery Fase 3 tetap frozen.
- Setiap fase harus: discovery → test merah → implementasi minimal → test hijau → regression → laporan/approval sebelum fase berikutnya.
