"""Extracted UI panel implementation; re-exported by jarvis.ui.panels."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from jarvis.core import log
from jarvis.ui import theme

_logger = log.get("ui.panels")

from jarvis.ui.panel_widgets import (
    _GroupRow,
    _HubRow,
    _ImageGenControls,
    _SkillRow,
)

class CapabilitiesPanel(QWidget):
    """3 pane (PARITY §5.3): tab + search + list kiri, detail kanan."""

    TABS = ("Skills", "Tools", "MCP", "Browse Hub")
    _PLACEHOLDER = {"Skills": 'Try "github"', "Tools": 'Try "patch"'}

    def __init__(self, parent: QWidget | None = None,
                 service=None):
        super().__init__(parent)
        if service is None:
            from jarvis.agent import capability_service as service
        self._service = service
        self._sort_desc = True
        self._selected: str | None = None
        self._rows: dict[str, _SkillRow] = {}

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.base};")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 12)
        root.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("CAPABILITIES")
        title.setFont(theme.header_font(14))
        title.setStyleSheet(f"color: {theme.PAL.accent}; background: transparent;"
                            "letter-spacing: 4px;")
        title_row.addWidget(title)
        title_row.addStretch()
        self._close_button = QPushButton("TUTUP")
        self._close_button.setFont(theme.mono_font(8))
        self._close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_button.setStyleSheet(
            f"QPushButton {{ background: {theme.PAL.panel}; color: "
            f"{theme.PAL.accent}; border: 1px solid {theme.PAL.accent_dim};"
            " border-radius: 4px; padding: 5px 12px; }}")
        self._close_button.clicked.connect(self.hide)
        title_row.addWidget(self._close_button)
        root.addLayout(title_row)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        root.addWidget(split, stretch=1)

        # ── pane kiri ────────────────────────────────────────────────────────
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        ll.setSpacing(6)

        self._search = QLineEdit()
        self._search.setFont(theme.mono_font(9))
        self._search.setPlaceholderText(self._PLACEHOLDER["Skills"])
        self._search.setStyleSheet(
            f"QLineEdit {{ background: {theme.PAL.panel}; color: {theme.PAL.text};"
            f" border: 1px solid {theme.PAL.panel}; border-radius: 4px;"
            f" padding: 6px 10px; }}")
        self._search.textChanged.connect(lambda _: self._reload_list())
        ll.addWidget(self._search)

        tabs = QHBoxLayout()
        tabs.setSpacing(4)
        self._tab_buttons: dict[str, QPushButton] = {}
        for tab in self.TABS:
            b = QPushButton(tab)
            b.setFont(theme.mono_font(8))
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, t=tab: self._set_tab(t))
            self._tab_buttons[tab] = b
            tabs.addWidget(b)
        tabs.addStretch()
        ll.addLayout(tabs)

        self._sort_btn = QPushButton("↓ Most used")
        self._sort_btn.setFont(theme.mono_font(8))
        self._sort_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sort_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            f" color: {theme.PAL.text_dim}; text-align: left; }}"
            f"QPushButton:hover {{ color: {theme.PAL.accent}; }}")
        self._sort_btn.clicked.connect(self._flip_sort)
        ll.addWidget(self._sort_btn)

        self._list_host = QWidget()
        self._list_lay = QVBoxLayout(self._list_host)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(4)
        self._list_lay.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        scroll.setWidget(self._list_host)
        ll.addWidget(scroll, stretch=1)

        note = QLabel("Changes apply to new sessions.")
        note.setFont(theme.mono_font(7))
        note.setAlignment(Qt.AlignmentFlag.AlignRight)
        note.setStyleSheet(f"color: {theme.PAL.text_dim}; background: transparent;")
        ll.addWidget(note)

        split.addWidget(left)

        # ── pane kanan (detail + aksi curator §8) ───────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        self._detail = QTextBrowser()
        self._detail.setFont(theme.mono_font(9))
        self._detail.setOpenExternalLinks(False)
        self._detail.setStyleSheet(
            f"QTextBrowser {{ background: {theme.PAL.panel};"
            f" color: {theme.PAL.text}; border: none; border-radius: 4px;"
            f" padding: 14px; }}")
        rl.addWidget(self._detail, stretch=1)

        # Selektor Image Generation interaktif — hanya tampil saat grup
        # 'image_generation' dipilih di tab Tools.
        self._image_controls = _ImageGenControls()
        self._image_controls.hide()
        rl.addWidget(self._image_controls)

        act_row = QHBoxLayout()
        self._pin_btn = QPushButton("Pin")
        self._pin_btn.setFont(theme.mono_font(8))
        self._pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pin_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.PAL.panel};"
            f" color: {theme.PAL.accent}; border: none; border-radius: 4px;"
            f" padding: 5px 12px; }}")
        self._pin_btn.clicked.connect(self._on_pin)
        self._pin_btn.hide()
        act_row.addWidget(self._pin_btn)
        self._archive_btn = QPushButton("Archive")
        self._archive_btn.setFont(theme.mono_font(8))
        self._archive_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._archive_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.PAL.panel};"
            f" color: {theme.PAL.alert}; border: none; border-radius: 4px;"
            f" padding: 5px 12px; }}")
        self._archive_btn.clicked.connect(self._on_archive)
        self._archive_btn.hide()
        act_row.addWidget(self._archive_btn)
        act_row.addStretch()
        rl.addLayout(act_row)

        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        self._set_tab("Skills")

    # ── tab ──────────────────────────────────────────────────────────────────

    def _set_tab(self, tab: str) -> None:
        self._tab = tab
        for name, btn in self._tab_buttons.items():
            active = name == tab
            btn.setChecked(active)
            color = theme.PAL.accent if active else theme.PAL.text_dim
            btn.setStyleSheet(
                "QPushButton { background: transparent; border: none;"
                f" color: {color}; padding: 3px 8px;"
                f" border-bottom: 1px solid {color if active else 'transparent'}; }}")
        self._search.setPlaceholderText(
            self._PLACEHOLDER.get(tab, "Search"))
        self._reload_list()

    def _flip_sort(self) -> None:
        self._sort_desc = not self._sort_desc
        self._sort_btn.setText(("↓ " if self._sort_desc else "↑ ") + "Most used")
        self._reload_list()

    # ── data ─────────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        self._reload_list()

    def showEvent(self, event) -> None:                      # data segar tiap buka
        super().showEvent(event)
        self.refresh()

    def _clear_list(self) -> None:
        self._rows.clear()
        while self._list_lay.count() > 1:                    # sisakan stretch
            item = self._list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _empty_state(self, text: str) -> None:
        self._clear_list()
        lbl = QLabel(text)
        lbl.setFont(theme.mono_font(9))
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {theme.PAL.text_dim}; background: transparent;"
                          " padding: 18px;")
        self._list_lay.insertWidget(0, lbl)
        self._detail.setPlainText("")
        self._image_controls.hide()
        self._pin_btn.hide()
        self._archive_btn.hide()

    def _reload_list(self) -> None:
        if self._tab == "Tools":
            self._reload_tools()
            return
        if self._tab == "MCP":
            self._reload_mcp()
            return
        if self._tab == "Browse Hub":
            self._reload_hub()
            return

        try:
            items = self._service.list_skills(self._search.text().strip())
            items = self._service.sort_skills(items, self._sort_desc)
        except Exception as e:                               # noqa: BLE001
            _logger.error("panels.skills_load_failed", error=str(e)[:120])
            self._empty_state("Gagal memuat skill — lihat log.")
            return

        self._clear_list()
        self._tab_buttons["Skills"].setText(
            f"Skills {self._service.skill_count()}")
        if not items:
            self._empty_state("Belum ada skill." if not self._search.text()
                              else "Tidak ada skill yang cocok.")
            return
        for skill in items:
            row = _SkillRow(skill)
            row.selected.connect(self._show_detail)
            row.toggle_requested.connect(self._on_toggle)
            self._rows[skill["name"]] = row
            self._list_lay.insertWidget(self._list_lay.count() - 1, row)
        if self._selected in self._rows:
            self._rows[self._selected].set_highlight(True)
            self._show_detail(self._selected)
        elif items:
            self._show_detail(items[0]["name"])

    def _reload_tools(self) -> None:
        try:
            items = self._service.list_tool_groups(self._search.text().strip())
            items = self._service.sort_tool_groups(items, self._sort_desc)
        except Exception as e:                               # noqa: BLE001
            _logger.error("panels.tools_load_failed", error=str(e)[:120])
            self._empty_state("Gagal memuat grup tool — lihat log.")
            return

        self._clear_list()
        self._group_items = {g["id"]: g for g in items}
        self._tab_buttons["Tools"].setText(
            f"Tools {self._service.tool_group_count()}")
        if not items:
            self._empty_state("Tidak ada grup yang cocok.")
            return
        for group in items:
            row = _GroupRow(group)
            row.selected.connect(self._show_group_detail)
            row.toggle_requested.connect(self._on_group_toggle)
            self._rows[group["id"]] = row
            self._list_lay.insertWidget(self._list_lay.count() - 1, row)
        first = self._selected if self._selected in self._rows \
            else items[0]["id"]
        self._show_group_detail(first)

    def _reload_mcp(self) -> None:
        try:
            servers = self._service.list_mcp_servers()
        except Exception as e:                               # noqa: BLE001
            _logger.error("panels.mcp_load_failed", error=str(e)[:120])
            self._empty_state("Gagal membaca server MCP — lihat log.")
            return
        self._clear_list()
        if not servers:
            self._empty_state(
                "Belum ada server MCP. Tambahkan di config.yaml:\n\n"
                "mcp:\n  servers:\n    - name: fs\n      command: npx\n"
                "      args: [-y, \"@modelcontextprotocol/"
                "server-filesystem\", \"D:/data\"]\n\n"
                "Agent memakainya lewat tool mcp_list / mcp_call.")
            return
        self._mcp_items = {s["name"]: s for s in servers}
        for s in servers:
            row = _GroupRow({
                "id": s["name"], "name": s["name"],
                "subtitle": s["state"], "calls": 0, "tool_calls": {},
                "available": True, "enabled": s["enabled"]})
            row.selected.connect(self._show_mcp_detail)
            row.toggle_requested.connect(self._on_mcp_toggle)
            self._rows[s["name"]] = row
            self._list_lay.insertWidget(self._list_lay.count() - 1, row)
        first = self._selected if self._selected in self._rows \
            else servers[0]["name"]
        self._show_mcp_detail(first)

    def _show_mcp_detail(self, name: str) -> None:
        self._image_controls.hide()
        self._pin_btn.hide()
        self._archive_btn.hide()
        for row_id, row in self._rows.items():
            row.set_highlight(row_id == name)
        self._selected = name
        s = getattr(self, "_mcp_items", {}).get(name)
        if s is None:
            self._detail.setPlainText("")
            return
        tools = "\n".join(f"  - {t}" for t in s["tools"]) or "  (belum ada — "\
            "connect saat tool mcp_list/mcp_call dipakai agent)"
        err = f"\nError : {s['error']}" if s.get("error") else ""
        self._detail.setPlainText(
            f"{s['name']}\n[{s['state']}]\n\n"
            f"Command: {s['command']} {' '.join(s['args'])}{err}\n\n"
            f"Tools:\n{tools}")

    def _on_mcp_toggle(self, name: str, enabled: bool) -> None:
        try:
            ok = self._service.set_mcp_enabled(name, enabled)
            if not ok:
                _logger.error("panels.mcp_toggle_rejected", server=name)
        except Exception as e:                               # noqa: BLE001
            _logger.error("panels.mcp_toggle_failed", error=str(e)[:120])
        self._reload_list()

    def _reload_hub(self) -> None:
        try:
            items = self._service.list_hub_skills(
                self._search.text().strip())
        except Exception as e:                               # noqa: BLE001
            _logger.error("panels.hub_load_failed", error=str(e)[:120])
            self._empty_state("Gagal membaca katalog hub — lihat log.")
            return
        self._clear_list()
        if not items:
            self._empty_state("Katalog hub kosong — cek skills.hub_sources "
                              "di config.yaml." if not self._search.text()
                              else "Tidak ada skill hub yang cocok.")
            return
        self._hub_items = {s["name"]: s for s in items}
        for s in items:
            row = _HubRow(s)
            row.selected.connect(self._show_hub_detail)
            row.install_requested.connect(self._on_hub_install)
            self._rows[s["name"]] = row
            self._list_lay.insertWidget(self._list_lay.count() - 1, row)
        first = self._selected if self._selected in self._rows \
            else items[0]["name"]
        self._show_hub_detail(first)

    def _show_hub_detail(self, name: str) -> None:
        self._image_controls.hide()
        self._pin_btn.hide()
        self._archive_btn.hide()
        for row_id, row in self._rows.items():
            row.set_highlight(row_id == name)
        self._selected = name
        s = getattr(self, "_hub_items", {}).get(name)
        if s is None:
            self._detail.setPlainText("")
            return
        status = "terinstal" if s["installed"] else "belum terinstal"
        self._detail.setPlainText(
            f"{s['name']}\n[{s['category']} · {status}]\n\n"
            f"{s['description']}\n\nSumber: {s['source_path']}")

    def _on_hub_install(self, name: str) -> None:
        try:
            ok, msg = self._service.install_hub_skill(name)
            if not ok:
                _logger.warning("panels.hub_install_rejected", msg=msg)
        except Exception as e:                               # noqa: BLE001
            _logger.error("panels.hub_install_failed", error=str(e)[:120])
        self._reload_list()

    def _on_group_toggle(self, gid: str, enabled: bool) -> None:
        ok = False
        try:
            ok = self._service.set_group_enabled(gid, enabled)
        except Exception as e:                               # noqa: BLE001
            _logger.error("panels.group_toggle_failed", error=str(e)[:120])
        if not ok:
            _logger.error("panels.group_toggle_rejected", group=gid)
        self._reload_list()

    def _show_group_detail(self, gid: str) -> None:
        self._pin_btn.hide()
        self._archive_btn.hide()
        for row_id, row in self._rows.items():
            row.set_highlight(row_id == gid)
        self._selected = gid
        g = getattr(self, "_group_items", {}).get(gid)
        if g is None:
            self._detail.setPlainText("")
            self._image_controls.hide()
            return
        # Grup Image Generation → tampilkan selektor provider/model/tier.
        is_image = gid == "image_generation"
        if is_image:
            self._image_controls.reload()
        self._image_controls.setVisible(is_image)
        status = []
        if not g["available"]:
            status.append("unavailable")
        if not g["enabled"]:
            status.append("disabled")
        # chip monospace per tool (§5.6): [read_file ×682] — hanya ×N > 0
        chips = "  ".join(
            f"[{t} ×{n}]" if n > 0 else f"[{t}]"
            for t, n in sorted(g["tool_calls"].items())) or "—"
        self._detail.setPlainText(
            f"{g['name']}\n{g['subtitle']}\n"
            + (f"[{' · '.join(status)}]\n" if status else "")
            + (f"\nAlasan: {g.get('availability_reason')}\n"
               if g.get("availability_reason") else "")
            + f"\nTotal calls: {g['calls']}\n\n{chips}")

    # ── interaksi ────────────────────────────────────────────────────────────

    def _on_toggle(self, name: str, enabled: bool) -> None:
        ok = False
        try:
            ok = self._service.set_skill_enabled(name, enabled)
        except Exception as e:                               # noqa: BLE001
            _logger.error("panels.toggle_failed", error=str(e)[:120])
        if not ok:
            _logger.error("panels.toggle_rejected", name=name)
        self._reload_list()

    def _on_pin(self) -> None:
        if self._selected:
            try:
                d = self._service.skill_detail(self._selected) or {}
                self._service.set_skill_pinned(self._selected,
                                               not d.get("pinned"))
            except Exception as e:                           # noqa: BLE001
                _logger.error("panels.pin_failed", error=str(e)[:120])
            self._reload_list()

    def _on_archive(self) -> None:
        if self._selected:
            try:
                ok, msg = self._service.archive_skill(self._selected)
                if not ok:
                    _logger.warning("panels.archive_rejected", msg=msg)
            except Exception as e:                           # noqa: BLE001
                _logger.error("panels.archive_failed", error=str(e)[:120])
            self._selected = None
            self._reload_list()

    def _show_detail(self, name: str) -> None:
        self._image_controls.hide()
        for row_name, row in self._rows.items():
            row.set_highlight(row_name == name)
        self._selected = name
        try:
            d = self._service.skill_detail(name)
        except Exception:                                    # noqa: BLE001
            d = None
        if d is None:
            self._detail.setPlainText("")
            self._pin_btn.hide()
            self._archive_btn.hide()
            return
        is_learned = d["provenance"] == "agent"
        self._pin_btn.setVisible(is_learned)
        self._pin_btn.setText("Unpin" if d.get("pinned") else "Pin")
        self._archive_btn.setVisible(is_learned)
        badges = [d["category"]]
        if is_learned:
            badges.append("learned")
        if d.get("pinned"):
            badges.append("pinned")
        if d.get("lifecycle") == "stale":
            badges.append("stale")
        if not d["enabled"]:
            badges.append("disabled")
        counters = f"use ×{d['use']} · view ×{d['view']} · patch ×{d['patch']}"
        triggers = ", ".join(d.get("triggers") or []) or "—"
        self._detail.setPlainText(
            f"{d['name']}\n[{' · '.join(badges)}]\n\n"
            f"{d['description']}\n\n"
            f"Triggers : {triggers}\n"
            f"Counter  : {counters}\n\n"
            f"{'─' * 40}\n{d['body']}")

    def open_centered(self, parent_w: int, parent_h: int) -> None:
        """Buka capabilities sebagai sheet lokal, bukan ContentStage legacy."""
        width, height = min(980, max(720, parent_w - 80)), \
            min(660, max(500, parent_h - 80))
        self.refresh()
        self.setGeometry((parent_w - width) // 2, (parent_h - height) // 2,
                         width, height)
        self.show()
        self.raise_()
