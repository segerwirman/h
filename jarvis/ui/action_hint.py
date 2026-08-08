"""Hint melayang saat ikon ActionPanel disorot.

Sengaja BUKAN ``QToolTip``: tooltip bawaan membawa delay OS, styling OS, dan
sudut tajam yang terlihat asing di UI sinematik ini.

``jarvis/ui/actionpanel.py`` semi-frozen dan **tidak punya sinyal hover**
(diperiksa: nol ``enterEvent``/``leaveEvent``/``installEventFilter``), jadi
hover diambil lewat ``eventFilter`` yang dipasang DARI LUAR — pola yang sama
dipakai ``calorie_popup`` terhadap panel visi. Berkas itu tidak disentuh.

Catatan warna: user meminta teks PUTIH dan spesifikasi menyarankan menambah
token ``text_bright`` ke ``theme.py``. Berkas itu **FROZEN** (manifest +
CI), jadi dipakai ``PAL.orb_core`` — token paling terang yang memang sudah
ada di setiap preset (cyan_gold ``#eafcff``, stealth_dark ``#e8eaec``,
alert_red ``#fff0f0``). Hasilnya putih di mata, dan tetap ikut berganti tema.
Tidak ada warna yang di-hardcode di sini.
"""
from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QPropertyAnimation, Qt, QTimer
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

from jarvis.core import config, log
from jarvis.ui import theme

_logger = log.get("ui.action_hint")

HINT_TEXT: dict[str, str] = {
    "vision": "Panel Visi (F6)",
    "upload": "Unggah Berkas (F3)",
    "spotify": "Spotify",
    "studio": "Content Studio",
    "home": "Smart Home",
    # awareness dipensiunkan dari ikon default (UI U1) tetapi tetap didukung
    # lewat opt-in config.yaml, jadi hint-nya sengaja dipertahankan.
    "awareness": "Kesadaran Layar",
    "focus_mode": "Mode Fokus (F7)",
    "palette": "Tema",
    "timeline": "Linimasa (F5)",
    "capabilities": "Skill & Tool",
    "messaging": "Pesan",
    "gateway_ops": "Gateway",
    "settings": "Pengaturan",
    "tasks": "Tugas Latar",
}


class ActionHint(QLabel):
    """Label melayang di atas ikon yang disorot."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        c = config.section("ui.action_panel.hint")
        self._delay_in = int(c.get("delay_in_ms", 120))
        self._delay_out = int(c.get("delay_out_ms", 80))
        self._offset = int(c.get("offset_px", 10))
        # Durasi fade diambil dari motion yang sudah ada — bukan angka baru.
        self._fade_ms = int(config.get("motion.transition_min_ms", 200))

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hide()

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)

        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(self._reveal)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._conceal)

        self._target: QWidget | None = None
        self._text = ""

    # ── gaya ─────────────────────────────────────────────────────────────

    def _restyle(self) -> None:
        """Dibaca ulang tiap tampil — ganti tema langsung terlihat."""
        pal = theme.PAL
        self.setFont(theme.mono_font(9))
        self.setStyleSheet(
            f"QLabel {{"
            f" color: {pal.orb_core};"
            f" background: {pal.panel};"
            f" border: 1px solid {pal.accent};"
            f" padding: 4px 10px;"
            f"}}")

    # ── hover ────────────────────────────────────────────────────────────

    def request(self, widget: QWidget, text: str) -> None:
        """Sorot masuk. Delay mencegah kedip saat kursor sekadar lewat."""
        if not text:
            return
        self._target = widget
        self._text = text
        self._hide_timer.stop()
        if self.isVisible():
            self._reveal()                  # sudah tampil → pindah langsung
        else:
            self._show_timer.start(self._delay_in)

    def release(self, widget: QWidget) -> None:
        if widget is not self._target:
            return
        self._show_timer.stop()
        self._hide_timer.start(self._delay_out)

    def dismiss(self) -> None:
        self._show_timer.stop()
        self._hide_timer.stop()
        self._conceal()

    # ── render ───────────────────────────────────────────────────────────

    def _reveal(self) -> None:
        target = self._target
        if target is None or not target.isVisible():
            return
        self._restyle()
        self.setText(self._text)
        self.adjustSize()
        self._reposition(target)
        self.show()
        self.raise_()
        self._fade_to(1.0)

    def _conceal(self) -> None:
        self._fade_to(0.0, then_hide=True)

    def _fade_to(self, value: float, then_hide: bool = False) -> None:
        self._anim.stop()
        try:
            self._anim.finished.disconnect()
        except TypeError:
            pass
        self._anim.setDuration(self._fade_ms)
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(value)
        if then_hide:
            self._anim.finished.connect(self.hide)
        self._anim.start()

    def _reposition(self, target: QWidget) -> None:
        """Tepat di atas ikon, dijepit agar tidak pernah keluar jendela."""
        parent = self.parentWidget()
        if parent is None:
            return

        margin = 4
        # Menjepit POSISI saja tidak cukup: hint yang lebih lebar dari
        # jendela tetap terpotong ke mana pun ia digeser. Lebarnya dibatasi
        # dulu, dan teks dibungkus bila perlu.
        max_w = max(40, parent.width() - 2 * margin)
        if self.width() > max_w:
            self.setWordWrap(True)
            self.setFixedWidth(max_w)
            self.adjustSize()
            self.setFixedWidth(max_w)

        top_left = target.mapTo(parent, QPoint(0, 0))
        x = top_left.x() + (target.width() - self.width()) // 2
        y = top_left.y() - self.height() - self._offset

        x = max(margin, min(x, parent.width() - self.width() - margin))
        if y < margin:                      # tak muat di atas → taruh di bawah
            y = top_left.y() + target.height() + self._offset
        y = max(margin, min(y, parent.height() - self.height() - margin))
        self.move(x, y)


def install(action_panel, parent: QWidget | None = None) -> ActionHint | None:
    """Pasang hint ke seluruh tombol ActionPanel. ``None`` bila dimatikan."""
    if not bool(config.get("ui.action_panel.hint.enabled", True)):
        return None
    buttons = getattr(action_panel, "_buttons", None)
    if not buttons:
        _logger.info("action_hint.no_buttons")
        return None

    host = parent or action_panel.parentWidget() or action_panel
    hint = ActionHint(host)

    from PyQt6.QtCore import QObject

    class _Filter(QObject):
        def eventFilter(self, obj, event):  # noqa: N802
            etype = event.type()
            if etype == QEvent.Type.Enter:
                hint.request(obj, HINT_TEXT.get(_name_of(obj), ""))
            elif etype in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress):
                hint.release(obj)
            elif etype == QEvent.Type.Hide:
                hint.dismiss()
            return False

    def _name_of(widget) -> str:
        for name, btn in buttons.items():
            if btn is widget:
                return name
        return ""

    flt = _Filter(hint)
    hint._filter = flt                      # cegah GC
    for btn in buttons.values():
        btn.installEventFilter(flt)
    _logger.info("action_hint.installed", icons=len(buttons))
    return hint


__all__ = ["ActionHint", "HINT_TEXT", "install"]
