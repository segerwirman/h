"""Local-only picker and manage sheet for one controllable Chrome tab."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage
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
from jarvis.ui.tab_share_preview import (
    CursorVisual,
    PreviewGeneration,
    PreviewMetadata,
    TabSharePreview,
)


_STATE_TEXT = {
    "feature_disabled": (
        "Screen Control belum diaktifkan di konfigurasi lokal. "
        "Tidak ada koneksi ke Chrome yang dicoba."
    ),
    "task_required": (
        "Mulai tepat satu tugas agent lokal terlebih dahulu, lalu buka kembali "
        "Bagikan Tab Chrome."
    ),
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
        # Lazy: MainWindow builds a sheet in __init__, and an eager get_host()
        # would spawn the process-local owner thread for every window ever
        # constructed — leaking it for the life of the process even when the
        # user never shares a tab. The host appears on first real browser work.
        self._injected_host = host
        self._process_host = None
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

        self.preview_widget = TabSharePreview(parent=self)
        layout.addWidget(self.preview_widget, 1)

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
        if state in {
            "feature_disabled",
            "task_required",
            "checking",
            "unavailable",
            "zero_tabs",
            "tabs_available",
            "selected",
            "preview_unavailable",
            "navigated",
            "closed",
            "disconnected",
            "captcha_handoff",
            "stopped",
        }:
            self.preview_widget.clear_preview()
        self._status.setText(self._state_text(state, reason))
        self._sync_buttons()
        return True

    @staticmethod
    def _state_text(state: str, reason: str) -> str:
        return str(reason or _STATE_TEXT.get(state, "Status tab tidak tersedia."))

    def present_readiness(
        self,
        state: str,
        parent_w: int,
        parent_h: int,
    ) -> bool:
        if state not in {"feature_disabled", "task_required"}:
            return False
        self._generation += 1
        self._scope = None
        self._picker_id = ""
        self._active_target_id = ""
        self._active_target_generation = 0
        self._chosen_candidate_id = ""
        self._candidates.clear()
        self.set_runtime_state(state)
        self._open(parent_w, parent_h)
        return True

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
                elif not self._host.selection_is_active(
                    result.target.target_id,
                    result.target.target_generation,
                ):
                    self._coordinator.revoke_browser_tab(
                        target_id=result.target.target_id,
                        target_generation=result.target.target_generation,
                        reason="selected_tab_target_closed",
                    )
                    result = type(result)(
                        False,
                        "closed",
                        "Tab ditutup saat authority sedang diaktifkan.",
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

    def refresh_preview(
        self,
        *,
        preview_id: str,
        cursor_state: str,
    ) -> bool:
        if (
            self._scope is None
            or self.state != "sharing"
            or not self._active_target_id
            or not preview_id
        ):
            self.preview_widget.clear_preview()
            return False
        try:
            result = self._host.get_preview(str(preview_id))
        except Exception:
            self.preview_widget.clear_preview()
            return False
        if not bool(getattr(result, "ok", False)):
            self.preview_widget.clear_preview()
            return False
        try:
            image = QImage.fromData(
                bytes(getattr(result, "image_bytes", b"")),
                "PNG",
            )
            generation = PreviewGeneration(
                target_generation=int(
                    getattr(result, "target_generation", 0) or 0
                ),
                document_generation=int(
                    getattr(result, "document_generation", 0) or 0
                ),
                observation_generation=int(
                    getattr(result, "observation_generation", 0) or 0
                ),
                preview_generation=int(
                    getattr(result, "preview_generation", 0) or 0
                ),
            )
            viewport_css = getattr(result, "viewport_css", ())
            screenshot_px = getattr(result, "screenshot_px", ())
            dom_rect = getattr(result, "dom_rect", ())
            if (
                not isinstance(viewport_css, (tuple, list))
                or len(viewport_css) != 2
                or not isinstance(screenshot_px, (tuple, list))
                or len(screenshot_px) != 2
                or not isinstance(dom_rect, (tuple, list))
                or len(dom_rect) != 4
            ):
                raise ValueError("selected_tab_preview_metadata_invalid")
            metadata = PreviewMetadata(
                viewport_css=(float(viewport_css[0]), float(viewport_css[1])),
                screenshot_px=(int(screenshot_px[0]), int(screenshot_px[1])),
                generation=generation,
                captured_at=float(
                    getattr(result, "captured_at", 0.0) or 0.0
                ),
                expires_at=float(
                    getattr(result, "expires_at", 0.0) or 0.0
                ),
            )
            visual = CursorVisual(
                dom_rect=tuple(float(part) for part in dom_rect),
                generation=generation,
                state=str(cursor_state or ""),
            )
        except (TypeError, ValueError, OverflowError):
            self.preview_widget.clear_preview()
            return False
        if not self.preview_widget.replace_preview(image, metadata):
            return False
        if not self.preview_widget.update_cursor(visual):
            self.preview_widget.clear_preview()
            return False
        return True

    def apply_visual_state(self, data: dict) -> bool:
        scope = self._scope
        if (
            scope is None
            or self.state != "sharing"
            or str(data.get("session_id") or "") != scope.session_id
            or str(data.get("task_id") or "") != scope.task_id
        ):
            return False
        return self.refresh_preview(
            preview_id=str(data.get("preview_id") or ""),
            cursor_state=str(data.get("state") or ""),
        )

    def apply_screen_control_state(self, data: dict) -> None:
        if bool(data.get("active", False)):
            return
        reason = str(data.get("reason") or "")
        state = {
            "selected_tab_target_closed": "closed",
            "selected_tab_browser_disconnected": "disconnected",
            "selected_tab_target_navigated": "navigated",
            "selected_tab_cross_origin_navigation": "navigated",
            "selected_tab_navigation_ineligible": "navigated",
            "handoff": "captcha_handoff",
        }.get(reason, "stopped")
        if not self._active_target_id and not self.preview_widget.has_preview:
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
            revoked = bool(
                self._coordinator.revoke_browser_tab(
                    target_id=target_id,
                    target_generation=target_generation,
                    reason="user_stop_sharing",
                )
            )
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
        self.preview_widget.clear_preview()
        if self.state != "sharing":
            self.cancel_local()
        event.accept()

    @property
    def _host(self):
        """Resolve the browser host on first use, not at construction time.

        An injected host (tests, explicit wiring) always wins and never
        touches the process singleton.
        """
        if self._injected_host is not None:
            return self._injected_host
        if self._process_host is None:
            self._process_host = get_host()
        return self._process_host

    def _open(self, parent_w: int, parent_h: int) -> None:
        width = min(720, max(360, int(parent_w) - 40))
        height = min(620, max(360, int(parent_h) - 80))
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
                def retire_stale_share() -> None:
                    self._coordinator.revoke_browser_tab(
                        target_id=target.target_id,
                        target_generation=target.target_generation,
                        reason="selected_tab_stale_share_result",
                    )
                    self._host.stop_selected(
                        target.target_id,
                        target.target_generation,
                    )

                threading.Thread(
                    target=retire_stale_share,
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
        readiness_only = self.state in {"feature_disabled", "task_required"}
        self._cancel_button.setText("TUTUP" if sharing or readiness_only else "BATAL")


__all__ = ["TabShareSheet"]
