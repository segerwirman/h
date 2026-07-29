# Rencana Pensiun `ui.py` Legacy

Dokumen ini adalah rencana Fase 9, bukan izin untuk mengubah zona FROZEN.
Root `ui.py` belum dapat dihapus atau diganti pada baseline MK50 saat ini.

## Fakta dependency saat ini

Entry aktif adalah `python -m jarvis.main` dan tampilan aktif berasal dari
`jarvis/ui/window.py`. Namun pipeline suara masih memiliki rantai import ini:

```text
jarvis.main._start_voice_pipeline
  -> import main.JarvisLive
  -> main.py: from ui import JarvisUI
  -> ui.py
```

Akibatnya, menghapus atau mengganti nama root `ui.py` sekarang akan memutus
startup voice. Kode nyata ini mengalahkan asumsi bahwa UI legacy sudah bebas
dependency. Root `main.py` dan `ui.py` tetap FROZEN dan dijaga manifest hash.

## Tahapan pensiun yang diusulkan

1. Pertahankan `ui.py` sebagai dependency legacy byte-stable pada MK50.
2. Karakterisasi facade UI yang benar-benar dipakai `main.JarvisLive`, termasuk
   callback, signal, status, interrupt, kamera, serta cleanup. Tambahkan contract
   test tanpa mengubah perilaku visual maupun audio.
3. Dengan persetujuan eksplisit untuk exception FROZEN, pisahkan runtime voice
   dari import UI root. Adapter baru harus menerima facade UI aktif melalui
   dependency injection; STT, TTS, wake word, persona, timing, dan audio stream
   tidak boleh berubah.
4. Jalankan shadow test entry aktif dengan dan tanpa voice. Bandingkan signal,
   callback, lifecycle, screenshot UI, dan sampel audio terhadap baseline.
5. Pertahankan shim deprecation selama minimal satu release. Catat warning hanya
   di log developer, bukan pada suara atau tampilan pengguna.
6. Hapus `ui.py` hanya setelah pencarian import bersih, suite regresi lulus,
   validasi perangkat nyata selesai, dan user menyetujui perubahan FROZEN.

## Kriteria penerimaan

- `python -m jarvis.main` berfungsi dengan dan tanpa `--no-voice`.
- Tidak ada runtime import root `ui.py`.
- UI, orb, layout, suara, wake word, dan latensi interaksi setara baseline.
- Interrupt, kamera, shutdown, serta reconnect voice lolos uji perangkat nyata.
- Manifest FROZEN hanya diubah melalui exception yang disetujui dan direkam.

Jika salah satu kriteria gagal, rollback ke dependency/shim legacy dan pertahankan
manifest baseline. Tidak ada bagian rencana ini yang boleh dilaksanakan diam-diam
sebagai refactor biasa.
