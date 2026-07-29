# Troubleshooting J.A.R.V.I.S (Mark XLIX — hardened)

## Instalasi

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-xlix.txt
python -m jarvis.main            # full assistant
python -m jarvis.main --no-voice # UI/NLP saja
python -m pytest tests\ -q       # test suite
python -m jarvis.core.health     # snapshot kesehatan semua subsistem
```

## JARVIS diam setelah perintah suara

Sejak hardening Fase 1-2 setiap perintah punya outcome eksplisit di
`logs/jarvis.log` (`pipeline.outcome`, `turn.outcome`) dengan `request_id`
yang sama dari transkripsi sampai TTS. Cari:

- `turn.outcome outcome=timeout` → model/jaringan lambat; JARVIS kini
  mengucapkan "perintah dibatalkan" otomatis setelah `JARVIS_RESPONSE_TIMEOUT_S`
  (default 30 s).
- `tool.timeout` → sebuah tool macet; dibatasi `JARVIS_TOOL_TIMEOUT_S`
  (default 60 s), pipeline tetap jalan.
- `tts.watchdog_reset` → status bicara macet; mikrofon dibuka paksa setelah
  `JARVIS_MAX_SPEAK_S` (default 120 s).
- `pipeline.stage_timeout` → state machine memaksa kembali ke state aman.

## Double clap tidak bekerja / terlalu sensitif

Jalankan mode diagnostik (menampilkan level, noise floor, alasan
terima/tolak setiap kandidat):

```powershell
python -m jarvis.core.wake
```

Tuning via env (atau `wake:` di config.yaml):

| Gejala | Ubah |
|---|---|
| Tidak pernah terdeteksi | Turunkan `CLAP_THRESHOLD_MULTIPLIER` (mis. 4.0) atau `wake.min_abs_peak` |
| Noise dianggap clap | Naikkan `CLAP_THRESHOLD_MULTIPLIER` / `wake.crest_factor` |
| Dua tepukan cepat tak terhitung | Turunkan `CLAP_MIN_INTERVAL_MS` |
| Tepukan lambat tak terhitung | Naikkan `CLAP_MAX_INTERVAL_MS` |
| Trigger beruntun | Naikkan `CLAP_COOLDOWN_MS` |
| Mic salah | Set `CLAP_INPUT_DEVICE` (index PyAudio) |

Deteksi otomatis ditekan saat JARVIS sedang bicara (echo guard), dan double
clap saat sesi sudah aktif tidak membuat sesi kedua.

## Upload DOCX gagal

- `.docx` valid kini diekstrak dengan python-docx (paragraf, heading, list,
  tabel). Pastikan terpasang: `python -m pip install python-docx`.
- `.doc` lama ditolak dengan pesan jelas — simpan ulang sebagai `.docx`.
- File korup/salah ekstensi/terenkripsi/terlalu besar → pesan spesifik di
  ContentStage dan diucapkan via TTS (tidak pernah diam).
- Jika ekstraksi sukses tapi LLM gagal, JARVIS menampilkan cuplikan teks dan
  mengatakan proses ringkasan gagal.

## Relay.app

Lihat [RELAY_SETUP.md](RELAY_SETUP.md). Cek cepat:
`` → baris `relay`, atau
`curl http://127.0.0.1:8791/relay/webhook/health`.

## Keamanan kredensial

- Kredensial IMAP TIDAK lagi ditaruh di `config.yaml` — gunakan env
  `JARVIS_IMAP_HOST` / `JARVIS_IMAP_USER` / `JARVIS_IMAP_PASSWORD`.
  (Kredensial lama yang pernah tertulis di config.yaml sebaiknya DIROTASI.)
- Secret Relay hanya via env (`RELAY_WEBHOOK_SECRET`, `RELAY_API_TOKEN`).
- Log tidak pernah memuat token, isi dokumen, atau audio mentah.
