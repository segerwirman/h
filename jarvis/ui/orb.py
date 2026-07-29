"""OrbRenderer — the Mark XLIX centerpiece (Part 1.3).

A transparent overlay canvas with a manual 60 fps redraw loop (16 ms timer —
the Qt analogue of ``after(16, ...)``). Never blocks the main thread: all
animation is incremental per-tick math; heavy work lives elsewhere.

States and their visual behaviour come from ``config.yaml → orb.states``.
"""
from __future__ import annotations

import math
import random
import time
from enum import Enum

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

from jarvis.core import config
from jarvis.ui import theme


class OrbState(str, Enum):
    BOOT      = "BOOT"        # pre-greeting fade-in
    IDLE      = "IDLE"
    LISTENING = "LISTENING"
    THINKING  = "THINKING"
    SPEAKING  = "SPEAKING"
    EXECUTING = "EXECUTING"
    ERROR     = "ERROR"


class Corner(str, Enum):
    BOTTOM_RIGHT = "bottom_right"
    BOTTOM_LEFT  = "bottom_left"
    TOP_RIGHT    = "top_right"
    TOP_LEFT     = "top_left"


class PresentationMode(str, Enum):
    """Layout is derived from ContentStage readiness, not pipeline state."""

    FULL_EMPTY_STAGE = "FULL_EMPTY_STAGE"
    DOCKED_CONTENT_STAGE = "DOCKED_CONTENT_STAGE"


def _ease_in_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 4 * t * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2


