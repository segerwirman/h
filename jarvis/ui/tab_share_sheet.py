"""Local-only picker and manage sheet for one controllable Chrome tab."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from jarvis.integrations.selected_tab_browser import get_host
from jarvis.ui import screen_control, theme


_STATE_TEXT = {
    "checking": "Memeriksa tab Chrome yang dapat dikontrol…",
    "unavailable": "Chrome tidak dapat dilihat. Periksa remote-debugging-port.",
    "zero_tabs": "Tidak ada tab HTTP/HTTPS yang dapat dibagikan.",
    "tabs_available": "Pilih tepat satu tab Chrome.",
    "selected": "Satu tab dipilih; belum dibagikan.",
    "preview_unavailable": "Preview belum tersedia; belum ada bukti visual.",
    "ready": "Tab siap dibagikan ke tugas lokal ini.",
    "sharing": "Satu tab sedang dibagikan. Tab lain tetap tidak terlihat.",
    "navigated": "Tab berpindah halaman; referensi lama sudah dicabut.",
    "closed": "Tab yang dibagikan sudah ditutup.",
    "disconnected": "Koneksi ke Chrome terputus.",
    "captcha_handoff": "Kontrol dijeda untuk penyelesaian CAPTCHA oleh manusia.",
    "stopped": "Berbagi tab dihentikan.",
}


@dataclass(frozen=True)
class _Scope:
    session_id: str
    task_id: str


class TabShareSheet(QWidget):
    """Present candidates locally; browser work never blocks the Qt thread."""

    _picker_ready = pyqtSignal(int, object)
    _share_ready = pyqtSignal(int, object)
    _cancel_ready = pyqtSignal(int, bool)
    _stop_ready = pyqtSignal(int, bool)

    def __init__(
        self,
        *,
        host=None,
        coordinator=screen_control.COORDINATOR,
        ttl_provider: Callable[[], float] = screen_control.default_ttl_s,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._host = host if host is not None else get_host()
        self._coordinator = coordinator
        self._ttl_provider = ttl_provider
        self._scope: _Scope | None = None
        self._picker_id = ""
        self._generation = 0
        self._active_target_id = ""
        self._active_target_generation = 0
        self._chosen_candidate_id = ""
        self.state = "stopped"

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.panel};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 28)
        layout.setSpacing(12)

        title = QLabel("BAGIKAN SATU TAB CHROME", self)
        title.setFont(theme.header_font(14))
        title.setStyleSheet(
            f"color: {theme.PAL.accent}; background: transparent; letter-spacing: 2px;"
        )
        layout.addWidget(title)

        self._status = QLabel(_STATE_TEXT["stopped"], self)
        self._status.setWordWrap(True)
        self._status.setFont(theme.mono_font(10))
        self._status.setStyleSheet(
            f"color: {theme.PAL.text}; background: transparent;"
        )
        layout.addWidget(self._status)

        self._candidates = QListWidget(self)
        self._candidates.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._candidates.itemClicked.connect(self._on_candidate_chosen)
        self._candidates.itemActivated.connect(self._on_candidate_chosen)
        layout.addWidget(self._candidates, 1)

        buttons = QHBoxLayout()
        self._share_button = QPushButton("BAGIKAN TAB", self)
        self._share_button.clicked.connect(self.share_selected)
        self._stop_button = QPushButton("STOP SHARING", self)
        self._stop_button.clicked.connect(self.stop_sharing)
        self._cancel_button = QPushButton("BATAL", self)
        self._cancel_button.clicked.connect(self.cancel_local)
        for button in (
            self._share_button,
            self._stop_button,
            self._cancel_button,
        ):
            button.setFont(theme.header_font(10))
            button.setFixedHeight(34)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self._picker_ready.connect(self._apply_picker_result)
        self._share_ready.connect(self._apply_share_result)
        self._cancel_ready.connect(self._apply_cancel_result)
        self._stop_ready.connect(self._apply_stop_result)
        self._sync_buttons()
        self.hide()

    @property
    def active_target_id(self) -> str:
        return self._active_target_id

    def status_text(self) -> str:
        return self._status.text()

    def candidate_titles(self) -> list[str]:
        return [self._candidates.item(i).text() for i in range(self._candidates.count())]

    def set_runtime_state(self, state: str, reason: str = "") -> bool:
        if state not in _STATE_TEXT:
            return False
        self.state = state
        self._status.setText(self._state_text(state, reason))
        self._sync_buttons()
        return True

    @staticmethod
    def _state_text(state: str, reason: str) -> str:
        return str(reason or _STATE_TEXT.get(state, "Status tab tidak tersedia."))

    def present(self, scope, parent_w: int, parent_h: int) -> bool:
        session_id = str(getattr(scope, "session_id", "") or "").strip()
        task_id = str(getattr(scope, "task_id", "") or "").strip()
        if not session_id or not task_id or self.state == "checking":
            return False
        self._scope = _Scope(session_id, task_id)
        self._picker_id = ""
        self._active_target_id = ""
        self._active_target_generation = 0
        self._chosen_candidate_id = ""
        self._candidates.clear()
        self._generation += 1
        generation = self._generation
        self.set_runtime_state("checking")
        self._open(parent_w, parent_h)

        def worker() -> None:
            result = self._host.begin_picker()
            self._picker_ready.emit(generation, result)

        threading.Thread(
            target=worker,
            daemon=True,
            name="selected-tab-picker-request",
        ).start()
        return True

    def present_manage(self, snapshot, parent_w: int, parent_h: int) -> bool:
        if (
            getattr(snapshot, "state", "") != screen_control.ACTIVE
            or getattr(snapshot, "surface_kind", "")
            != screen_control.BROWSER_TAB_SURFACE
        ):
            return False
        self._generation += 1
        self._scope = _Scope(
            str(getattr(snapshot, "session_id", "") or ""),
            str(getattr(snapshot, "task_id", "") or ""),
        )
        self._picker_id = ""
        self._active_target_id = str(getattr(snapshot, "surface_id", "") or "")
        self._active_target_generation = int(
            getattr(snapshot, "surface_generation", 0) or 0
        )
        self._candidates.clear()
        self.set_runtime_state("sharing")
        self._open(parent_w, parent_h)
        return True

    def share_selected(self) -> None:
        item = self._candidates.currentItem()
        scope = self._scope
        candidate_id = str(
            item.data(Qt.ItemDataRole.UserRole) if item is not None else ""
        )
        if (
            item is None
            or scope is None
            or not self._picker_id
            or self.state not in {"selected", "ready"}
            or candidate_id != self._chosen_candidate_id
        ):
            return
        if not candidate_id:
            return
        picker_id = self._picker_id
        self._generation += 1
        generation = self._generation
        self.set_runtime_state("ready")

        def worker() -> None:
            result = self._host.select_candidate(picker_id, candidate_id)
            if (
                result.ok
                and result.target is not None
                and not self._host.selection_is_active(
                    result.target.target_id,
                    result.target.target_generation,
                )
            ):
                result = type(result)(
                    False,
                    "closed",
                    "Tab ditutup sebelum authority dapat diaktifkan.",
                )
            if result.ok and result.target is not None:
                activated = self._coordinator.activate_browser_tab(
                    scope.session_id,
                    scope.task_id,
                    target_id=result.target.target_id,
                    target_generation=result.target.target_generation,
                    ttl_s=float(self._ttl_provider()),
                )
                if not activated:
                    self._host.stop_selected(
                        result.target.target_id,
                        result.target.target_generation,
                    )
                    result = type(result)(
                        False,
                        "stopped",
                        "Tab tidak dibagikan: tugas atau lease tidak lagi cocok.",
                    )
            self._share_ready.emit(generation, result)

        threading.Thread(
            target=worker,
            daemon=True,
            name="selected-tab-share-request",
        ).start()

    def cancel_local(self) -> None:
        picker_id = self._picker_id
        self._generation += 1
        generation = self._generation
        self._picker_id = ""
        self._scope = None
        self._candidates.clear()
        self.set_runtime_state("stopped")
        self.hide()
        if not picker_id:
            return

        def worker() -> None:
            self._cancel_ready.emit(generation, bool(self._host.cancel_picker(picker_id)))

        threading.Thread(
            target=worker,
            daemon=True,
            name="selected-tab-picker-cancel",
        ).start()

    def apply_screen_control_state(self, data: dict) -> None:
        if not self._active_target_id or bool(data.get("active", False)):
            return
        reason = str(data.get("reason") or "")
        state = {
            "selected_tab_target_closed": "closed",
            "selected_tab_browser_disconnected": "disconnected",
        }.get(reason)
        if state is None:
            return
        self._generation += 1
        self._active_target_id = ""
        self._active_target_generation = 0
        self._scope = None
        self.set_runtime_state(state)

    def stop_sharing(self) -> None:
        if self.state != "sharing" or not self._active_target_id:
            return
        target_id = self._active_target_id
        target_generation = self._active_target_generation
        self._generation += 1
        generation = self._generation

        def worker() -> None:
            revoked = bool(self._coordinator.revoke("user_stop_sharing"))
            stopped = bool(
                self._host.stop_selected(target_id, target_generation)
            )
            self._stop_ready.emit(generation, revoked or stopped)

        threading.Thread(
            target=worker,
            daemon=True,
            name="selected-tab-share-stop",
        ).start()

    def closeEvent(self, event) -> None:
        if self.state != "sharing":
            self.cancel_local()
        event.accept()

    def _open(self, parent_w: int, parent_h: int) -> None:
        width = min(620, max(360, int(parent_w) - 40))
        height = min(460, max(280, int(parent_h) - 80))
        self.setGeometry(
            (int(parent_w) - width) // 2,
            (int(parent_h) - height) // 2,
            width,
            height,
        )
        self.show()
        self.raise_()

    def _apply_picker_result(self, generation: int, result) -> None:
        if generation != self._generation:
            if getattr(result, "ok", False) and getattr(result, "picker_id", ""):
                picker_id = str(result.picker_id)
                threading.Thread(
                    target=lambda: self._host.cancel_picker(picker_id),
                    daemon=True,
                    name="selected-tab-stale-picker-retire",
                ).start()
            return
        self._picker_id = str(getattr(result, "picker_id", "") or "")
        self._candidates.blockSignals(True)
        self._candidates.clear()
        if getattr(result, "ok", False):
            for candidate in getattr(result, "candidates", ()):
                item = QListWidgetItem(str(candidate.title or candidate.origin))
                item.setToolTip(str(candidate.origin))
                item.setData(Qt.ItemDataRole.UserRole, candidate.candidate_id)
                self._candidates.addItem(item)
        self._candidates.blockSignals(False)
        self.set_runtime_state(
            str(getattr(result, "state", "unavailable") or "unavailable"),
            str(getattr(result, "reason", "") or ""),
        )

    def _apply_share_result(self, generation: int, result) -> None:
        if generation != self._generation:
            target = getattr(result, "target", None)
            if getattr(result, "ok", False) and target is not None:
                threading.Thread(
                    target=lambda: self._host.stop_selected(
                        target.target_id,
                        target.target_generation,
                    ),
                    daemon=True,
                    name="selected-tab-stale-share-retire",
                ).start()
            return
        target = getattr(result, "target", None)
        if getattr(result, "ok", False) and target is not None:
            self._picker_id = ""
            self._active_target_id = str(target.target_id)
            self._active_target_generation = int(target.target_generation)
            self._candidates.clear()
        self.set_runtime_state(
            str(getattr(result, "state", "stopped") or "stopped"),
            str(getattr(result, "reason", "") or ""),
        )

    def _apply_cancel_result(self, _generation: int, _ok: bool) -> None:
        return None

    def _apply_stop_result(self, generation: int, _ok: bool) -> None:
        if generation != self._generation:
            return
        self._active_target_id = ""
        self._active_target_generation = 0
        self._scope = None
        self.set_runtime_state("stopped")
        self.hide()

    def _on_candidate_chosen(self, item) -> None:
        if item is None or self.state not in {"tabs_available", "selected"}:
            return
        self._chosen_candidate_id = str(
            item.data(Qt.ItemDataRole.UserRole) or ""
        )
        if self._chosen_candidate_id:
            self.set_runtime_state("selected")

    def _sync_buttons(self) -> None:
        sharing = self.state == "sharing"
        self._share_button.setVisible(not sharing)
        self._share_button.setEnabled(
            self.state in {"selected", "ready"}
            and bool(self._chosen_candidate_id)
            and self._candidates.currentItem() is not None
        )
        self._stop_button.setVisible(sharing)
        self._stop_button.setEnabled(sharing)
        self._cancel_button.setText("TUTUP" if sharing else "BATAL")


__all__ = ["TabShareSheet"]
