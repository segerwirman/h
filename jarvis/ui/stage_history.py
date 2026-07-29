"""Riwayat panel untuk ContentStage — dasar tombol "kembali".

DIAGNOSIS_2 MASALAH 5d: ``jarvis/ui/stage.py`` hanya punya
``show_child``/``activate``/``hide_all`` — **tidak ada konsep riwayat sama
sekali**, sehingga tombol kembali tidak pernah bisa dibuat. Jadi ini bukan
bug; fiturnya memang belum ada.

Ekstensi tipis di luar ``stage.py``: stage tidak di-refactor, hanya diamati.
Riwayat dibatasi 5 supaya "kembali" tetap bisa ditebak — tumpukan dalam
membuat user tidak tahu akan mendarat di mana.
"""
from __future__ import annotations

import threading

from jarvis.core import log

_logger = log.get("ui.stage_history")

MAX_DEPTH = 5


class StageHistory:
    """Tumpukan nama panel. Tidak menyentuh widget apa pun."""

    def __init__(self, stage, max_depth: int = MAX_DEPTH) -> None:
        self._stage = stage
        self._max = max(1, int(max_depth))
        self._stack: list[str] = []
        self._lock = threading.RLock()
        self._suspend = False

    # ── perekaman ────────────────────────────────────────────────────────

    def record(self, name: str) -> None:
        """Catat panel yang SEDANG tampil sebelum berpindah."""
        with self._lock:
            if self._suspend:
                return
            current = self._stage.current
            if not current or current == name:
                return
            if self._stack and self._stack[-1] == current:
                return
            self._stack.append(current)
            if len(self._stack) > self._max:
                del self._stack[0]

    def depth(self) -> int:
        with self._lock:
            return len(self._stack)

    def peek(self) -> str | None:
        with self._lock:
            return self._stack[-1] if self._stack else None

    def clear(self) -> None:
        with self._lock:
            self._stack.clear()

    # ── navigasi ─────────────────────────────────────────────────────────

    def can_go_back(self) -> bool:
        return bool(self._stack) or bool(self._stage.current)

    def back(self) -> str | None:
        """Panel sebelumnya, atau EMPTY bila tumpukan habis.

        Mengembalikan nama panel yang ditampilkan, atau ``None`` bila stage
        dikosongkan.
        """
        with self._lock:
            previous = self._stack.pop() if self._stack else None
            self._suspend = True            # jangan catat langkah mundur
        try:
            if previous:
                self._stage.show_child(previous)
                _logger.info("stage.back", to=previous)
                return previous
            self._stage.hide_all()
            _logger.info("stage.back", to="EMPTY")
            return None
        finally:
            with self._lock:
                self._suspend = False


__all__ = ["StageHistory", "MAX_DEPTH"]