class OrbRenderer(QWidget):
    """Overlay canvas: paints only the orb; mouse events pass through."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAutoFillBackground(False)

        self._states: dict = config.section("orb.states")
        self._reactor: dict = config.section("orb.reactor")
        self._dock_inset = float(config.get("ui.orb.docking.inset_px",
                                            config.get("orb.dock_inset_px", 200)))
        self._dock_diam = float(config.get("ui.orb.speaking.active_content.diameter",
                                           config.get("orb.dock_diameter", 140)))
        self._amp_smooth = float(config.get("orb.amplitude_smoothing", 0.35))
        self._particle_max = int(config.get("ui.orb.speaking.empty.particles.count",
                                            config.get("orb.particle_max", 48)))
        default_dock_ms = int(config.get("ui.orb.transition.docking_ms",
                                         config.get("motion.dock_ms", 400)))
        self._wave_bars = int(config.get("ui.orb.speaking.empty.waveform.bars", 24))
        self._tick_ms = int(config.get("motion.tick_ms", 16))

        sg = config.section("ui.sentiment_glow")
        self._sentiment_enabled = bool(sg.get("enabled", True))
        self._sentiment_hue_max = float(sg.get("hue_shift_max_deg", 18))
        self._sentiment_intensity_max = float(sg.get("intensity_max", 0.12))
        self._sentiment_smooth = float(sg.get("smoothing", 0.08))
        self._sentiment = 0.0
        self._sentiment_target = 0.0

        px = config.section("ui.parallax")
        self._parallax_enabled = bool(px.get("enabled", True))
        self._parallax_max = float(px.get("max_px", 6))
        self._parallax_reduced_max = float(px.get("reduced_motion_max_px", 1))
        self._parallax_smooth = float(px.get("smoothing", 0.12))
        self._reduced_motion = False
        self._parallax = QPointF(0.0, 0.0)
        self._parallax_target = QPointF(0.0, 0.0)

        self.state = OrbState.IDLE
        self._prev_state = OrbState.IDLE
        self._corner = Corner.BOTTOM_RIGHT
        self._docked = False
        self.presentation = PresentationMode.FULL_EMPTY_STAGE

        # transition bookkeeping: snapshot → target, eased by progress
        self._trans_start = time.monotonic()
        self._trans_ms = default_dock_ms
        self._default_dock_ms = default_dock_ms
        self._from_pos: QPointF | None = None      # None → center of widget
        self._from_diam = self._state_diam(OrbState.IDLE)
        self._from_color = QColor(self._state_color(OrbState.IDLE))
        self._to_color = QColor(self._from_color)

        self._opacity = 1.0
        self._fade_start: float | None = None
        self._fade_ms = 0
        self._fade_from = 1.0
        self._fade_to = 1.0

        self._amp = 0.0            # smoothed
        self._amp_target = 0.0
        self._wave = [0.0] * self._wave_bars
        self._progress = 0.0       # EXECUTING progress ring, 0..1
        self._flash_t0 = 0.0       # ERROR flash epoch
        self._phase = 0.0          # pulse phase (radians)
        self._rot = 0.0            # THINKING arc rotation (deg)
        self._tick_rot = 0.0       # outer reticle rotation (deg)
        self._particles: list[list[float]] = []
        self._status_word = ""
        self._t0 = time.monotonic()
        self._last_tick = self._t0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(self._tick_ms)

    # ── required API (Part 1.3) ──────────────────────────────────────────────

    def set_state(self, state: OrbState | str, transition_ms: int | None = None) -> None:
        state = OrbState(state)
        if state == self.state:
            return
        params = self._params(state)
        self._begin_transition(transition_ms
                               if transition_ms is not None
                               else self._default_dock_ms)
        self._prev_state, self.state = self.state, state
        self._to_color = QColor(self._state_color(state))
        # SPEAKING layout is exclusively driven by ContentStage readiness.
        if state != OrbState.SPEAKING:
            self._docked = bool(params.get("docked", self._docked))
        if state == OrbState.ERROR:
            self._flash_t0 = time.monotonic()
        if state == OrbState.EXECUTING:
            self._progress = 0.0
        self._status_word = "" if self._docked else state.value

    def set_presentation(self, mode: PresentationMode | str) -> None:
        """Idempotently animate between full and content-docked layouts."""
        mode = PresentationMode(mode)
        if mode is self.presentation:
            return
        self._begin_transition(self._default_dock_ms)
        self.presentation = mode
        self._docked = mode is PresentationMode.DOCKED_CONTENT_STAGE
        self._status_word = "" if self._docked else self.state.value

    def presentation_snapshot(self) -> dict:
        """Renderer-level seam used by deterministic state tests."""
        return {
            "mode": self.presentation.value,
            "diameter": self._target_diameter(),
            "docked": self._docked,
            "waveform_bars": self._wave_bars if self.state is OrbState.SPEAKING else 0,
            "particles": self._particle_mode(),
            "halo": self._halo_visible(),
        }

    def feed_amplitude(self, level: float) -> None:
        """0.0–1.0 — mic level while LISTENING, TTS level while SPEAKING."""
        self._amp_target = max(0.0, min(1.0, float(level)))

    def dock(self, corner: Corner | str = Corner.BOTTOM_RIGHT) -> None:
        self._corner = Corner(corner)
        if not self._docked:
            self._begin_transition(self._default_dock_ms)
            self._docked = True
            self.presentation = PresentationMode.DOCKED_CONTENT_STAGE
            self._status_word = ""

    def undock(self) -> None:
        if self._docked:
            self._begin_transition(self._default_dock_ms)
            self._docked = False
            self.presentation = PresentationMode.FULL_EMPTY_STAGE
            self._status_word = self.state.value

    # ── extras used by boot / executor ───────────────────────────────────────

    def set_progress(self, fraction: float) -> None:
        self._progress = max(0.0, min(1.0, fraction))

    def fade_in(self, ms: int | None = None) -> None:
        self._fade_from, self._fade_to = 0.0, 1.0
        self._fade_ms = ms or int(config.get("motion.orb_fade_in_ms", 800))
        self._fade_start = time.monotonic()
        self._opacity = 0.0

    def start_cinematic_boot(self) -> None:
        """A visual-only, skippable spin-up that never blocks input."""
        if not bool(config.get("ui.boot.cinematic_enabled", True)):
            return
        self.set_state(OrbState.BOOT)
        self.fade_in(int(config.get("boot.fade_in_ms", 800)))
        QTimer.singleShot(int(config.get("ui.boot.cinematic_duration_ms", 900)),
                          self._finish_cinematic_boot)

    def _finish_cinematic_boot(self) -> None:
        # A state change from the live pipeline is the skip mechanism.
        if self.state is OrbState.BOOT:
            self.set_status_word(str(config.get("ui.boot.ready_label", "READY")))

    def set_status_word(self, word: str) -> None:
        """Override the word under the orb (e.g. during boot checks)."""
        self._status_word = word

    def feed_sentiment(self, value: float) -> None:
        """-1..1 conversational sentiment. Subtly shifts hue/intensity only —
        clamped well below what audio-driven elements (waveform, rings,
        particles) express, so sentiment never obscures the current state."""
        self._sentiment_target = max(-1.0, min(1.0, float(value)))

    def set_reduced_motion(self, reduced: bool) -> None:
        self._reduced_motion = reduced

    def set_parallax_target(self, dx: float, dy: float) -> None:
        """Cursor-driven HUD displacement, smoothed in `_tick`. The caller
        is responsible for pausing this while the window is inactive."""
        if not self._parallax_enabled:
            self._parallax_target = QPointF(0.0, 0.0)
            return
        cap = self._parallax_reduced_max if self._reduced_motion else self._parallax_max
        self._parallax_target = QPointF(max(-cap, min(cap, dx)), max(-cap, min(cap, dy)))

    # ── internals ────────────────────────────────────────────────────────────

    def _params(self, state: OrbState) -> dict:
        return self._states.get(state.value,
                                self._states.get("IDLE", {})) or {}

    def _state_diam(self, state: OrbState) -> float:
        if self._params(state).get("docked"):
            return self._dock_diam
        return float(self._params(state).get("diameter", 280))

    def _target_diameter(self) -> float:
        if self.state is OrbState.SPEAKING:
            path = ("ui.orb.speaking.active_content.diameter" if self._docked
                    else "ui.orb.speaking.empty.diameter")
            return float(config.get(path, self._dock_diam if self._docked else 300))
        return self._dock_diam if self._docked else self._state_diam(self.state)

    def _state_color(self, state: OrbState) -> str:
        return self._params(state).get("color", theme.PAL.accent)

    def _center_pos(self) -> QPointF:
        return QPointF(self.width() / 2, self.height() / 2)

    def _corner_pos(self) -> QPointF:
        i = self._dock_inset
        w, h = self.width(), self.height()
        right = float(config.get("ui.orb.docking.margin_right_px", i))
        bottom = max(float(config.get("ui.orb.docking.margin_bottom_px", i)),
                     float(config.get("ui.orb.docking.command_bar_clearance_px", i)))
        return {
            Corner.BOTTOM_RIGHT: QPointF(w - right, h - bottom),
            Corner.BOTTOM_LEFT:  QPointF(i, h - bottom),
            Corner.TOP_RIGHT:    QPointF(w - right, i),
            Corner.TOP_LEFT:     QPointF(i, i),
        }[self._corner]

    def _begin_transition(self, ms: int) -> None:
        # snapshot current animated values as the new starting point
        self._from_pos = QPointF(self._cur_pos())
        self._from_diam = self._cur_diam()
        self._from_color = self._cur_color()
        self._trans_start = time.monotonic()
        self._trans_ms = max(1, ms)

    def _trans_t(self) -> float:
        return _ease_in_out_cubic(
            (time.monotonic() - self._trans_start) * 1000.0 / self._trans_ms)

    def _cur_pos(self) -> QPointF:
        target = self._corner_pos() if self._docked else self._center_pos()
        if self._from_pos is None:
            base = target
        else:
            t = self._trans_t()
            base = QPointF(
                self._from_pos.x() + (target.x() - self._from_pos.x()) * t,
                self._from_pos.y() + (target.y() - self._from_pos.y()) * t,
            )
        return QPointF(base.x() + self._parallax.x(), base.y() + self._parallax.y())

    def _cur_diam(self) -> float:
        target = self._target_diameter()
        return self._from_diam + (target - self._from_diam) * self._trans_t()

    def _cur_color(self) -> QColor:
        return theme.blend(self._from_color, self._to_color, self._trans_t())

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(0.1, now - self._last_tick)
        self._last_tick = now

        motion_factor = 0.1 if self._reduced_motion else 1.0
        hz = self._pulse_hz()
        self._phase = (self._phase + 2 * math.pi * hz * dt) % (2 * math.pi * 1000)
        self._rot = (self._rot + 90.0 * dt * hz * motion_factor) % 360
        self._tick_rot = (self._tick_rot
                          + float(self._reactor.get("tick_rot_dps", 12.0)) * dt * motion_factor) % 360

        self._amp += (self._amp_target - self._amp) * self._amp_smooth
        # natural decay so a stalled feed doesn't freeze the ring/waveform
        self._amp_target *= 0.94

        self._sentiment += (self._sentiment_target - self._sentiment) * self._sentiment_smooth
        self._parallax = QPointF(
            self._parallax.x() + (self._parallax_target.x() - self._parallax.x()) * self._parallax_smooth,
            self._parallax.y() + (self._parallax_target.y() - self._parallax.y()) * self._parallax_smooth)

        if self.state == OrbState.SPEAKING:
            self._wave.pop(0)
            jitter = random.uniform(float(config.get("ui.orb.waveform.jitter_min", 0.55)),
                                    float(config.get("ui.orb.waveform.jitter_max", 1.0)))
            fallback = float(config.get("ui.orb.speaking.empty.waveform.fallback_amplitude", 0.18))
            self._wave.append(max(self._amp * jitter,
                                  fallback * (0.5 + 0.5 * math.sin(self._phase))))

        if self._fade_start is not None:
            ft = (now - self._fade_start) * 1000.0 / max(1, self._fade_ms)
            self._opacity = self._fade_from + (self._fade_to - self._fade_from) * min(1.0, ft)
            if ft >= 1.0:
                self._fade_start = None

        self._step_particles(dt)
        self.update()

    def _step_particles(self, dt: float) -> None:
        mode = self._particle_mode()
        pos, diam = self._cur_pos(), self._cur_diam()
        r = diam / 2

        spawn = 0.0
        if mode == "drift":
            spawn = 0.35
        elif mode == "reactive":
            spawn = 0.3 + self._amp * 4.0
        elif mode == "orbit":
            spawn = 0.8

        if len(self._particles) < self._particle_max and random.random() < spawn * dt * 8:
            ang = random.uniform(0, 2 * math.pi)
            speed = random.uniform(8, 30) * (1 + self._amp * 2)
            if mode == "orbit":
                # tangential launch — particles circle the reactor
                vx, vy = -math.sin(ang) * speed * 1.6, math.cos(ang) * speed * 1.6
            else:
                vx = math.cos(ang) * speed
                vy = math.sin(ang) * speed - (12 if mode == "drift" else 0)
            self._particles.append([
                pos.x() + math.cos(ang) * r,
                pos.y() + math.sin(ang) * r,
                vx, vy, 1.0,
            ])
        for p in self._particles:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[4] -= dt * 0.7
        self._particles = [p for p in self._particles if p[4] > 0]

    def _pulse_hz(self) -> float:
        if self.state is OrbState.SPEAKING:
            return float(config.get("ui.orb.speaking.empty.waveform.base_frequency_hz", 1.0))
        return float(self._params(self.state).get("pulse_hz", 0.5))

    def _particle_mode(self) -> str:
        if self.state is OrbState.SPEAKING:
            path = ("ui.orb.speaking.active_content.particles.mode" if self._docked
                    else "ui.orb.speaking.empty.particles.mode")
            return str(config.get(path, "none" if self._docked else "orbit"))
        return str(self._params(self.state).get("particles", "none"))

    def _halo_visible(self) -> bool:
        return (bool(config.get("ui.orb.halo_aperture.enabled", True))
                and not self._docked)

    def _apply_sentiment(self, col: QColor) -> QColor:
        """Audio-driven elements (waveform amplitude, ring pulse, particle
        spawn rate) already dominate the orb's motion language; this only
        nudges hue/value within the clamped config limits so mood never
        overrides what state color/motion already communicates."""
        if not self._sentiment_enabled or abs(self._sentiment) < 0.01:
            return col
        h, s, v, a = col.getHsvF()
        if h < 0:      # fully desaturated colors report h = -1
            return col
        shift = (self._sentiment * self._sentiment_hue_max) / 360.0
        h = (h + shift) % 1.0
        v = max(0.0, min(1.0, v + self._sentiment * self._sentiment_intensity_max))
        out = QColor()
        out.setHsvF(h, s, v, a)
        return out

    # ── painting (Mark L arc-reactor, Change 8) ──────────────────────────────

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._opacity)

        pos, diam, col = self._cur_pos(), self._cur_diam(), self._cur_color()
        col = self._apply_sentiment(col)

        # IDLE breathing: slow ±4 % scale at pulse_hz (0.4 Hz)
        breathe = 1.0
        if self.state in (OrbState.IDLE, OrbState.BOOT):
            breathe = 1.0 + 0.04 * math.sin(self._phase)
        diam *= breathe
        r = diam / 2

        rx = self._reactor
        alpha_boost = self._error_flash_alpha()

        # 1 — stacked bloom layers (depth glow, borderless separation)
        layers = int(rx.get("bloom_layers", 3))
        for i in range(layers):
            reach = r * (2.2 - i * 0.45)
            glow = QRadialGradient(pos, reach)
            gcol = QColor(col)
            gcol.setAlpha(int((26 + i * 22) * alpha_boost))
            glow.setColorAt(0.0, gcol)
            gcol2 = QColor(col); gcol2.setAlpha(0)
            glow.setColorAt(1.0, gcol2)
            p.setBrush(QBrush(glow))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(pos, reach, reach)

        # 2 — core: bright white-hot center, accent mid, dark rim (depth)
        core = QRadialGradient(pos, r * 0.60)
        hot = theme.blend(QColor(theme.PAL.orb_core), col, 0.25)
        hot.setAlpha(int(245 * alpha_boost))
        mid = QColor(col); mid.setAlpha(int(210 * alpha_boost))
        rim = QColor(theme.PAL.base); rim.setAlpha(int(250 * alpha_boost))
        core.setColorAt(0.0, hot)
        core.setColorAt(0.45, mid)
        core.setColorAt(1.0, rim)
        p.setBrush(QBrush(core))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(pos, r * 0.46, r * 0.46)

        # 3 — inner coil ring: solid glow, dashed into reactor segments
        self._paint_coil(p, pos, r, col, alpha_boost)

        # 4 — state rings (pulse / reactive / rotating arcs)
        self._paint_rings(p, pos, r, col, alpha_boost)

        # 5 — outer rotating tick reticle
        self._paint_ticks(p, pos, r, col, alpha_boost)

        # 6 — JARVIS label dead-center
        self._paint_label(p, pos, diam, col, alpha_boost)

        # 7 — Orbital Halo Aperture (the former HUD brackets are removed).
        if self._halo_visible():
            self._paint_halo_aperture(p, pos, r, col, alpha_boost)

        if self.state == OrbState.SPEAKING:
            self._paint_waveform(p, pos, r, col)
        if self.state == OrbState.EXECUTING:
            self._paint_progress(p, pos, r, col)

        for pt in self._particles:
            a = int(max(0.0, min(1.0, pt[4])) * 200 * alpha_boost)
            pc = QColor(col); pc.setAlpha(a)
            p.setBrush(QBrush(pc))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(pt[0], pt[1]), 1.8, 1.8)

        if self._status_word and not self._docked:
            p.setPen(QPen(theme.qcolor(theme.PAL.text_dim, int(220 * self._opacity))))
            p.setFont(theme.header_font(13))
            p.drawText(
                QRectF(0, pos.y() + r * 1.45 + 18, self.width(), 30),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                self._status_word,
            )

    def _paint_coil(self, p: QPainter, pos: QPointF, r: float,
                    col: QColor, boost: float) -> None:
        """Inner arc-reactor coil: thick segmented ring, solid glow."""
        segs = int(self._reactor.get("coil_segments", 12))
        rr = r * 0.60
        rect = QRectF(pos.x() - rr, pos.y() - rr, rr * 2, rr * 2)
        span = 360.0 / segs
        gap = span * 0.22
        pen_w = max(2.5, r * 0.055)
        cc = QColor(col); cc.setAlpha(int(235 * boost))
        p.setPen(QPen(cc, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for s in range(segs):
            start = s * span + gap / 2 - self._rot * 0.25
            p.drawArc(rect, int(start * 16), int((span - gap) * 16))
        # halo behind the coil so it reads as light, not a line
        halo = QColor(col); halo.setAlpha(int(60 * boost))
        p.setPen(QPen(halo, pen_w * 2.6))
        p.drawEllipse(rect)

    def _paint_ticks(self, p: QPainter, pos: QPointF, r: float,
                     col: QColor, boost: float) -> None:
        """Outer HUD reticle: rotating tick marks, every Nth emphasized."""
        n = int(self._reactor.get("tick_count", 60))
        major_every = max(1, int(self._reactor.get("tick_major_every", 5)))
        rot = math.radians(self._tick_rot)
        r_in = r * 1.02
        for i in range(n):
            ang = rot + i * 2 * math.pi / n
            major = (i % major_every == 0)
            ln = r * (0.10 if major else 0.05)
            a = int((150 if major else 80) * boost)
            pc = QColor(col); pc.setAlpha(a)
            p.setPen(QPen(pc, 1.8 if major else 1.0))
            ca, sa = math.cos(ang), math.sin(ang)
            p.drawLine(
                QPointF(pos.x() + ca * r_in, pos.y() + sa * r_in),
                QPointF(pos.x() + ca * (r_in + ln), pos.y() + sa * (r_in + ln)))

    def _paint_label(self, p: QPainter, pos: QPointF, diam: float,
                     col: QColor, boost: float) -> None:
        label = str(self._reactor.get("label", "JARVIS"))
        min_diam = float(self._reactor.get("label_min_diam", 90))
        if diam < min_diam:
            label = label[:1]                 # docked mini: initial only
        size = max(7, int(diam * float(self._reactor.get("label_scale", 0.115))))
        font = theme.header_font(size)
        font.setLetterSpacing(font.SpacingType.PercentageSpacing, 160)
        p.setFont(font)
        breathe_a = 0.82 + 0.18 * math.sin(self._phase)
        tc = theme.blend(QColor(theme.PAL.orb_core), col, 0.18)
        tc.setAlpha(int(235 * boost * breathe_a))
        p.setPen(QPen(tc))
        p.drawText(
            QRectF(pos.x() - diam, pos.y() - diam / 2, diam * 2, diam),
            Qt.AlignmentFlag.AlignCenter, label)

    def _paint_halo_aperture(self, p: QPainter, pos: QPointF, r: float,
                             col: QColor, boost: float) -> None:
        """Three interrupted optical arcs, travelling nodes, and audio ticks."""
        h = config.section("ui.orb.halo_aperture")
        radii = h.get("radii", [1.32, 1.48, 1.66])
        gaps = h.get("arc_gaps_deg", [42, 67, 31])
        widths = h.get("line_thickness", [1.0, 1.0, 1.0])
        speed = float(h.get("rotation_dps", 2.0))
        opacity = float(h.get("opacity", 0.45))
        node_count = int(h.get("nodes", 6))
        tick_count = int(h.get("spectral_ticks", 18))
        tick_len = float(h.get("spectral_tick_length_ratio", 0.12))
        node_radius = float(h.get("node_radius_px", 2.0))
        for i, ratio in enumerate(radii):
            rr = r * float(ratio)
            rect = QRectF(pos.x() - rr, pos.y() - rr, rr * 2, rr * 2)
            gap = float(gaps[i % len(gaps)])
            start = ((-self._rot if i % 2 else self._rot) * speed / 90.0
                     + float(h.get("start_offset_deg", 0)) + i * gap)
            arc = 360.0 - gap
            pc = QColor(col); pc.setAlpha(int(255 * opacity * boost))
            p.setPen(QPen(pc, float(widths[i % len(widths)])))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(rect, int(start * 16), int(arc * 16))
        for n in range(node_count):
            layer = n % max(1, len(radii))
            rr = r * float(radii[layer])
            direction = -1 if layer % 2 else 1
            angle = math.radians((n * 360.0 / max(1, node_count))
                                 + direction * self._rot * speed / 90.0)
            pc = QColor(col); pc.setAlpha(int(255 * opacity * boost))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(pc)
            p.drawEllipse(QPointF(pos.x() + math.cos(angle) * rr,
                                  pos.y() + math.sin(angle) * rr),
                          node_radius, node_radius)
        response = float(h.get("audio_response", 1.0))
        for i in range(tick_count):
            angle = math.radians(i * 360.0 / max(1, tick_count) + self._tick_rot)
            pulse = max(0.0, math.sin(self._phase + i * response))
            pc = QColor(col); pc.setAlpha(int(255 * opacity * pulse * boost))
            rr = r * float(radii[-1])
            p.setPen(QPen(pc, float(h.get("spectral_tick_width_px", 1.0))))
            p.drawLine(QPointF(pos.x() + math.cos(angle) * rr,
                               pos.y() + math.sin(angle) * rr),
                       QPointF(pos.x() + math.cos(angle) * rr * (1 + tick_len),
                               pos.y() + math.sin(angle) * rr * (1 + tick_len)))

    def _error_flash_alpha(self) -> float:
        if self.state != OrbState.ERROR:
            return 1.0
        flashes = int(self._params(OrbState.ERROR).get("flash_count", 3))
        elapsed = time.monotonic() - self._flash_t0
        period = 0.22
        if elapsed > flashes * period:
            return 1.0
        return 0.25 + 0.75 * abs(math.sin(elapsed / period * math.pi))

    def _paint_rings(self, p: QPainter, pos: QPointF, r: float,
                     col: QColor, boost: float) -> None:
        rings = int(self._params(self.state).get("rings", 2))
        rect = lambda rr: QRectF(pos.x() - rr, pos.y() - rr, rr * 2, rr * 2)

        if self.state == OrbState.THINKING:
            # rotating arc segments
            for i in range(rings):
                rr = r * (0.72 + 0.16 * i)
                a = int((160 - i * 40) * boost)
                pc = QColor(col); pc.setAlpha(a)
                p.setPen(QPen(pc, 2.0 - i * 0.4))
                p.setBrush(Qt.BrushStyle.NoBrush)
                base = self._rot * (1.4 if i % 2 == 0 else -1.0) + i * 60
                for seg in range(3):
                    start = base + seg * 120
                    p.drawArc(rect(rr), int(start * 16), int(70 * 16))
            return

        for i in range(rings):
            rr = r * (0.78 + 0.16 * i)
            # LISTENING: outer ring reacts to mic amplitude
            if self.state == OrbState.LISTENING and i == rings - 1:
                rr += self._amp * r * 0.35
            pulse = 0.5 + 0.5 * math.sin(self._phase - i * 0.9)
            a = int((50 + 110 * pulse) * boost / (1 + i * 0.6))
            pc = QColor(col); pc.setAlpha(max(0, min(255, a)))
            p.setPen(QPen(pc, 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(rect(rr))

    def _paint_waveform(self, p: QPainter, pos: QPointF, r: float,
                        col: QColor) -> None:
        """Arc-reactor styled: radial bars around the outer ring."""
        r0 = r * 1.06
        wave = config.section("ui.orb.speaking.active_content.waveform") if self._docked \
            else config.section("ui.orb.speaking.empty.waveform")
        minimum = float(wave.get("minimum_length_px", 2))
        length_ratio = float(wave.get("length_ratio", 0.42))
        alpha_base = int(wave.get("alpha_base", 110))
        alpha_range = int(wave.get("alpha_range", 145))
        stroke = float(wave.get("stroke_px", 2.6))
        for i, level in enumerate(self._wave):
            ang = -math.pi / 2 + i * 2 * math.pi / self._wave_bars
            ln = minimum + level * r * length_ratio
            a = alpha_base + int(level * alpha_range)
            pc = QColor(col); pc.setAlpha(min(255, a))
            p.setPen(QPen(pc, stroke, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap))
            ca, sa = math.cos(ang), math.sin(ang)
            p.drawLine(QPointF(pos.x() + ca * r0, pos.y() + sa * r0),
                       QPointF(pos.x() + ca * (r0 + ln), pos.y() + sa * (r0 + ln)))

    def _paint_progress(self, p: QPainter, pos: QPointF, r: float,
                        col: QColor) -> None:
        rr = r * 0.86
        rect = QRectF(pos.x() - rr, pos.y() - rr, rr * 2, rr * 2)
        track = QColor(col); track.setAlpha(40)
        p.setPen(QPen(track, 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)
        arc = QColor(col); arc.setAlpha(230)
        p.setPen(QPen(arc, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(rect, 90 * 16, -int(self._progress * 360 * 16))


# ── keyboard test harness (delivery stage 2) ─────────────────────────────────
# Run:  python -m jarvis.ui.orb
#   1..6 → IDLE / LISTENING / THINKING / SPEAKING / EXECUTING / ERROR
#   d/u  → dock / undock      a → amplitude burst      p → progress +10 %
#   f    → fade-in replay     q → quit
if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication, QMainWindow

    app = QApplication(sys.argv)

    class Harness(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("OrbRenderer test harness — keys: 1-6 d u a p f q")
            self.resize(1000, 700)
            self.setStyleSheet(f"background: {theme.PAL.base};")
            self.orb = OrbRenderer(self)
            self.orb.setGeometry(0, 0, 1000, 700)
            self.orb.set_status_word("IDLE")

        def resizeEvent(self, e):
            self.orb.setGeometry(0, 0, self.width(), self.height())
            super().resizeEvent(e)

        def keyPressEvent(self, e):
            key = e.text().lower()
            states = {"1": OrbState.IDLE, "2": OrbState.LISTENING,
                      "3": OrbState.THINKING, "4": OrbState.SPEAKING,
                      "5": OrbState.EXECUTING, "6": OrbState.ERROR}
            if key in states:
                self.orb.set_state(states[key])
            elif key == "d":
                self.orb.dock(Corner.BOTTOM_RIGHT)
            elif key == "u":
                self.orb.undock()
            elif key == "a":
                self.orb.feed_amplitude(1.0)
            elif key == "p":
                self.orb.set_progress((self.orb._progress + 0.1) % 1.0)
            elif key == "f":
                self.orb.fade_in()
            elif key == "q":
                self.close()

    win = Harness()
    win.show()
    win.orb.fade_in()
    sys.exit(app.exec())
