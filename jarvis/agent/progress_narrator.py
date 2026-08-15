"""Progress narrator — presence layer agar JARVIS 'menyela sesekali dengan
progres' saat mengerjakan tugas di latar, alih-alih bilang 'baik, sedang saya
kerjakan' lalu diam.

Pure + thread-safe + throttled. Tidak tahu Qt/voice/transport; caller yang
memutuskan mengucapkan hasilnya. Aman untuk unit test tanpa UI.
"""
from __future__ import annotations

import threading
import time

# Peta nama tool → frasa natural (Indonesia). Tool asing tetap visual-only.
_TOOL_PHRASES = {
    "web_search": "Sedang mencari datanya, sir.",
    "web_extract": "Membaca sumbernya sekarang.",
    "browser_navigate": "Membuka halamannya.",
    "browser_click": "Menelusuri halaman.",
    "browser_snapshot": "Memeriksa isi halaman.",
    "image_generate": "Membuat gambarnya, sebentar.",
    "terminal": "Menjalankan perintahnya.",
    "process_spawn": "Menyalakan prosesnya.",
    "file_read": "Membaca berkasnya.",
    "file_write": "Menyimpan berkasnya.",
    "memory_search": "Mengecek ingatan saya.",
    "yt_search_data": "Mencari videonya.",
    "yt_latest": "Mengambil video terbarunya.",
    "gmail_send": "Menyiapkan emailnya.",
    "gcal_create": "Menambah agendanya.",
}
def phrase_for(tool_name: str) -> str:
    """Frasa progres natural untuk sebuah tool (tanpa side effect)."""
    key = str(tool_name or "").strip().lower()
    # Buang prefix '🔧 ' yang dikirim agent loop.
    for junk in ("🔧", "tool:", "menjalankan"):
        key = key.replace(junk, "").strip()
    key = key.split()[0] if key else ""
    return _TOOL_PHRASES.get(key, "")


class ProgressNarrator:
    """Batasi ucapan progres agar hadir tapi tidak mengganggu.

    - ``min_interval_s``: jeda minimal antar-ucapan progres.
    - ``max_spoken``: maksimum ucapan progres per tugas (sisanya cukup log).
    Log ke panel selalu boleh (tak dibatasi); yang dibatasi hanya SUARA.
    """

    def __init__(self, *, min_interval_s: float = 12.0, max_spoken: int = 4):
        self._min_interval = max(0.0, float(min_interval_s))
        self._max_spoken = max(0, int(max_spoken))
        self._last = 0.0
        self._has_spoken = False
        self._spoken = 0
        self._last_phrase = ""
        self._lock = threading.Lock()

    def should_speak(self, phrase: str, *, now: float | None = None) -> bool:
        """True bila progres ini layak diucapkan (bukan sekadar dicatat)."""
        phrase = " ".join(str(phrase or "").split())
        if not phrase:
            return False
        now = time.monotonic() if now is None else float(now)
        with self._lock:
            if self._spoken >= self._max_spoken:
                return False
            if phrase == self._last_phrase:
                return False               # jangan mengulang frasa sama
            if self._has_spoken and (now - self._last) < self._min_interval:
                return False
            self._last = now
            self._has_spoken = True
            self._last_phrase = phrase
            self._spoken += 1
            return True

    def reset(self) -> None:
        with self._lock:
            self._last = 0.0
            self._has_spoken = False
            self._spoken = 0
            self._last_phrase = ""
