"""Panel and peripheral lifecycle methods for MainWindow."""
from __future__ import annotations

import threading

from PyQt6.QtCore import QTimer

from jarvis.core import config, log
from jarvis.core.bus import BUS
from jarvis.core.command_palette import CommandPaletteModel
from jarvis.core.target_resolver import decide_and_close
from jarvis.ui.orb import OrbState

_logger = log.get("ui")


class WindowPanelsMixin:
    """Own ContentStage panels, command palette, and approval lifecycle."""

    def _on_info_card_shown(self, _data: dict) -> None:
        """Kartu info baru (§6.4/§7.2) → tampilkan panel info bila stage
        sedang kosong/info; panel aktif lain (vision/home) tidak direbut."""
        if self.info_panel is not None and \
                self.stage.current in (None, "info"):
            self.stage.show_child("info")

    def _toggle_studio_panel(self) -> None:
        """Toggle Studio local-only; ContentStage owns visibility, controller owns focus restore."""
        if self.content_studio is None:
            self._deferred_panel_notice("Content Studio", "panel tidak tersedia — lihat log")
            return
        self._studio_focus.toggle()
        self._sync_orb_visibility()

    def _set_studio_focus(self, active: bool) -> None:
        if self._studio_focus.set_studio_focus(bool(active)) and self.content_studio is not None:
            self.content_studio.set_studio_focus_active(bool(active))

    def _toggle_home_panel(self) -> None:
        """Buka Home lewat state LOADING; data/empty-state mengaktifkan panel."""
        if self.stage.current == "home" or self.stage.is_loading("home"):
            self._close_stage_panels()
            return
        if self.home_panel is None:
            self._deferred_panel_notice(
                "Home Assistant", "panel tidak tersedia — lihat log")
            return
        self.stage.begin_loading("home")
        self._sync_orb_visibility()
        self.home_panel.refresh()

    def _on_home_ready(self) -> None:
        if self.stage.is_loading("home"):
            self.stage.activate("home")
            self._sync_orb_visibility()

    def _deferred_panel_notice(self, name: str, detail: str | None = None) -> None:
        detail = detail or "tidak berada di ContentStage dan belum tersedia pada build ini"
        self.write_log(f"SYS: {name} — {detail}.")
        self.notifications.push(name, detail, "info")

    def go_home(self) -> None:
        """Clear ContentStage, return the orb to center, IDLE, panel undim."""
        self._close_stage_panels()
        self.write_log("SYS: Kembali ke tampilan utama.")

    def _close_stage_panels(self) -> None:
        """Tutup panel stage via cross-fade dan buang riwayat yang tak lagi
        relevan. Dipakai toggle, ESC, dan tombol kembali ke Home."""
        if getattr(self.stage, "current", None) == "studio":
            self._studio_focus.close()
        history = getattr(self, "stage_history", None)
        if history is not None:
            history.clear()
        self.stage.hide_all()
        self._sync_orb_visibility()
        self.orb.undock()
        self.orb.set_state(OrbState.IDLE)
        self.action_panel.set_dimmed(False)

    def _on_page_content(self, text: str, url: str) -> None:
        if self._pending_query is None:
            return
        query, self._pending_query = self._pending_query, None
        BUS.publish("info.card", kind="search", title=query,
                    lines=[text[:1600]], source=url, ts="")
        self._restore_orb()

    def _on_intent_event(self, d: dict) -> None:
        if d.get("intent") == "SEARCH_WEB" and d.get("meta", {}).get("url") \
                and self._pending_query is None and d.get("meta", {}).get("query"):
            if self.stage.current != "browser":
                self.run_search(d["meta"]["query"])

    def _build_palette_model(self) -> CommandPaletteModel:
        model = CommandPaletteModel()
        model.set_commands([
            {"label": "Go home", "action_id": "go_home"},
            {"label": "Toggle mute", "action_id": "toggle_mute"},
            {"label": "Toggle vision panel", "action_id": "toggle_vision_panel"},
            {"label": "Toggle gesture control", "action_id": "toggle_gesture_arm"},
            {"label": "Toggle Focus Mode", "action_id": "toggle_focus_mode"},
            {"label": "Toggle screen awareness", "action_id": "toggle_awareness"},
            {"label": "Open context timeline", "action_id": "open_timeline"},
            {"label": "Reopen last closed tab", "action_id": "reopen_last_tab"},
            {"label": "Open system browser", "action_id": "open_browser_agent"},
            {"label": "Manage monitor sources", "action_id": "manage_monitor_sources"},
        ])
        model.set_sites(dict(self.router._known_sites))
        try:
            from jarvis.core.router import _APP_HINTS
            model.set_apps(sorted(_APP_HINTS))
        except ImportError:
            pass
        try:
            model.set_recent(self.memory.get_recent_episodes(limit=15))
        except Exception:
            pass
        try:
            model.set_macros(self.memory.list_macros(approved_only=True))
        except Exception:
            pass
        return model

    _PALETTE_COMMANDS = {
        "go_home": lambda self: self.go_home(),
        "toggle_mute": lambda self: self.toggle_mute(),
        "toggle_vision_panel": lambda self: self.toggle_vision_panel(),
        "toggle_gesture_arm": lambda self: self.toggle_gesture_arm(),
        "toggle_focus_mode": lambda self: self._toggle_focus_mode(),
        "toggle_awareness": lambda self: self._toggle_awareness(),
        "open_timeline": lambda self: self._toggle_timeline(),
        "reopen_last_tab": lambda self: self._reopen_last_tab(),
        "open_browser_agent": lambda self: self.open_browser_agent(),
        "manage_monitor_sources": lambda self: self._open_monitor_source_sheet(),
    }

    def _on_palette_activated(self, cand) -> None:
        if cand.kind == "command" and cand.action_id in self._PALETTE_COMMANDS:
            self._PALETTE_COMMANDS[cand.action_id](self)
        elif cand.kind == "app":
            self.open_app(cand.action_id)
        elif cand.kind == "site":
            self.open_url(cand.action_id)
        elif cand.kind == "macro":
            steps = cand.meta.get("steps", [])
            self.write_log(f"SYS: macro '{cand.label}' — {len(steps)} step(s) tersimpan. "
                           "Eksekusi macro belum diaktifkan tanpa konfirmasi eksplisit lebih lanjut.")
        elif cand.kind == "recent":
            self.write_log(f"SYS: dari riwayat — {cand.label}")

    def _open_monitor_source_sheet(self) -> None:
        self.monitor_source_sheet.open_centered(
            self.centralWidget().width(), self.centralWidget().height())

    def _toggle_command_palette(self) -> None:
        if self.command_palette.isVisible():
            self.command_palette.hide()
            return
        self.command_palette.model = self._build_palette_model()
        c = self.centralWidget()
        self.command_palette.open_centered(c.width(), c.height())

    def _toggle_timeline(self) -> None:
        if self.timeline.isVisible():
            self.timeline.hide()
            return
        c = self.centralWidget()
        self.timeline.open_centered(c.width(), c.height())

    def _toggle_focus_mode(self) -> None:
        duration = float(config.get("live_comments.focus_mode.default_duration_s", 1800))
        active = self._focus_mode.toggle(duration_s=duration)
        self.action_panel.set_indicator("focus_mode", active)
        self.action_panel.set_button_state(
            "focus_mode", "Focus Mode — AKTIF (klik untuk nonaktif)"
            if active else "Focus Mode — pause comment narration")
        self.write_log(f"SYS: Focus Mode {'AKTIF' if active else 'nonaktif'}.")
        self.notifications.push("Focus Mode", "AKTIF" if active else "nonaktif", "info")
        self.notifications.set_focus_mode(active)

    def _toggle_awareness(self) -> None:
        from jarvis.core import screen_awareness
        aw = screen_awareness.get()
        if not aw.running:
            aw.start()
            self.action_panel.set_indicator("awareness", True)
            self.action_panel.set_button_state("awareness", "Screen awareness — ACTIVE (click to pause)")
            self.write_log("SYS: screen awareness AKTIF.")
            self.notifications.push("Awareness", "started", "info")
        elif aw.paused:
            aw.resume()
            self.action_panel.set_indicator("awareness", True)
            self.action_panel.set_button_state("awareness", "Screen awareness — ACTIVE (click to pause)")
            self.write_log("SYS: screen awareness dilanjutkan.")
            self.notifications.push("Awareness", "resumed", "info")
        else:
            aw.pause()
            self.action_panel.set_indicator("awareness", False)
            self.action_panel.set_button_state("awareness", "Screen awareness — PAUSED (click to resume)")
            self.write_log("SYS: screen awareness dijeda.")
            self.notifications.push("Awareness", "paused", "info")

    def _begin_close_target(self, target: str) -> None:
        if not target:
            self.write_log("SYS: sebutkan target yang ingin ditutup.")
            return
        decision = decide_and_close(target, self._target_resolver)
        if decision.status == "executed":
            detail = decision.result.detail if decision.result else "closed"
            self.write_log(f"SYS: {detail} — {target}")
            self.notifications.push("Closed", target, "success")
        elif decision.status == "no_target":
            self.write_log(f"SYS: tidak menemukan jendela untuk '{target}'.")
            self.notifications.push("No target", target, "warning")
        else:
            self._pending_close_decision = decision
            names = ", ".join(c.window.title for c in decision.candidates[:3])
            self.write_log(
                f"SYS: konfirmasi diperlukan untuk menutup '{target}' ({decision.reason}). "
                f"Kandidat: {names or '-'}. Ucapkan/ketik 'confirm' atau gestur jempol untuk "
                f"melanjutkan, 'cancel' atau jempol turun untuk membatalkan.")
            self.notifications.push("Confirm required", decision.reason, "warning")

    def _execute_remote_proposal(self, action: str) -> bool:
        wanted = {"focus_mode_enable": True, "focus_mode_disable": False}.get(action)
        if wanted is not None:
            if self._focus_mode.active != wanted:
                self._toggle_focus_mode()
            return self._focus_mode.active == wanted
        if not str(action).startswith("media_"):
            return False
        try:
            import asyncio
            from jarvis.agent.remote_media_execution import execute_proposal
            from jarvis.agent.tools.browser import BrowserMedia

            result = asyncio.run(execute_proposal(action, runner=BrowserMedia().run))
            return bool(result.get("ok"))
        except Exception:
            return False

    def _on_remote_proposal_pending(self, data: dict) -> None:
        proposal_id = str(data.get("proposal_id") or "")
        actor_id = str(data.get("actor_id") or "")
        session_id = str(data.get("session_id") or "")
        if self._remote_proposal_sheet.present(proposal_id, actor_id=actor_id,
                                               session_id=session_id):
            self.notifications.push("Remote proposal", "Menunggu persetujuan lokal", "warning")

    def _on_voice_proposal_pending(self, data: dict) -> None:
        """Voice may request; only this desktop UI may approve a named action."""
        proposal_id = str(data.get("proposal_id") or "")
        action = str(data.get("action") or "")
        if not proposal_id or action not in {"focus_mode_enable", "focus_mode_disable"}:
            return
        self._pending_voice_proposal_id = proposal_id
        self.write_log("SYS: proposal voice diterima — ketik 'confirm' atau 'cancel'.")
        self.notifications.push("Voice proposal", "Menunggu persetujuan lokal", "warning")

    def _approve_voice_proposal(self) -> bool:
        proposal_id = self._pending_voice_proposal_id
        if not proposal_id:
            return False
        from jarvis.integrations.voice_desktop_proposals import get_queue

        def execute(action: str) -> bool:
            wanted = action == "focus_mode_enable"
            if self._focus_mode.active != wanted:
                self._toggle_focus_mode()
            return self._focus_mode.active == wanted

        self._pending_voice_proposal_id = None
        result = get_queue().approve_local(proposal_id, executor=execute)
        if result.get("executed"):
            self.write_log("SYS: proposal voice disetujui secara lokal.")
            return True
        self.write_log("SYS: proposal voice tidak dapat dijalankan.")
        return True

    def start_countdown(self, duration_s: int) -> bool:
        """Mulai countdown native via FACADE lokal (Phase 29); orb progress.

        UI tidak pernah bypass facade — durasi terbatas (1..3600s), murni
        lokal, tanpa remote/network/write.
        """
        from jarvis.ui.countdown_driver import CountdownDriver

        outcome = self._facades.invoke("start_countdown",
                                       duration_s=duration_s)
        if not outcome.get("ok"):
            return False
        timer = outcome["artifacts"]["timer"]
        if self._countdown_ticker is None:
            self._countdown_ticker = QTimer(self)
            self._countdown_ticker.setInterval(200)
            self._countdown_ticker.timeout.connect(self._on_countdown_tick)
        self._countdown = timer
        self._countdown_driver = CountdownDriver(
            timer=timer,
            orb=self.orb,
            set_progress=self.orb.set_progress,
            ticker_start=self._countdown_ticker.start,
            ticker_stop=self._countdown_ticker.stop,
        )
        self._countdown_driver.attach()
        self.write_log(f"Timer {duration_s} dtk berjalan (lokal).")
        return True

    def cancel_countdown(self) -> bool:
        """Batalkan countdown yang berjalan (idempotent)."""
        if self._countdown is None:
            return False
        cancelled = self._countdown.cancel()
        if cancelled:
            self.write_log("Timer dibatalkan.")
        return cancelled

    def _on_countdown_tick(self) -> None:
        if self._countdown_driver is not None:
            self._countdown_driver.tick()

    def _on_confirm(self, _d: dict) -> None:
        if self._approve_voice_proposal():
            return
        if self._pending_close_decision is None:
            return
        decision, self._pending_close_decision = self._pending_close_decision, None
        if not decision.candidates:
            return
        top = decision.candidates[0]
        result_decision = decide_and_close("", self._target_resolver,
                                           confirmed_target=top.window)
        ok = result_decision.status == "executed"
        detail = result_decision.result.detail if result_decision.result else "failed"
        self.write_log(f"SYS: {detail} — {top.window.title}")
        self.notifications.push("Closed" if ok else "Failed", top.window.title,
                                "success" if ok else "error")

    def _on_cancel(self, _d: dict) -> None:
        if self._pending_voice_proposal_id is not None:
            self._pending_voice_proposal_id = None
            self.write_log("SYS: proposal voice dibatalkan secara lokal.")
            return
        if self._pending_close_decision is not None:
            self._pending_close_decision = None
            self.write_log("SYS: aksi dibatalkan.")
            self.notifications.push("Cancelled", "", "info")

    def _reopen_last_tab(self) -> None:
        item = self._closed_items.pop_last("tab")
        if item is None:
            self.write_log("SYS: tidak ada tab yang bisa dibuka kembali.")
            return
        url = item["meta"].get("url", "")
        if url:
            self.open_url(url)

    def _on_sentiment(self, d: dict) -> None:
        self.orb.feed_sentiment(float(d.get("value", 0.0)))

    def _on_remote_setup_pending(self, d: dict) -> None:
        """Tampilkan approval lokal hanya untuk runtime-owned SetupQueue."""
        from jarvis.agent.remote_setup import get_setup_queue

        request_id = str(d.get("request_id", "") or "")
        if not request_id:
            return
        sheet = getattr(self, "remote_setup_sheet", None)
        if sheet is None:
            return
        # The BUS carries only the opaque request id; the queue is the
        # process-local runtime-owned instance, never a caller-supplied object.
        queue = getattr(self, "_setup_queue", None) or get_setup_queue()
        sheet._queue = queue
        if not sheet.present(request_id):
            return
        c = self.centralWidget()
        if c is not None:
            w, h = min(520, c.width()), min(320, c.height())
            sheet.setGeometry((c.width() - w) // 2, (c.height() - h) // 2, w, h)
        sheet.raise_()

    def toggle_vision_panel(self) -> None:
        """Klik ikon vision yang sama menutup, termasuk selama LOADING."""
        visible = not (self.stage.current == "vision"
                       or self.stage.is_loading("vision"))
        self._set_vision_visible(visible)

    def _set_vision_visible(self, visible: bool) -> None:
        _logger.info("vision.panel", visible=bool(visible),
                     stage=str(getattr(self.stage, "current", "") or ""))
        if visible:
            if self.vision is not None and not self.vision.alive:
                self.vision.start()
            self.stage.begin_loading("vision")
            self._sync_orb_visibility()
            if self.vision_panel.has_payload:
                self.stage.activate("vision")
        elif self.stage.current == "vision" or self.stage.is_loading("vision"):
            self._close_stage_panels()
            self._sync_orb_visibility()
            self._restore_orb()
            self.orb.undock()
            if self.vision is not None and self.vision.alive and not self.vision.armed:
                threading.Thread(target=self.vision.stop, daemon=True,
                                 name="vision-stop").start()

    def toggle_gesture_arm(self) -> None:
        self.set_gesture_armed(not (self.vision.armed if self.vision else False))

    def set_gesture_armed(self, armed: bool) -> None:
        if self.vision is None:
            self.write_log("ERR: subsistem vision tidak tersedia.")
            return
        if armed:
            if not self.vision.alive:
                self.vision.start()
            self.vision.arm()
            self.stage.begin_loading("vision")
            if self.vision_panel.has_payload:
                self.stage.activate("vision")
            self.write_log("SYS: Kontrol gestur DIAKTIFKAN — telapak terbuka "
                           "3 detik untuk berhenti darurat.")
        else:
            self.vision.disarm()
            self.write_log("SYS: Kontrol gestur dinonaktifkan.")

    def _on_gesture(self, d: dict) -> None:
        g = d.get("gesture", "")
        if g == "PEACE_V":
            self.toggle_mute()
        elif g == "SPREAD_TO_FIST":
            self._do_interrupt()
        elif g in ("THUMBS_UP", "THUMBS_DOWN"):
            BUS.publish("confirm" if g == "THUMBS_UP" else "cancel")

    def _on_vision_status(self, d: dict) -> None:
        if not d.get("alive", True):
            self.write_log(f"SYS: vision — {d.get('detail', 'offline')}")
            self.notifications.push("Vision", d.get("detail", "offline"), "warning")
