"""17F desktop-local metadata manager for public monitor sources."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from jarvis.core import config
from jarvis.monitoring.source_registry_store import PersistentSourceRegistry
from jarvis.monitoring.monitor_job_store import MonitorJobRegistry
from jarvis.ui import theme


class MonitorSourceSheet(QWidget):
    """Local-only source add/select sheet; it never fetches or schedules."""

    def __init__(self, registry: PersistentSourceRegistry | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.registry = registry or PersistentSourceRegistry(
            config.base_dir() / "data" / "monitor_sources.sqlite")
        self.jobs = MonitorJobRegistry(self.registry.path.with_name("monitor_jobs.sqlite"), self.registry)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.panel};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 24)
        title = QLabel("MONITOR SOURCE — LOKAL")
        title.setFont(theme.header_font(13))
        title.setStyleSheet(f"color:{theme.PAL.accent}; background:transparent;")
        lay.addWidget(title)
        form = QFormLayout()
        self._name = QLineEdit(); self._url = QLineEdit(); self._mode = QComboBox()
        self._mode.addItems(["rss", "api", "html"])
        self._rate = QSpinBox(); self._rate.setRange(5, 86400); self._rate.setValue(60)
        form.addRow("Nama", self._name); form.addRow("URL publik HTTPS", self._url)
        form.addRow("Mode", self._mode); form.addRow("Interval minimum (detik)", self._rate)
        lay.addLayout(form)
        self._selected = QComboBox()
        self._schedule = QLineEdit("*/15 * * * *")
        self._delivery = QComboBox(); self._delivery.addItems(["desktop_only", "on_change", "daily_digest", "both"])
        form.addRow("Source aktif", self._selected)
        form.addRow("Jadwal monitor", self._schedule)
        form.addRow("Delivery", self._delivery)
        self._summary = QLabel("")
        self._summary.setWordWrap(True); self._summary.setFont(theme.mono_font(10))
        self._summary.setStyleSheet(f"color:{theme.PAL.text}; background:transparent;")
        lay.addWidget(self._summary)
        row = QHBoxLayout()
        add = QPushButton("TAMBAH"); add.clicked.connect(self._add_from_fields)
        select = QPushButton("PILIH"); select.clicked.connect(self._select_from_box)
        register = QPushButton("DAFTAR JOB"); register.clicked.connect(self._register_from_fields)
        enable = QPushButton("AKTIFKAN JOB"); enable.clicked.connect(lambda: self._set_selected_job_enabled(True))
        disable = QPushButton("NONAKTIFKAN JOB"); disable.clicked.connect(lambda: self._set_selected_job_enabled(False))
        clear = QPushButton("HAPUS PILIHAN"); clear.clicked.connect(self._clear)
        for button in (add, select, register, enable, disable, clear):
            button.setFixedHeight(32); row.addWidget(button)
        row.addStretch(); lay.addLayout(row)
        self.refresh(); self.hide()

    def summary_text(self) -> str:
        return self._summary.text()

    @staticmethod
    def _job_state_text(job) -> str:
        enabled = "Aktif" if job.enabled else "Dinonaktifkan"
        status = {
            "not_started": "Belum pernah berjalan",
            "ok": "Pemeriksaan terakhir aman",
            "source_failed": "Gagal mengambil sumber",
        }.get(job.last_status, "Status aman tidak tersedia")
        return f"{enabled} | {status}"

    def refresh(self) -> None:
        items = self.registry.public_view()
        selected = self.registry.selected()
        self._selected.clear()
        for item in items:
            self._selected.addItem(item["name"], item["id"])
            if selected is not None and item["id"] == selected.id:
                self._selected.setCurrentIndex(self._selected.count() - 1)
        rows = [f"• {item['name']} [{item['mode']}] — {item['url']}" for item in items]
        jobs = [
            f"Job: {job.source} | {job.schedule} | {job.delivery_mode} | {self._job_state_text(job)}"
            for job in self.jobs.list()
        ]
        prefix = f"Dipilih: {selected.name}\n" if selected else "Belum ada source dipilih.\n"
        sources_text = "\n".join(rows) if rows else "Belum ada source tersimpan."
        self._summary.setText(prefix + sources_text + ("\n" + "\n".join(jobs) if jobs else ""))

    def add_source(self, name: str, url: str, mode: str, rate_limit_s: int) -> bool:
        try:
            self.registry.add(name, url, mode, rate_limit_s=int(rate_limit_s))
        except (TypeError, ValueError):
            self._summary.setText("Source tidak valid.")
            return False
        self.refresh()
        return True

    def select_source(self, source_id: str) -> bool:
        try:
            self.registry.select(source_id)
        except ValueError:
            return False
        self.refresh()
        return True

    def clear_selection(self) -> bool:
        self.registry.clear_selection()
        self.refresh()
        return True

    def register_selected_job(self, schedule: str, delivery_mode: str):
        """Persist local monitor-only registration; never runs scheduler here."""
        try:
            job = self.jobs.register_selected(schedule, delivery_mode)
        except ValueError:
            self._summary.setText("Job monitor tidak valid atau source belum dipilih.")
            return None
        self.refresh()
        return job

    def _add_from_fields(self) -> None:
        self.add_source(self._name.text(), self._url.text(), self._mode.currentText(), self._rate.value())

    def _select_from_box(self) -> None:
        source_id = self._selected.currentData()
        if source_id:
            self.select_source(str(source_id))

    def set_job_enabled(self, job_id: str, enabled: bool) -> bool:
        """Toggle only an existing local monitor registration; never starts work."""
        try:
            self.jobs.set_enabled(job_id, enabled)
        except ValueError:
            self._summary.setText("Job monitor tidak ditemukan.")
            return False
        self.refresh()
        return True

    def _register_from_fields(self) -> None:
        self.register_selected_job(self._schedule.text(), self._delivery.currentText())

    def _set_selected_job_enabled(self, enabled: bool) -> None:
        selected = self.registry.selected()
        if selected is None:
            self._summary.setText("Belum ada source dipilih.")
            return
        matching = [job for job in self.jobs.list() if job.source_id == selected.id]
        if not matching:
            self._summary.setText("Belum ada job untuk source dipilih.")
            return
        self.set_job_enabled(matching[-1].id, enabled)

    def _clear(self) -> None:
        self.clear_selection()

    def open_centered(self, parent_w: int, parent_h: int) -> None:
        self.setGeometry((parent_w - 580) // 2, int(parent_h * .16), 580, 400)
        self.refresh(); self.show(); self.raise_()


__all__ = ["MonitorSourceSheet"]
