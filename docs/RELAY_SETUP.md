# Integrasi Relay.app — Panduan Setup

JARVIS membaca data dari Relay.app melalui **webhook masuk**: workflow Relay
Anda menambahkan langkah *HTTP request* yang mengirim JSON ke endpoint JARVIS.
Tidak ada API baca publik Relay.app yang diasumsikan — JARVIS hanya menerima
apa yang sengaja Anda kirim, plus (opsional) memanggil endpoint yang Anda
ekspos sendiri.

## 1. Konfigurasi di sisi Relay.app

1. Buka workflow yang datanya ingin dibaca JARVIS.
2. Tambahkan langkah **HTTP request** (Send HTTP request) di akhir workflow.
3. Method: `POST`. URL: webhook JARVIS Anda (lihat bagian 2).
4. Header:
   - `Content-Type: application/json`
   - `X-Relay-Token: <RELAY_WEBHOOK_SECRET Anda>`
5. Body (map field dari langkah-langkah workflow Anda):

```json
{
  "event_id": "{{run_id}}",
  "workflow": "laporan-harian",
  "kind": "workflow_result",
  "timestamp": "{{run_started_at}}",
  "data": {
    "ringkasan": "…",
    "jumlah": 42
  }
}
```

Hanya `event_id` yang sangat disarankan (untuk dedup & proteksi replay);
field lain opsional. Payload tanpa `event_id` tetap diterima (id dibuat dari
hash body).

## 2. URL webhook

Default JARVIS bind di `http://127.0.0.1:8791/relay/webhook` (loopback,
tidak terekspos ke internet). Karena Relay.app berjalan di cloud, Anda perlu
mengekspos endpoint ini, misalnya dengan tunnel:

```
cloudflared tunnel --url http://127.0.0.1:8791
# atau: ngrok http 8791
```

URL yang dipakai di Relay = `https://<tunnel-anda>/relay/webhook`.

## 3. Secret / autentikasi

- Wajib: `RELAY_WEBHOOK_SECRET` (string acak panjang, mis. `openssl rand -hex 24`).
  Tanpa ini webhook **menolak start** (secure by default).
- Mode sederhana: Relay mengirim header `X-Relay-Token: <secret>`.
- Mode kuat (jika pengirim bisa menghitung HMAC):
  `X-Relay-Signature: sha256=<hex hmac_sha256(body, secret)>`.
- Event dengan `timestamp` lebih tua dari `RELAY_REPLAY_WINDOW_S` (default
  300 detik) ditolak (proteksi replay). Duplikat `event_id` di-dedup.

## 4. Environment variable

Lihat `.env.example`. Minimum untuk mode baca via webhook:

```
RELAY_ENABLED=1
RELAY_WEBHOOK_SECRET=<secret Anda>
```

Opsional (hanya bila Anda mengekspos endpoint sendiri untuk ditarik JARVIS):
`RELAY_BASE_URL`, `RELAY_API_TOKEN`, dan mapping `relay.endpoints` di
`config.yaml`. JARVIS tidak pernah mengarang path endpoint.

## 5. Menguji koneksi

```powershell
# jalankan JARVIS (python -m jarvis.main), lalu:
curl.exe -X POST http://127.0.0.1:8791/relay/webhook `
  -H "Content-Type: application/json" `
  -H "X-Relay-Token: <secret>" `
  -d '{"event_id":"tes-1","workflow":"uji","data":{"halo":"dunia"}}'
# → {"ok": true}

curl.exe http://127.0.0.1:8791/relay/webhook/health
# → {"ok": true, "events": 1}
```

Lalu tanyakan ke JARVIS: *"cek status koneksi relay"* atau *"baca event
relay terbaru"* — HermesAgent memakai tool `RELAY_CONNECTION_STATUS` /
`RELAY_READ_EVENTS`.

## 6. Contoh payload (tersanitasi)

```json
{
  "event_id": "run-2026-07-11-0001",
  "workflow": "rekap-penjualan",
  "kind": "workflow_result",
  "timestamp": "2026-07-11T08:00:00Z",
  "data": {"total": "Rp 1.250.000", "transaksi": 17}
}
```

## 7. Batasan data yang dapat dibaca JARVIS

- Hanya event yang workflow Anda kirim ke webhook (maks 500 event tersimpan,
  yang lama dihapus otomatis; payload maks 256 KB).
- Tool agent dibatasi 25 event per panggilan, payload dipotong (400–800
  karakter) — agent tidak pernah menerima dump mentah besar.
- Tool agent bersifat **read-only**; tidak ada akses HTTP arbitrer.

## 8. Mencabut akses

1. Hapus/ubah `RELAY_WEBHOOK_SECRET` (request lama langsung ditolak 401).
2. Set `RELAY_ENABLED=0` (service tidak start).
3. Matikan tunnel.
4. Hapus `relay_events.sqlite` bila ingin membersihkan data tersimpan.

## 9. Read-only vs action-enabled

- **Read-only (default):** JARVIS hanya membaca event/hasil workflow.
- **Action-enabled:** `RELAY_ALLOW_ACTIONS=1` mengizinkan pemanggilan
  `RelayService.trigger_workflow(..., confirmed=True)` dari kode/UI —
  setiap aksi tetap butuh konfirmasi eksplisit per panggilan, dan tool ini
  sengaja TIDAK diekspos ke agent LLM.