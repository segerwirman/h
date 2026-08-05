"""Satu antrean bicara untuk seluruh Jarvis (Fase 28).

Keluhan lapangan Takeda: *"suara tumpang tindih dan saling memotong membuat
saya bingung apa yang sedang dikerjakan."*

Sebabnya di kode: ``MainWindow._speak_line`` melahirkan **thread baru untuk
setiap kalimat**, dan ada 42 pemanggil — ACK, narator progres, hasil akhir,
konfirmasi, ringkasan pencarian. Tidak ada yang menyerialkan mereka.

Modul ini bukan sekadar pengurut. Yang membuatnya berguna adalah **apa yang
DIBUANG**: progres yang sudah basi ketika hasil akhir tiba tidak boleh
diucapkan belakangan, karena justru itulah yang membuat user bingung soal apa
yang sedang dikerjakan.

Aturan per jenis:

``confirm``   pertanyaan konfirmasi — mendahului antrean, tidak pernah dibuang;
              pertanyaan yang hilang membuat user menunggu jawaban yang tidak
              pernah diminta.
``final``     hasil/kegagalan — membatalkan progres dan ACK giliran yang sama.
``ack``       "baik, saya kerjakan" — dibuang bila hasilnya sudah tiba.
``progress``  narasi kerja — digantikan progres yang lebih baru.

Pembatalan selalu mengikat SATU giliran (``turn``), bukan seluruh antrean:
pekerjaan latar milik giliran lain tidak boleh ikut bungkam.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from jarvis.core import log

_logger = log.get("core.speech")

_PRIORITY = {"confirm": 3, "final": 2, "ack": 1, "progress": 0}
_DEFAULT_PRIORITY = 2


@dataclass(order=True)
class _Item:
    priority: int
    seq: int
    text: str = field(compare=False)
    kind: str = field(compare=False, default="info")
    turn: str = field(compare=False, default="")


class SpeechQueue:
    """Serialisasi ucapan. ``speaker`` dipanggil satu per satu, tidak pernah
    bersamaan, dan tidak pernah melempar ke pemanggil."""

    MAX_PENDING = 32

    def __init__(self, speaker, *, on_drop=None):
        self._speaker = speaker
        self._on_drop = on_drop
        self._lock = threading.Lock()
        self._pending: list[_Item] = []
        self._seq = 0
        self._last_spoken = ""
        self._speaking = threading.Lock()

    # ── API ───────────────────────────────────────────────────────────────
    def say(self, text, *, kind: str = "info", turn: str = "") -> bool:
        """Antrekan satu kalimat. ``False`` bila diabaikan atau digantikan."""
        try:
            line = " ".join(str(text or "").split())
            if not line:
                return False
            label = str(kind or "info").strip().casefold()
            priority = _PRIORITY.get(label, _DEFAULT_PRIORITY)
            key = str(turn or "")

            with self._lock:
                self._supersede(label, key)
                if len(self._pending) >= self.MAX_PENDING:
                    # Buang yang paling tidak penting dan paling lama.
                    self._pending.sort()
                    dropped = self._pending.pop(0)
                    _logger.info("speech.dropped_overflow", kind=dropped.kind)
                self._seq += 1
                self._pending.append(
                    _Item(-priority, self._seq, line, label, key))
            return True
        except Exception as exc:                             # noqa: BLE001
            _logger.warning("speech.enqueue_failed", error=str(exc)[:100])
            return False

    def run_once(self) -> bool:
        """Ucapkan paling banyak satu antrean. ``False`` bila kosong."""
        with self._speaking:
            with self._lock:
                if not self._pending:
                    return False
                self._pending.sort()
                item = self._pending.pop(0)
                if item.text == self._last_spoken and item.kind != "confirm":
                    # Mengulang kalimat yang sama persis terdengar seperti
                    # Jarvis tersangkut, bukan seperti kabar baru.
                    return True
                self._last_spoken = item.text
            try:
                self._speaker(item.text)
            except Exception as exc:                         # noqa: BLE001
                _logger.warning("speech.speaker_failed",
                                error=str(exc)[:100])
            return True

    def drain(self) -> None:
        while self.run_once():
            pass

    def pending(self) -> int:
        with self._lock:
            return len(self._pending)

    def clear(self, turn: str = "") -> None:
        """Bungkam giliran tertentu (mis. saat user menyela)."""
        with self._lock:
            if turn:
                self._pending = [i for i in self._pending if i.turn != turn]
            else:
                self._pending.clear()

    # ── internal ──────────────────────────────────────────────────────────
    def _supersede(self, kind: str, turn: str) -> None:
        """Buang antrean yang sudah tidak ada gunanya diucapkan."""
        if kind == "progress":
            # Hanya progres TERBARU yang berguna.
            self._drop(lambda i: i.kind == "progress" and i.turn == turn)
        elif kind == "final":
            # Hasil sudah ada: progres dan ACK giliran ini tidak relevan lagi.
            self._drop(lambda i: i.turn == turn
                       and i.kind in ("progress", "ack"))

    def _drop(self, predicate) -> None:
        keep: list[_Item] = []
        for item in self._pending:
            if predicate(item):
                _logger.info("speech.superseded", kind=item.kind)
                if self._on_drop is not None:
                    try:
                        self._on_drop(item.text, item.kind)
                    except Exception:                        # noqa: BLE001
                        pass
                continue
            keep.append(item)
        self._pending = keep


__all__ = ["SpeechQueue"]
