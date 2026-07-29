"""Mini strip tugas latar (AUDIT_REPORT §8.5 lapis 1).

Selalu terlihat selama ada tugas aktif, maksimum 3 chip, tinggi ~26 px.
Auto-hide 6 detik setelah semuanya selesai.

Digambar manual dalam satu widget — bukan tumpukan QWidget per chip —
mengikuti gaya renderer di repo ini (``orb.py``, ``HudCanvas``) dan supaya
strip setinggi 26 px tidak membawa 3×3 widget anak beserta layout-nya.
Hit-test tombol ✕ dilakukan terhadap rect yang dihitung saat paint.

Seluruh warna, font, dan spacing dibaca dari ``jarvis.ui.theme`` **saat
render**, bukan di-cache di konstruktor — itulah yang membuat pergantian tema
langsung terlihat.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from jarvis.core import config
from jarvis.ui import theme

_SPINNER = "◐◓◑◒"


class TaskStrip(QWidget):
    """Chip ringkas per tugas aktif. Klik chip → buka deck; klik ✕ → batal."""

    chip_clicked = pyqtSignal(str)        # task id
    cancel_requested = pyqtSignal(str)    # task id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        c = config.section("ui.task_deck")
        self._max_chips = int(c.get("mini_strip_max", 3))
        self._height = int(c.get("mini_strip_height_px", 26))
        self._autohide_ms = int(c.get("autohide_after_done_ms", 6000))

        self._views: list = []
        self._chip_rects: list[tuple[str, QRectF, QRectF]] = []
        self._all_done_since: float | None = None
        self._phase = 0
        # Id yang tombol batalnya baru diklik. Dipakai agar chip berubah
        # SEBELUM registry sempat memperbarui statusnya.
        self._cancelling: set[str] = set()

        self.setFixedHeight(self._height)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.hide()

        # Spinner + evaluasi auto-hide. Ringan: hanya repaint bila terlihat.
        self._tick = QTimer(self)
        self._tick.setInterval(220)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

    # ── data ─────────────────────────────────────────────────────────────

    def set_tasks(self, views) -> None:
        """Dipanggil dari thread UI saja (BUS ui=True atau timer Qt)."""
        active = [v for v in views if v.active]
        active.sort(key=lambda v: v.created_at)
        # Lupakan tanda "sedang dibatalkan" untuk task yang sudah tidak aktif.
        live_ids = {v.id for v in active}
        self._cancelling &= live_ids
        self._views = active[: self._max_chips]
        self._overflow = max(0, len(active) - len(self._views))

        if active:
            self._all_done_since = None
            if not self.isVisible():
                self.show()
        elif self._all_done_since is None:
            # Jangan langsung sembunyi — user perlu sempat melihat 100 %.
            self._all_done_since = time.monotonic()
        self.update()

    def _on_tick(self) -> None:
        if self._all_done_since is not None:
            if (time.monotonic() - self._all_done_since) * 1000 >= self._autohide_ms:
                self._all_done_since = None
                self._views = []
                self.hide()
                return
        if self.isVisible() and self._views:
            self._phase = (self._phase + 1) % len(_SPINNER)
            self.update()

    # ── interaksi ────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:                # noqa: N802
        point = QPointF(event.position())
        for task_id, chip, close_btn in self._chip_rects:
            if close_btn.contains(point):
                # Repaint DULU, baru kirim sinyal — umpan balik tidak boleh
                # menunggu pembatalan benar-benar selesai.
                self._cancelling.add(task_id)
                self.update()
                self.cancel_requested.emit(task_id)
                return
            if chip.contains(point):
                self.chip_clicked.emit(task_id)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:                 # noqa: N802
        point = QPointF(event.position())
        over = any(chip.contains(point) or btn.contains(point)
                   for _tid, chip, btn in self._chip_rects)
        self.setCursor(Qt.CursorShape.PointingHandCursor if over
                       else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    # ── render ───────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:                    # noqa: N802
        self._chip_rects = []
        if not self._views:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        pal = theme.PAL
        font = theme.mono_font(max(8, self._height - 16))
        p.setFont(font)
        metrics = p.fontMetrics()

        pad = 10.0
        gap = 8.0
        x = pad
        top = 2.0
        h = float(self._height - 4)

        for view in self._views:
            # Umpan balik INSTAN: begitu cancel event ter-set, chip langsung
            # berubah — tidak menunggu status jadi CANCELLED. Tombol tanpa
            # umpan balik instan selalu terasa rusak, bahkan saat bekerja.
            cancelling = view.cancelled or view.id in self._cancelling
            spinner = "…" if cancelling else _SPINNER[self._phase % len(_SPINNER)]
            pct = "BATAL" if cancelling else f"{int(view.progress * 100):>3d}%"
            title = view.title or view.prompt
            label = f"{spinner} {view.id} {title}"
            # Potong judul, bukan persen — angka progres tidak boleh hilang.
            max_label = 260
            if metrics.horizontalAdvance(label) > max_label:
                while label and metrics.horizontalAdvance(label + "…") > max_label:
                    label = label[:-1]
                label += "…"

            text_w = metrics.horizontalAdvance(f"{label}  {pct}")
            chip_w = text_w + 34
            chip = QRectF(x, top, chip_w, h)
            if chip.right() > self.width() - pad:
                break

            accent = QColor(pal.accent if view.status.value != "queued"
                            else pal.text_dim)
            bg = QColor(pal.panel)
            bg.setAlpha(210)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(chip, h / 2, h / 2)

            # progres sebagai isian tipis di dasar chip — tidak menambah tinggi
            if view.progress > 0:
                fill = QRectF(chip.left(), chip.bottom() - 2.0,
                              chip.width() * view.progress, 2.0)
                fc = QColor(accent)
                fc.setAlpha(200)
                p.setBrush(fc)
                p.drawRoundedRect(fill, 1.0, 1.0)

            p.setPen(QPen(QColor(pal.text)))
            p.drawText(QRectF(chip.left() + 12, chip.top(),
                              chip.width() - 34, chip.height()),
                       int(Qt.AlignmentFlag.AlignVCenter
                           | Qt.AlignmentFlag.AlignLeft),
                       f"{label}  {pct}")

            close_size = 12.0
            close_btn = QRectF(chip.right() - close_size - 8,
                               chip.center().y() - close_size / 2,
                               close_size, close_size)
            p.setPen(QPen(QColor(pal.text_dim), 1.4))
            p.drawLine(close_btn.topLeft(), close_btn.bottomRight())
            p.drawLine(close_btn.topRight(), close_btn.bottomLeft())

            # rect klik dibuat lebih longgar dari glyph agar mudah dikenai
            self._chip_rects.append(
                (view.id, chip, close_btn.adjusted(-5, -5, 5, 5)))
            x = chip.right() + gap

        if getattr(self, "_overflow", 0):
            p.setPen(QPen(QColor(pal.text_dim)))
            p.drawText(QRectF(x, top, 90, h),
                       int(Qt.AlignmentFlag.AlignVCenter
                           | Qt.AlignmentFlag.AlignLeft),
                       f"⋯ +{self._overflow} lagi")
        p.end()


__all__ = ["TaskStrip"]
