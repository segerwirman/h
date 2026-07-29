---
name: laporan-harian
description: Cara menyusun laporan/briefing harian untuk user (format, sumber, urutan)
triggers: [laporan harian, briefing, daily report]
category: Productivity
---

# Laporan Harian

Saat diminta laporan/briefing harian (atau dipakai oleh cron):

1. `web_search` mode=news untuk 3-5 berita teknologi/AI terbaru (bahasa user).
2. Cuaca kota user bila diketahui dari memori (`memory_search` "kota user").
3. `cron_list` — sebutkan job yang akan berjalan hari ini.
4. `todo_read` — sisa pekerjaan sesi sebelumnya bila ada.

Format hasil:
- Sapaan singkat + tanggal.
- Berita: judul — satu kalimat ringkasan — sumber.
- Maksimal 200 kata, tanpa basa-basi.
