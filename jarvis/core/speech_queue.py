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
        self._last_spoken: tuple[str, str] | None = None
        self._speaking = threading.Lock()
        self._inflight = None
        self._inflight_item: _Item | None = None

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
                if (label == "ack" and (
                        any(item.kind == "final" and item.turn == key
                            for item in self._pending)
                        or (self._inflight_item is not None
                            and self._inflight_item.kind == "final"
                            and self._inflight_item.turn == key))):
                    return False
                self._supersede(label, key)
                if len(self._pending) >= self.MAX_PENDING:
                    # Nilai priority disimpan negatif untuk urutan delivery.
                    # Korban overflow justru priority paling RENDAH; pada tie,
                    # buang yang paling lama. Konfirmasi tidak boleh terpilih
                    # selama ada item dengan prioritas lebih rendah.
                    victim = min(
                        range(len(self._pending)),
                        key=lambda index: (
                            -self._pending[index].priority,
                            self._pending[index].seq,
                        ),
                    )
                    dropped = self._pending.pop(victim)
                    _logger.info("speech.dropped_overflow", kind=dropped.kind)
                self._seq += 1
                self._pending.append(
                    _Item(-priority, self._seq, line, label, key))
            return True
        except Exception as exc:                             # noqa: BLE001
            _logger.warning("speech.enqueue_failed", error=str(exc)[:100])
            return False

    def run_once(self) -> bool:
        """Submit at most one item when the previous audible turn is terminal."""
        with self._speaking:
            with self._lock:
                if self._ticket_active(self._inflight):
                    return False
                if self._inflight is not None:
                    self._settle_inflight_locked()
                if not self._pending:
                    return False
            # Readiness dapat memanggil Live state; jangan tahan queue lock saat
            # menyeberangi komponen lain. _speaking tetap menserialkan consumer.
            if not self._speaker_ready():
                return False
            with self._lock:
                if not self._pending:
                    return False
                self._pending.sort()
                item = self._pending.pop(0)
                spoken_key = (item.text, item.turn)
                if spoken_key == self._last_spoken and item.kind != "confirm":
                    # Hanya duplicate milik task/turn yang sama yang terlihat
                    # seperti stuck; dua task boleh punya final identik.
                    self._last_spoken = spoken_key
                    return True
                # Reserve ownership before crossing into the speaker. A direct
                # Live notice can inspect ``busy()`` from another thread during
                # submission and must not slip into this pop-before-ticket gap.
                self._inflight_item = item
            delivered = True
            try:
                ticket = self._speaker(item.text)
                with self._lock:
                    if self._ticket_active(ticket):
                        self._inflight = ticket
                    elif self._ticket_completed(ticket):
                        self._last_spoken = spoken_key
                        self._inflight_item = None
                    elif ticket is None:
                        # Compatibility speaker lama: return None berarti
                        # synchronous success.
                        self._last_spoken = spoken_key
                        self._inflight_item = None
                    elif self._ticket_aborted(ticket):
                        # ready() dan submission bukan transaksi tunggal. Jika
                        # lane berubah di sela keduanya, jangan hilangkan item;
                        # kembalikan dengan sequence yang sama untuk retry.
                        self._pending.append(item)
                        self._inflight_item = None
                        delivered = False
                    else:
                        self._inflight_item = None
            except Exception as exc:                         # noqa: BLE001
                _logger.warning("speech.speaker_failed",
                                error=str(exc)[:100])
                with self._lock:
                    self._inflight_item = None
            return delivered

    def drain(self) -> int:
        count = 0
        while self.run_once():
            count += 1
        return count

    def pending(self) -> int:
        """Return queued items only (the established compatibility contract)."""
        with self._lock:
            return len(self._pending)

    def busy(self) -> bool:
        """Whether queued, submitting, or submitted speech owns this lane."""
        with self._lock:
            return bool(self._pending or self._inflight_item is not None)

    def clear(self, turn: str = "") -> None:
        """Bungkam giliran tertentu (mis. saat user menyela)."""
        with self._lock:
            if turn:
                self._pending = [i for i in self._pending if i.turn != turn]
            else:
                self._pending.clear()

    # ── internal ──────────────────────────────────────────────────────────
    @staticmethod
    def _ticket_active(ticket) -> bool:
        if ticket is None:
            return False
        try:
            return not bool(ticket.done)
        except Exception:
            return False

    @staticmethod
    def _ticket_completed(ticket) -> bool:
        if ticket is None:
            return False
        try:
            return bool(ticket.completed)
        except Exception:
            # A legacy terminal token may expose only ``done``. Preserve the
            # previous terminal-success assumption for that narrow contract.
            try:
                return bool(ticket.done) and not bool(ticket.aborted)
            except Exception:
                return False

    @staticmethod
    def _ticket_aborted(ticket) -> bool:
        if ticket is None:
            return False
        try:
            return bool(ticket.aborted)
        except Exception:
            return False

    def _settle_inflight_locked(self) -> None:
        ticket = self._inflight
        item = self._inflight_item
        if item is not None and self._ticket_completed(ticket):
            self._last_spoken = (item.text, item.turn)
        elif item is not None and self._ticket_aborted(ticket):
            # Accepted submission is not delivery. A reconnect, interruption,
            # cancellation, or playback failure must preserve the same task item
            # for the next safe boundary instead of silently losing completion.
            self._pending.append(item)
        self._inflight = None
        self._inflight_item = None

    def _speaker_ready(self) -> bool:
        ready = getattr(self._speaker, "ready", None)
        if not callable(ready):
            owner = getattr(self._speaker, "__self__", None)
            ready = getattr(getattr(owner, "on_speech_command", None),
                            "ready", None)
        if not callable(ready):
            return True
        try:
            return bool(ready())
        except Exception as exc:                              # noqa: BLE001
            _logger.warning("speech.ready_failed", error=str(exc)[:100])
            return False

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
