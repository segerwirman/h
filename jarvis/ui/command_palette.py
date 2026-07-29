"""CommandPalette — one entry point for voice and text commands (redesign §12).

Fuzzy-matches against the command registry, recent actions, procedural
macros, and known apps/sites (``jarvis.core.command_palette.CommandPaletteModel``
does the ranking — this is a thin Qt view). Every candidate shows its
confidence and source; a candidate below the confidence threshold requires
a second Enter to confirm instead of running immediately, and destructive
candidates are visually flagged. This widget never executes anything
itself — it only emits the chosen candidate for the caller to dispatch.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from jarvis.core.command_palette import LOW_CONFIDENCE_THRESHOLD, CommandPaletteModel
from jarvis.ui import theme


class CommandPalette(QWidget):
    activated = pyqtSignal(object)   # PaletteCandidate

    def __init__(self, parent: QWidget, model: CommandPaletteModel | None = None):
        super().__init__(parent)
        self.model = model or CommandPaletteModel()
        self._pending_low_confidence = None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.panel};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Command palette — type to search…")
        self._input.setFont(theme.mono_font(11))
        self._input.setStyleSheet(
            f"QLineEdit {{ background: {theme.PAL.base}; color: {theme.PAL.text};"
            f" border: none; padding: 8px; }}")
        self._input.textEdited.connect(self._refresh)
        self._input.returnPressed.connect(self._activate_current)
        lay.addWidget(self._input)

        self._list = QListWidget()
        self._list.setFont(theme.mono_font(10))
        self._list.setStyleSheet(
            f"QListWidget {{ background: transparent; color: {theme.PAL.text}; border: none; }}"
            f"QListWidget::item {{ padding: 4px 2px; }}"
            f"QListWidget::item:selected {{ background: {theme.PAL.accent_dim}; }}")
        self._list.itemActivated.connect(lambda _item: self._activate_current())
        lay.addWidget(self._list, stretch=1)
        self.hide()

    def open_centered(self, parent_w: int, parent_h: int) -> None:
        w, h = 520, 360
        self.setGeometry((parent_w - w) // 2, int(parent_h * 0.18), w, h)
        self._input.clear()
        self._pending_low_confidence = None
        self._refresh("")
        self.show()
        self.raise_()
        self._input.setFocus()

    def _refresh(self, text: str) -> None:
        self._list.clear()
        for cand in self.model.query(text):
            marker = "  ⚠ destructive" if cand.is_destructive else ""
            low = ("  (low confidence — Enter again to confirm)"
                  if cand.confidence < LOW_CONFIDENCE_THRESHOLD else "")
            item = QListWidgetItem(f"{cand.label}   ·  {cand.source} {cand.confidence:.2f}{marker}{low}")
            item.setData(Qt.ItemDataRole.UserRole, cand)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)

    def _activate_current(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        cand = item.data(Qt.ItemDataRole.UserRole)
        if cand.confidence < LOW_CONFIDENCE_THRESHOLD and self._pending_low_confidence is not cand:
            self._pending_low_confidence = cand
            return   # first Enter on a low-confidence pick only arms it
        self._pending_low_confidence = None
        self.hide()
        self.activated.emit(cand)
