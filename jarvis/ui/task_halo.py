"""Arc progres tugas latar di cincin halo orb (AUDIT_REPORT §8.5 lapis 3).

Kenapa subclass, bukan menyunting ``jarvis/ui/orb.py``: berkas itu FROZEN
(``config/frozen_manifest.json``) dan dijaga CI. ``OrbRenderer`` hanya
dikonstruksi di satu tempat (``jarvis/ui/window.py``), jadi menukar kelasnya
adalah perubahan satu baris yang meninggalkan orb asli utuh.

Keputusan desain yang berlawanan dengan intuisi, dan disengaja:

    Orb TIDAK pernah dipindahkan ke state EXECUTING saat tugas latar berjalan.

``EXECUTING`` akan menggantikan ``LISTENING``, dan itu menghapus satu-satunya
sinyal bahwa Jarvis masih mendengarkan — padahal justru itu inti fitur ini.
Prioritas state tetap SPEAKING > LISTENING > THINKING > IDLE; progres tugas
adalah **lapisan tambahan** di atasnya.

    "Jarvis sibuk" ≠ "Jarvis tidak tersedia".
"""
from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen

from jarvis.core import config
from jarvis.ui import theme
from jarvis.ui.orb import OrbRenderer, OrbState


class TaskHaloOrb(OrbRenderer):
    """OrbRenderer + satu arc progres di cincin halo. Tidak menyentuh state."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._task_progress: float | None = None
        self._task_count = 0

    # ── API dipanggil dari thread UI (lewat BUS ui=True) ─────────────────

    def set_task_progress(self, fraction: float | None,
                          count: int = 0) -> None:
        """``None`` = tidak ada tugas aktif → arc hilang.

        Sengaja di-push dari luar, bukan membaca registry tiap frame: paint
        berjalan 60 fps dan mengunci registry sesering itu hanya membuang
        kontensi tanpa manfaat visual.
        """
        if fraction is None:
            changed = self._task_progress is not None
            self._task_progress = None
            self._task_count = 0
        else:
            value = max(0.0, min(1.0, float(fraction)))
            changed = (self._task_progress != value
                       or self._task_count != count)
            self._task_progress = value
            self._task_count = int(count)
        if changed:
            self.update()

    @property
    def task_progress(self) -> float | None:
        return self._task_progress

    # ── render ───────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:                     # noqa: N802
        super().paintEvent(event)
        if self._task_progress is None:
            return
        if not bool(config.get("ui.task_deck.progress_arc_in_halo", True)):
            return
        if not self._halo_visible():
            # Saat orb docked halo memang disembunyikan; memaksa arc muncul
            # di sana akan menabrak waveform SPEAKING.
            return
        try:
            self._paint_task_arc()
        except Exception:                                    # noqa: BLE001
            pass                                             # UI tidak boleh jatuh

    def _geometry(self) -> tuple[QPointF, float]:
        """Ulangi perhitungan geometri paintEvent induk agar arc sejajar
        persis dengan cincin halo, termasuk 'breathing' saat IDLE."""
        pos = self._cur_pos()
        diam = self._cur_diam()
        if self.state in (OrbState.IDLE, OrbState.BOOT):
            diam *= 1.0 + 0.04 * math.sin(self._phase)
        return pos, diam / 2.0

    def _paint_task_arc(self) -> None:
        halo = config.section("ui.orb.halo_aperture")
        radii = halo.get("radii", [1.32, 1.48, 1.66])
        # Cincin tengah: cukup jauh dari core agar terbaca, cukup dalam agar
        # tidak tertukar dengan tick spektral di cincin terluar.
        ratio = float(radii[len(radii) // 2] if radii else 1.48)

        pos, r = self._geometry()
        rr = r * ratio
        rect = QRectF(pos.x() - rr, pos.y() - rr, rr * 2, rr * 2)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._opacity)

        width = float(halo.get("line_thickness", [1.0])[0]) + 1.6
        # Warna dari tema, dibaca saat paint — ganti tema langsung terlihat.
        col = QColor(theme.PAL.success if self._task_progress >= 1.0
                     else theme.PAL.accent)

        track = QColor(col)
        track.setAlpha(38)
        p.setPen(QPen(track, width))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)

        arc = QColor(col)
        arc.setAlpha(235)
        p.setPen(QPen(arc, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        # 12 o'clock, searah jarum jam — sama dengan _paint_progress bawaan
        # orb, supaya dua permukaan progres tidak saling bertentangan arah.
        p.drawArc(rect, 90 * 16, -int(self._task_progress * 360 * 16))
        p.end()


__all__ = ["TaskHaloOrb"]
