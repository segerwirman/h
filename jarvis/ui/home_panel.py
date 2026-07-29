"""HomePanel (MK50 §8) — Home Assistant di ContentStage: CCTV, lampu, cuaca.

Di atas tool HA yang SUDAH ada (`jarvis/agent/tools/home_assistant.py`):
reuse `_url()/_token()/available()/_get/_post` — tidak menduplikasi klien.
Aturan §8.2: REST + long-lived token, cache entity ~5 menit, kamera via
snapshot proxy berkala (`/api/camera_proxy/<entity>`; stream QtWebEngine
sengaja tidak dipakai — §7 baru saja membuang QtWebEngine dari boot),
tanpa kredensial → empty-state jujur, tidak crash. Semua I/O jaringan di
thread worker; UI di-update lewat sinyal Qt.
"""
from __future__ import annotations

import threading
import time

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout,
                             QLabel, QPushButton, QScrollArea, QSlider,
                             QVBoxLayout, QWidget)

from jarvis.core import config, log
from jarvis.core import locale as jlocale
from jarvis.ui import theme

_logger = log.get("ui.home_panel")

REFRESH_S = 300          # cache entity §8.2
SNAPSHOT_S = 10          # kamera: snapshot berkala


def _ha():
    """Modul tool HA (lazy import — panel tetap hidup tanpa modul agent)."""
    from jarvis.agent.tools import home_assistant
    return home_assistant


class _CameraLabel(QLabel):
    """Snapshot kamera yang dapat dibuka dalam tampilan lebih besar."""

    activated = pyqtSignal(str)

    def __init__(self, entity_id: str, text: str):
        super().__init__(text)
        self.entity_id = entity_id
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:              # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.entity_id)
        super().mousePressEvent(event)


class _LightRow(QFrame):
    """Satu lampu: nama + toggle + slider brightness → ha_call_service."""

    def __init__(self, panel: "HomePanel", entity_id: str, name: str,
                 state: str, brightness: int | None):
        super().__init__()
        self._panel = panel
        self.entity_id = entity_id
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"QFrame {{ background: {theme.PAL.panel};"
                           " border: none; border-radius: 6px; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(10)

        lab = QLabel(name or entity_id)
        lab.setFont(theme.mono_font(9))
        lab.setStyleSheet(f"color: {theme.PAL.text}; background: transparent;")
        lay.addWidget(lab, stretch=1)

        self.toggle = QPushButton("ON" if state == "on" else "OFF")
        self.toggle.setCheckable(True)
        self.toggle.setChecked(state == "on")
        self.toggle.setFixedWidth(52)
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.setStyleSheet(
            f"QPushButton {{ background: {theme.PAL.base};"
            f" color: {theme.PAL.text_dim}; border: 1px solid"
            f" {theme.PAL.accent_dim}; border-radius: 4px; padding: 3px; }}"
            f"QPushButton:checked {{ color: {theme.PAL.accent};"
            f" border-color: {theme.PAL.accent}; }}")
        self.toggle.clicked.connect(self._on_toggle)
        lay.addWidget(self.toggle)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 255)
        self.slider.setValue(int(brightness or 0))
        self.slider.setFixedWidth(110)
        self.slider.setEnabled(state == "on")
        self.slider.sliderReleased.connect(self._on_brightness)
        lay.addWidget(self.slider)

    def _on_toggle(self) -> None:
        on = self.toggle.isChecked()
        self.toggle.setText("ON" if on else "OFF")
        self.slider.setEnabled(on)
        self._panel.call_service(
            "light", "turn_on" if on else "turn_off", self.entity_id)

    def _on_brightness(self) -> None:
        if self.toggle.isChecked():
            self._panel.call_service(
                "light", "turn_on", self.entity_id,
                {"brightness": int(self.slider.value())})


