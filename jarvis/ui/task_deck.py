"""Task Deck — panel penuh tugas latar (AUDIT_REPORT §8.5 lapis 2).

Didaftarkan ke ``ContentStage`` lewat pola yang sudah ada:

    stage.register("tasks", TaskDeckPanel())

Jejak langkah dibaca dari ``data/logs/tools.jsonl``. Berkas itu tumbuh terus
(rollup di 5 MiB), jadi pembacaannya **inkremental**: offset byte terakhir
disimpan, dan tiap refresh hanya membaca ekor yang baru. Pembacaan berjalan di
thread terpisah — ContentStage berada di state LOADING selama itu, dan thread
UI tidak pernah diblokir.

Warna/font/spacing dibaca dari ``jarvis.ui.theme`` saat render, sehingga
pergantian tema langsung terlihat tanpa membangun ulang panel.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from jarvis.core import log
from jarvis.ui import theme

_logger = log.get("ui.task_deck")

_STATUS_GLYPH = {
    "queued": "⋯", "running": "◐", "waiting": "?",
    "done": "✓", "failed": "✕", "cancelled": "—",
}


class JsonlTail:
    """Pembaca ekor JSONL dengan cache offset byte.

    Menahan diri dari membaca ulang seluruh berkas tiap render — itu yang akan
    membuat panel makin lambat seiring log tumbuh. Rotasi/truncate terdeteksi
    lewat ukuran berkas yang mengecil, lalu offset di-reset.
    """

    def __init__(self, path: Path, max_records: int = 4000) -> None:
        self._path = Path(path)
        self._offset = 0
        self._records: list[dict] = []
        self._max = max_records
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def records(self) -> list[dict]:
        with self._lock:
            return list(self._records)

    def refresh(self) -> int:
        """Baca hanya bagian baru. Return jumlah record baru. Tidak pernah
        melempar — panel harus tetap tampil walau log rusak/hilang."""
        try:
            if not self._path.exists():
                return 0
            size = self._path.stat().st_size
            with self._lock:
                offset = self._offset
                if size < offset:                # rotasi atau truncate
                    offset = 0
                    self._records.clear()
            if size == offset:
                return 0
            with self._path.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(offset)
                chunk = fh.read()
                new_offset = fh.tell()
        except OSError as exc:
            _logger.warning("task_deck.jsonl_unreadable", error=str(exc)[:120])
            return 0

        fresh: list[dict] = []
        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except (ValueError, TypeError):
                continue                          # baris separuh tertulis
            if isinstance(record, dict):
                fresh.append(record)
        with self._lock:
            self._offset = new_offset
            self._records.extend(fresh)
            if len(self._records) > self._max:
                del self._records[: len(self._records) - self._max]
        return len(fresh)

    def for_session(self, session_id: str, limit: int = 200) -> list[dict]:
        if not session_id:
            return []
        rows = [r for r in self.records() if str(r.get("session", "")) == session_id]
        return rows[-limit:]


class TaskDeckPanel(QWidget):
    """Daftar tugas + pane detail. Semua mutasi dari thread UI."""

    cancel_requested = pyqtSignal(str)
    loading_changed = pyqtSignal(bool)
    back_requested = pyqtSignal()

    def __init__(self, tail: JsonlTail | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if tail is None:
            from jarvis.agent import tool_usage
            tail = JsonlTail(tool_usage.jsonl_path())
        self._tail = tail
        self._views: list = []
        self._selected: str | None = None
        self._reading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)
        # Tombol kembali di pojok kiri atas — gaya sama dengan tombol dismiss
        # yang sudah ada (borderless, glyph tunggal, warna dari tema).
        self._back_btn = QPushButton("←", self)
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.setFixedSize(28, 24)
        self._back_btn.setToolTip("Kembali")
        self._back_btn.clicked.connect(self.back_requested.emit)
        top.addWidget(self._back_btn)

        self._header = QLabel("TUGAS LATAR", self)
        top.addWidget(self._header, 1)
        root.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body, 1)

        self._list = QListWidget(self)
        self._list.setSizePolicy(QSizePolicy.Policy.Expanding,
                                 QSizePolicy.Policy.Expanding)
        self._list.currentItemChanged.connect(self._on_row_changed)
        body.addWidget(self._list, 3)

        side = QVBoxLayout()
        side.setSpacing(8)
        body.addLayout(side, 4)

        self._detail = QTextEdit(self)
        self._detail.setReadOnly(True)
        side.addWidget(self._detail, 1)

        buttons = QHBoxLayout()
        self._cancel_btn = QPushButton("Batalkan", self)
        self._cancel_btn.clicked.connect(self._on_cancel_clicked)
        self._cancel_btn.setEnabled(False)
        buttons.addWidget(self._cancel_btn)
        # "Lihat Hasil" — menyalin hasil ke clipboard. Tanpa aksi nyata,
        # tombol ini akan jadi tombol mati ketiga di panel yang sama.
        self._result_btn = QPushButton("Salin Hasil", self)
        self._result_btn.clicked.connect(self._on_copy_result)
        self._result_btn.setEnabled(False)
        buttons.addWidget(self._result_btn)
        buttons.addStretch(1)
        side.addLayout(buttons)

        self._apply_theme()

    # ── tema ─────────────────────────────────────────────────────────────

    def _apply_theme(self) -> None:
        """Dibaca ulang tiap refresh — ganti tema langsung terlihat."""
        pal = theme.PAL
        self._header.setFont(theme.header_font(13))
        self._header.setStyleSheet(f"color:{pal.text_dim}; letter-spacing:2px;")
        mono = theme.mono_font(10)
        self._list.setFont(mono)
        self._detail.setFont(mono)
        self._list.setStyleSheet(
            f"QListWidget{{background:{pal.panel}; color:{pal.text};"
            f" border:none; outline:none;}}"
            f"QListWidget::item{{padding:6px 8px;}}"
            f"QListWidget::item:selected{{background:{pal.accent_dim};"
            f" color:{pal.base};}}")
        self._detail.setStyleSheet(
            f"QTextEdit{{background:{pal.panel}; color:{pal.text};"
            f" border:none;}}")
        self._cancel_btn.setStyleSheet(
            f"QPushButton{{background:transparent; color:{pal.alert};"
            f" border:1px solid {pal.alert}; padding:5px 14px;}}"
            f"QPushButton:disabled{{color:{pal.text_dim};"
            f" border-color:{pal.text_dim};}}")
        self._result_btn.setStyleSheet(
            f"QPushButton{{background:transparent; color:{pal.accent};"
            f" border:1px solid {pal.accent_dim}; padding:5px 14px;}}"
            f"QPushButton:disabled{{color:{pal.text_dim};"
            f" border-color:{pal.text_dim};}}")
        self._back_btn.setStyleSheet(
            f"QPushButton{{background:transparent; color:{pal.text_dim};"
            f" border:none; font-size:15px;}}"
            f"QPushButton:hover{{color:{pal.orb_core};}}")

    # ── data ─────────────────────────────────────────────────────────────

    def set_tasks(self, views) -> None:
        """Aktif di atas, selesai di bawah — urutan yang paling sering dicari."""
        ordered = sorted(
            views,
            key=lambda v: (not v.active, -(v.started_at or v.created_at)))
        self._views = ordered
        self._apply_theme()

        keep = self._selected
        self._list.blockSignals(True)
        self._list.clear()
        for view in ordered:
            glyph = _STATUS_GLYPH.get(view.status.value, "·")
            pct = f"{int(view.progress * 100):>3d}%"
            title = view.title or view.prompt
            line = f"{glyph} {view.id}  {pct}  {title[:48]}"
            item = QListWidgetItem(line, self._list)
            item.setData(Qt.ItemDataRole.UserRole, view.id)
        self._list.blockSignals(False)

        self._cancel_btn.setText("Batalkan")
        if keep is not None:
            self.select(keep)
        elif ordered:
            self.select(ordered[0].id)
        else:
            self._detail.setPlainText("Tidak ada tugas latar.")
            self._cancel_btn.setEnabled(False)

    def select(self, task_id: str) -> None:
        self._selected = task_id
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == task_id:
                self._list.setCurrentRow(row)
                break
        self._render_detail()

    # ── detail + pembacaan JSONL di luar thread UI ───────────────────────

    def _current_view(self):
        for view in self._views:
            if view.id == self._selected:
                return view
        return None

    def _render_detail(self) -> None:
        view = self._current_view()
        if view is None:
            self._detail.setPlainText("Tidak ada tugas terpilih.")
            self._cancel_btn.setEnabled(False)
            return
        self._cancel_btn.setEnabled(bool(view.active) and not view.cancelled)
        self._result_btn.setEnabled(bool(view.result))

        lines = [
            f"{view.id}  ·  {view.status.value.upper()}",
            view.title or view.prompt,
            "",
            f"progres   : {int(view.progress * 100)}%"
            f"  (iterasi {view.iteration}/{view.max_iterations})",
            f"berjalan  : {view.elapsed:.0f}s",
        ]
        if view.step:
            lines.append(f"langkah   : {view.step}")
        if view.resources:
            lines.append(f"resource  : {', '.join(sorted(view.resources))}")
        if view.error:
            lines.append(f"error     : {view.error}")
        if view.result:
            lines += ["", "HASIL", view.result[:4000]]

        rows = self._tail.for_session(view.session_id)
        if rows:
            lines += ["", f"JEJAK TOOL ({len(rows)})"]
            for record in rows[-40:]:
                mark = "ok" if record.get("ok") else "GAGAL"
                lines.append(
                    f"  {record.get('tool', '?')} → {mark}"
                    f"  {str(record.get('error') or '')[:70]}".rstrip())
        elif view.session_id:
            lines += ["", "JEJAK TOOL: belum ada entri untuk sesi ini."]

        self._detail.setPlainText("\n".join(lines))

    def _on_row_changed(self, current, _previous) -> None:
        if current is None:
            return
        self._selected = current.data(Qt.ItemDataRole.UserRole)
        self._render_detail()

    def _on_cancel_clicked(self) -> None:
        if not self._selected:
            return
        # Umpan balik instan, sama seperti chip di mini strip.
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setText("Membatalkan…")
        self.cancel_requested.emit(self._selected)

    def _on_copy_result(self) -> None:
        view = self._current_view()
        if view is None or not view.result:
            return
        try:
            from PyQt6.QtWidgets import QApplication
            clip = QApplication.clipboard()
            if clip is not None:
                clip.setText(view.result)
                self._result_btn.setText("Tersalin")
                QTimer.singleShot(
                    1200, lambda: self._result_btn.setText("Salin Hasil"))
        except Exception as exc:                             # noqa: BLE001
            _logger.warning("task_deck.copy_failed", error=str(exc)[:100])

    def refresh_log_async(self) -> None:
        """Baca ekor JSONL di thread lain; UI tetap responsif.

        ``loading_changed`` dipakai pemanggil untuk menggerakkan state LOADING
        milik ContentStage — panel tidak pernah menyentuh stage secara langsung.
        """
        if self._reading:
            return
        self._reading = True
        self.loading_changed.emit(True)

        def _work() -> None:
            try:
                self._tail.refresh()
            except Exception as exc:                         # noqa: BLE001
                _logger.warning("task_deck.refresh_failed", error=str(exc)[:120])
            finally:
                self._reading = False
                # Sinyal Qt aman lintas thread; slot dieksekusi di thread UI.
                self.loading_changed.emit(False)

        threading.Thread(target=_work, daemon=True,
                         name="task-deck-jsonl").start()


__all__ = ["TaskDeckPanel", "JsonlTail"]
