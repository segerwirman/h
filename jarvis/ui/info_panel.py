"""InfoPanel (MK50 §7.2) — kartu informasi interaktif di ContentStage.

Menampilkan kartu berita (§6), cuaca, dan hasil pencarian: judul + isi +
sumber + timestamp. Data masuk lewat BUS event ``info.card``:

    BUS.publish("info.card", kind="news", title="...", lines=[...],
                source="...", ts="...")

Panel pasif — tidak menarik jaringan sendiri; produser (tool web, action
legacy) yang mendorong kartu. Token warna dari theme (FROZEN — dibaca saja).
"""
from __future__ import annotations

import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QFrame, QLabel, QScrollArea, QVBoxLayout,
                             QWidget)

from jarvis.core import config, log
from jarvis.core.bus import BUS
from jarvis.ui import theme

_logger = log.get("ui.info_panel")

MAX_CARDS = 12


class _InfoCard(QFrame):
    def __init__(self, kind: str, title: str, lines: list[str],
                 source: str, ts: str):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Kartu borderless (permintaan §UI): tanpa garis kotak, hanya latar
        # halus + aksen tipis di kiri agar tetap terbaca sebagai kartu.
        show_border = bool(config.get("ui.info_panel.card_border", False))
        border = (f"border: 1px solid {theme.PAL.accent_dim};" if show_border
                  else "border: none;")
        self.setStyleSheet(
            f"QFrame {{ background: {theme.PAL.panel};"
            f" {border} border-radius: 6px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(4)

        head = QLabel(f"{kind.upper()} — {title}" if title else kind.upper())
        head.setFont(theme.header_font(10))
        head.setStyleSheet(f"color: {theme.PAL.accent};"
                           " background: transparent; letter-spacing: 1px;")
        head.setWordWrap(True)
        lay.addWidget(head)

        for line in lines[:12]:
            lab = QLabel(str(line))
            lab.setFont(theme.mono_font(9))
            lab.setStyleSheet(f"color: {theme.PAL.text};"
                              " background: transparent;")
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            lay.addWidget(lab)

        meta_bits = [b for b in (source, ts) if b]
        if meta_bits:
            meta = QLabel("  ·  ".join(meta_bits))
            meta.setFont(theme.mono_font(8))
            meta.setStyleSheet(f"color: {theme.PAL.text_dim};"
                               " background: transparent;")
            meta.setWordWrap(True)
            lay.addWidget(meta)


class InfoPanel(QWidget):
    """Registrasi ContentStage ``"info"`` — cuaca, berita, hasil pencarian."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.setSpacing(10)

        title = QLabel("INFO")
        title.setFont(theme.header_font(12))
        title.setStyleSheet(f"color: {theme.PAL.text};"
                            " background: transparent; letter-spacing: 4px;")
        outer.addWidget(title)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QScrollBar:vertical {{ background: transparent; width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {theme.PAL.text_dim};"
            " border-radius: 3px; }")
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        self._cards_lay = QVBoxLayout(body)
        self._cards_lay.setContentsMargins(0, 0, 0, 0)
        self._cards_lay.setSpacing(10)
        self._cards_lay.addStretch()
        self._scroll.setWidget(body)
        outer.addWidget(self._scroll, stretch=1)

        self._empty = QLabel("Belum ada informasi — hasil berita/cuaca/"
                             "pencarian akan tampil di sini.")
        self._empty.setFont(theme.mono_font(9))
        self._empty.setStyleSheet(f"color: {theme.PAL.text_dim};"
                                  " background: transparent;")
        self._empty.setWordWrap(True)
        outer.addWidget(self._empty)

        # marshal ke UI thread oleh BUS (ui=True) — produser boleh dari
        # worker thread mana pun.
        BUS.subscribe("info.card", self._on_card, ui=True)

    # ── kartu ─────────────────────────────────────────────────────────────

    def _on_card(self, data: dict) -> None:
        try:
            self.add_card(
                kind=str(data.get("kind", "info")),
                title=str(data.get("title", "")),
                lines=[str(x) for x in (data.get("lines") or [])],
                source=str(data.get("source", "")),
                ts=str(data.get("ts", "")) or datetime.datetime.now()
                .strftime("%d %b %Y %H:%M"),
            )
        except Exception as e:                               # noqa: BLE001
            _logger.warning("info_panel.card_failed", error=str(e)[:100])

    def add_card(self, kind: str, title: str, lines: list[str],
                 source: str = "", ts: str = "") -> None:
        card = _InfoCard(kind, title, lines, source, ts)
        self._cards_lay.insertWidget(0, card)
        self._empty.hide()
        limit = int(config.get("ui.info_panel.max_cards", MAX_CARDS))
        while self._cards_lay.count() - 1 > limit:
            item = self._cards_lay.takeAt(self._cards_lay.count() - 2)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    @property
    def card_count(self) -> int:
        return self._cards_lay.count() - 1