class HomePanel(QWidget):
    """Registrasi ContentStage ``"home"`` — CCTV + smart lamp + cuaca."""

    _data_ready = pyqtSignal(dict)
    _snapshot_ready = pyqtSignal(str, bytes)
    _service_done = pyqtSignal(str, bool, str)
    ready = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._entities: list[dict] = []
        self._cache_ts = 0.0
        self._camera_labels: dict[str, QLabel] = {}
        self._lights_rows: list[_LightRow] = []
        self._busy = False
        self._camera_dialog: QDialog | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("HOME ASSISTANT")
        title.setFont(theme.header_font(12))
        title.setStyleSheet(f"color: {theme.PAL.text};"
                            " background: transparent; letter-spacing: 4px;")
        head.addWidget(title)
        head.addStretch()
        self._refresh_btn = QPushButton("MUAT ULANG")
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.PAL.text_dim};"
            f" border: 1px solid {theme.PAL.accent_dim}; border-radius: 4px;"
            " padding: 3px 10px; }"
            f"QPushButton:hover {{ color: {theme.PAL.accent}; }}")
        self._refresh_btn.clicked.connect(lambda: self.refresh(force=True))
        head.addWidget(self._refresh_btn)
        outer.addLayout(head)

        self._status = QLabel("")
        self._status.setFont(theme.mono_font(9))
        self._status.setStyleSheet(f"color: {theme.PAL.text_dim};"
                                   " background: transparent;")
        self._status.setWordWrap(True)
        outer.addWidget(self._status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            f"QScrollBar:vertical {{ background: transparent; width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {theme.PAL.text_dim};"
            " border-radius: 3px; }")
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        self._body_lay = QVBoxLayout(body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        self._body_lay.setSpacing(12)

        self._weather_card = QLabel("")
        self._weather_card.setFont(theme.mono_font(9))
        self._weather_card.setWordWrap(True)
        self._weather_card.setStyleSheet(
            f"QLabel {{ background: {theme.PAL.panel}; color: {theme.PAL.text};"
            f" border: 1px solid {theme.PAL.accent_dim}; border-radius: 6px;"
            " padding: 10px 14px; }")
        self._weather_card.hide()
        self._body_lay.addWidget(self._weather_card)

        self._camera_grid_host = QWidget()
        self._camera_grid_host.setStyleSheet("background: transparent;")
        self._camera_grid = QGridLayout(self._camera_grid_host)
        self._camera_grid.setContentsMargins(0, 0, 0, 0)
        self._camera_grid.setSpacing(10)
        self._body_lay.addWidget(self._camera_grid_host)

        self._lights_host = QWidget()
        self._lights_host.setStyleSheet("background: transparent;")
        self._lights_lay = QVBoxLayout(self._lights_host)
        self._lights_lay.setContentsMargins(0, 0, 0, 0)
        self._lights_lay.setSpacing(6)
        self._body_lay.addWidget(self._lights_host)
        self._body_lay.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll, stretch=1)

        self._data_ready.connect(self._apply_data)
        self._snapshot_ready.connect(self._apply_snapshot)
        self._service_done.connect(self._on_service_done)

        self._snap_timer = QTimer(self)
        self._snap_timer.setInterval(
            int(config.get("ui.home_panel.snapshot_s", SNAPSHOT_S)) * 1000)
        self._snap_timer.timeout.connect(self._pull_snapshots)

        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(
            int(config.get("ui.home_panel.refresh_s", REFRESH_S)) * 1000)
        self._auto_timer.timeout.connect(lambda: self.refresh(force=True))

    # ── lifecycle: panel hanya aktif menarik data saat terlihat ───────────

    def showEvent(self, ev) -> None:                          # noqa: N802
        super().showEvent(ev)
        self.refresh()
        self._snap_timer.start()
        self._auto_timer.start()

    def hideEvent(self, ev) -> None:                          # noqa: N802
        super().hideEvent(ev)
        self._snap_timer.stop()
        self._auto_timer.stop()

    # ── data ──────────────────────────────────────────────────────────────

    def refresh(self, force: bool = False) -> None:
        ha = _ha()
        if not ha.available():
            self._show_empty_state()
            self.ready.emit()
            return
        if self._busy:
            return
        if not force and self._entities and \
                time.time() - self._cache_ts < REFRESH_S:
            self.ready.emit()
            return
        self._busy = True
        self._status.setText("Memuat data Home Assistant …")

        def _work():
            payload: dict = {}
            try:
                states = ha._get("/api/states")
                payload = {"ok": True, "states": states}
            except Exception as e:                           # noqa: BLE001
                payload = {"ok": False, "error": str(e)[:160]}
            self._data_ready.emit(payload)

        threading.Thread(target=_work, daemon=True,
                         name="home-panel-refresh").start()

    def _show_empty_state(self) -> None:
        self._status.setText(
            "Home Assistant belum terhubung — set HA_URL dan HA_TOKEN "
            "melalui environment aman, lalu muat ulang.")
        self._weather_card.hide()
        self._clear_cameras()
        self._clear_lights()

    def _apply_data(self, payload: dict) -> None:
        self._busy = False
        if not payload.get("ok"):
            self._status.setText("Home Assistant tidak merespons: "
                                 + str(payload.get("error", ""))
                                 + " — coba muat ulang.")
            self.ready.emit()
            return
        states = payload.get("states") or []
        self._entities = states
        self._cache_ts = time.time()

        cameras = [s for s in states
                   if str(s.get("entity_id", "")).startswith("camera.")]
        lights = [s for s in states
                  if str(s.get("entity_id", "")).startswith("light.")]
        weather = [s for s in states
                   if str(s.get("entity_id", "")).startswith("weather.")]

        self._status.setText(
            f"{len(cameras)} kamera · {len(lights)} lampu · "
            f"{len(weather)} stasiun cuaca")

        self._build_weather(weather)
        self._build_cameras(cameras)
        self._build_lights(lights)
        self._pull_snapshots()
        self.ready.emit()

    # ── cuaca (§8.1 — pakai locale §6) ────────────────────────────────────

    def _build_weather(self, weather: list[dict]) -> None:
        if not weather:
            self._weather_card.hide()
            return
        s = weather[0]
        attrs = s.get("attributes") or {}
        loc = jlocale.resolve()
        name = attrs.get("friendly_name", s.get("entity_id", ""))
        bits = [f"CUACA — {name}  ({loc.region})",
                f"kondisi: {s.get('state', '?')}"]
        for key, label in (("temperature", "suhu"), ("humidity",
                           "kelembapan"), ("wind_speed", "angin")):
            if attrs.get(key) is not None:
                bits.append(f"{label}: {attrs[key]}")
        self._weather_card.setText("   ·   ".join(bits))
        self._weather_card.show()

    # ── kamera ────────────────────────────────────────────────────────────

    def _clear_cameras(self) -> None:
        while self._camera_grid.count():
            item = self._camera_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._camera_labels.clear()

    def _build_cameras(self, cameras: list[dict]) -> None:
        self._clear_cameras()
        max_cams = int(config.get("ui.home_panel.max_cameras", 4))
        for i, s in enumerate(cameras[:max_cams]):
            eid = str(s.get("entity_id", ""))
            attrs = s.get("attributes") or {}
            lab = _CameraLabel(
                eid, f"{attrs.get('friendly_name', eid)}\n(memuat snapshot …)")
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setFont(theme.mono_font(8))
            lab.setMinimumSize(220, 140)
            lab.setStyleSheet(
                f"QLabel {{ background: {theme.PAL.panel};"
                f" color: {theme.PAL.text_dim}; border: 1px solid"
                f" {theme.PAL.accent_dim}; border-radius: 6px; }}")
            lab.activated.connect(self._open_camera)
            self._camera_labels[eid] = lab
            self._camera_grid.addWidget(lab, i // 2, i % 2)

    def _open_camera(self, entity_id: str) -> None:
        source = self._camera_labels.get(entity_id)
        if source is None:
            return
        dialog = QDialog(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.setWindowTitle(entity_id)
        dialog.resize(900, 560)
        lay = QVBoxLayout(dialog)
        view = QLabel(entity_id)
        view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        view.setStyleSheet(
            f"background: {theme.PAL.base}; color: {theme.PAL.text_dim};")
        pix = source.pixmap()
        if pix is not None and not pix.isNull():
            view.setPixmap(pix.scaled(
                860, 520, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        else:
            view.setText(source.text())
        lay.addWidget(view)
        dialog.destroyed.connect(lambda: setattr(self, "_camera_dialog", None))
        self._camera_dialog = dialog
        dialog.show()

    def _pull_snapshots(self) -> None:
        ha = _ha()
        if not ha.available() or not self._camera_labels:
            return

        def _work(entity_ids: list[str]):
            import requests
            for eid in entity_ids:
                try:
                    r = requests.get(
                        f"{ha._url()}/api/camera_proxy/{eid}",
                        headers=ha._headers(), timeout=10)
                    r.raise_for_status()
                    self._snapshot_ready.emit(eid, r.content)
                except Exception as e:                       # noqa: BLE001
                    _logger.warning("home_panel.snapshot_failed",
                                    entity=eid, error=str(e)[:100])

        threading.Thread(target=_work,
                         args=(list(self._camera_labels),),
                         daemon=True, name="home-panel-snapshots").start()

    def _apply_snapshot(self, entity_id: str, data: bytes) -> None:
        lab = self._camera_labels.get(entity_id)
        if lab is None:
            return
        img = QImage.fromData(data)
        if img.isNull():
            lab.setText(f"{entity_id}\n(snapshot tidak valid)")
            return
        pix = QPixmap.fromImage(img).scaled(
            lab.width(), lab.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        lab.setPixmap(pix)

    # ── lampu ─────────────────────────────────────────────────────────────

    def _clear_lights(self) -> None:
        while self._lights_lay.count():
            item = self._lights_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._lights_rows.clear()

    def _build_lights(self, lights: list[dict]) -> None:
        self._clear_lights()
        for s in lights[:int(config.get("ui.home_panel.max_lights", 12))]:
            attrs = s.get("attributes") or {}
            row = _LightRow(
                self, str(s.get("entity_id", "")),
                str(attrs.get("friendly_name", "")),
                str(s.get("state", "")),
                attrs.get("brightness"))
            self._lights_rows.append(row)
            self._lights_lay.addWidget(row)

    def call_service(self, domain: str, service: str, entity_id: str,
                     data: dict | None = None) -> None:
        """POST service HA di thread worker; hasil kembali via sinyal."""
        ha = _ha()
        if not ha.available():
            self._show_empty_state()
            return

        def _work():
            try:
                ha._post(f"/api/services/{domain}/{service}",
                         {"entity_id": entity_id, **(data or {})})
                self._service_done.emit(entity_id, True, "")
            except Exception as e:                           # noqa: BLE001
                self._service_done.emit(entity_id, False, str(e)[:120])

        threading.Thread(target=_work, daemon=True,
                         name="home-panel-service").start()

    def _on_service_done(self, entity_id: str, ok: bool, err: str) -> None:
        if ok:
            self._status.setText(
                f"Perintah untuk {entity_id} terkirim; memverifikasi state …")
            self._cache_ts = 0.0
            self.refresh(force=True)
        else:
            self._status.setText(
                f"Perintah untuk {entity_id} gagal: {err} — state panel "
                "dimuat ulang.")
            self.refresh(force=True)
