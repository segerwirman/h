"""Command execution methods for the Mark XLIX main window."""
from __future__ import annotations

import re
import sys
import threading

from jarvis.core import config, log
from jarvis.core.bus import BUS
from jarvis.ui.orb import OrbState

_logger = log.get("ui")

_LEGACY_STATE_MAP = {
    "LISTENING": OrbState.LISTENING,
    "SPEAKING": OrbState.SPEAKING,
    "THINKING": OrbState.THINKING,
    "PROCESSING": OrbState.EXECUTING,
    "SLEEPING": OrbState.IDLE,
    "INITIALISING": OrbState.BOOT,
    "MUTED": OrbState.IDLE,
    "ERROR": OrbState.ERROR,
    "IDLE": OrbState.IDLE,
    "EXECUTING": OrbState.EXECUTING,
}


class CommandActionsMixin:
    """Execute routed actions using state and seams owned by MainWindow."""

    _YT_WATCH_RE = re.compile(
        r"(?:youtube\.com/watch\?(?:.*&)?v=|youtu\.be/)([\w-]{6,})", re.I)

    def open_url(self, url: str) -> None:
        if not url:
            return
        # deterministic URL policy (§6): only allowlisted schemes may load;
        # a schemeless value is treated as https, never executed via a shell.
        # Explicit-scheme detection requires "://" so "localhost:8080" stays
        # a host:port, not a scheme.
        allowed = set(config.get("browser.allowed_schemes", ["https", "http"]))
        m_scheme = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*)://", url)
        if m_scheme:
            if m_scheme.group(1).lower() not in allowed:
                self.write_log(
                    f"ERR: skema URL tidak diizinkan — {m_scheme.group(1)}://")
                return
        elif re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:(?!\d)", url):
            self.write_log("ERR: skema URL tidak diizinkan.")
            return          # javascript:, data:… — reject; host:port passes
        else:
            url = f"https://{url}"
        # MK50 §7 — panel browser dibuang: URL tervalidasi dibuka di browser
        # sistem. Skema tetap dibatasi allowlist di atas (keamanan tak turun).
        from jarvis.core.native_actions import open_external_url

        result = open_external_url(url)
        if result.ok:
            self.write_log(f"SYS: Membuka {url} di browser sistem.")
        else:
            self.write_log(
                f"ERR: browser sistem gagal dibuka — {result.detail}")

    def _close_named_app(self, slots: dict) -> None:
        """Tutup aplikasi BERNAMA di worker thread — guard ada di dalamnya."""
        name = str(slots.get("value") or "").strip()
        all_windows = bool(slots.get("all_windows"))

        def _run() -> None:
            try:
                from actions.close_app import close_app
                outcome = close_app(name, all_windows=all_windows)
            except Exception as exc:                         # noqa: BLE001
                outcome = None
                self.write_log(f"ERR: gagal menutup {name} — {str(exc)[:80]}")
            if outcome is not None:
                self.write_log(f"SYS: {outcome.message}")
                self._speak_line(outcome.message)

        threading.Thread(target=_run, daemon=True, name="close-app").start()

    def _request_self_shutdown(self) -> None:
        """'matikan dirimu' — minta konfirmasi, jangan langsung berhenti."""
        from jarvis.integrations import voice_safety

        message, _ok = voice_safety.handle_shutdown({})
        prompt = ("Anda yakin ingin saya berhenti sepenuhnya? "
                  "Jawab 'ya' untuk konfirmasi.")
        self.write_log(f"Jarvis: {prompt}")
        self._speak_line(prompt)
        self._pending_self_shutdown = True
        _ = message

    def _confirm_self_shutdown(self, text: str) -> bool:
        """``True`` bila teks ini menjawab permintaan berhenti."""
        if not getattr(self, "_pending_self_shutdown", False):
            return False
        low = text.strip().lower()
        if low in self._CONFIRM_WORDS or low in ("ya", "yes", "iya", "betul"):
            self._pending_self_shutdown = False
            from jarvis.integrations import voice_safety
            self.write_log("SYS: Menutup dengan rapi…")
            voice_safety.graceful_shutdown()
            return True
        if low in self._CANCEL_WORDS or low in ("tidak", "jangan", "batal",
                                                "no"):
            self._pending_self_shutdown = False
            self.write_log("SYS: Dibatalkan — saya tetap di sini.")
            return True
        return False

    def _ask_clarify(self, slots: dict) -> None:
        """Bertanya satu kalimat, lalu menunggu — bukan menebak."""
        from jarvis.core import clarify_state

        question = str(slots.get("question") or "Maksud Anda yang mana?")
        clarify_state.set_pending(
            topic=str(slots.get("topic") or ""), question=question,
            options=list(slots.get("options") or []),
            app=str(slots.get("app") or ""), url=str(slots.get("url") or ""))
        self.write_log(f"Jarvis: {question}")
        self._speak_line(question)

    def _handle_clarify_answer(self, text: str) -> bool:
        """``True`` bila teks ini adalah jawaban dan sudah ditindaklanjuti."""
        from jarvis.core import clarify_state

        outcome = clarify_state.resolve(text)
        if outcome is None:
            return False
        kind, ask = outcome
        if kind == "declined":
            self.write_log("SYS: Dibatalkan.")
            return True
        if kind == "app":
            self.open_app(ask.app or ask.topic)
        else:
            self.open_url(ask.url)
        self.write_log(
            f"SYS: Dicatat — '{ask.topic}' berarti "
            f"{'aplikasi' if kind == 'app' else 'browser'}.")
        return True

    def open_app(self, app: str) -> None:
        self.orb.set_state(OrbState.EXECUTING)

        def _run():
            try:
                from actions.open_app import launch_application

                outcome = launch_application(app)
                level = "SYS" if outcome.ok else "ERR"
                self.write_log(f"{level}: {outcome.message}")
            except Exception as e:
                self.write_log(f"ERR: gagal membuka {app} — {str(e)[:80]}")
            finally:
                self._restore_orb()
        threading.Thread(target=_run, daemon=True, name="open-app").start()

    def run_system(self, slots: dict, text: str) -> None:
        action = slots.get("action", "")
        if action == "gesture_arm":
            self.set_gesture_armed(True)
            return
        if action == "gesture_disarm":
            self.set_gesture_armed(False)
            return
        if action == "vision_open":                    # Change 5
            self._set_vision_visible(True)
            return
        if action == "vision_close":
            self._set_vision_visible(False)
            return
        if action == "home":                           # Change 7
            self.go_home()
            return
        if action == "reply":                          # Change 1.5
            if self.stage.current == "browser":
                self.reply_flow.begin(slots.get("value", ""))
            else:
                self._speak_line("Buka halaman pesan terlebih dahulu, sir.")
            return
        if action == "close_app":
            self._close_named_app(slots)
            return
        if action == "close_blocked":
            name = slots.get("value", "itu")
            msg = (f"Saya tidak menutup '{name}' — proses itu saya sendiri. "
                   f"Kalau memang ingin saya berhenti, katakan 'matikan "
                   f"dirimu' dan saya akan minta konfirmasi dulu.")
            self.write_log(f"SYS: {msg}")
            self._speak_line(msg)
            return
        if action == "shutdown_jarvis_request":
            self._request_self_shutdown()
            return
        if action == "close_target":                    # redesign §13
            target = slots.get("value", "").strip()
            self._begin_close_target(target)
            return
        if action == "reopen_last_tab":                  # redesign §13
            self._reopen_last_tab()
            return
        if action == "calorie_analyze":                  # MK50 — kalori kamera
            self._run_calorie_analysis(slots.get("value", "") or "")
            return
        self.orb.set_state(OrbState.EXECUTING)

        def _run():
            try:
                from actions.computer_settings import computer_settings
                result = computer_settings(
                    parameters={"action": action, "description": text,
                                "value": slots.get("value", "")},
                    response=None, player=None)
                self.write_log(f"SYS: {result or 'Selesai.'}")
            except Exception as e:
                self.write_log(f"ERR: {action} — {str(e)[:80]}")
            finally:
                self._restore_orb()
        threading.Thread(target=_run, daemon=True, name="system-action").start()

    def run_native_task(self, slots: dict, text: str) -> None:
        """Execute compatibility messaging/task intents using native Jarvis.

        Telegram keeps its existing direct adapter. Other external actions go
        through the native agent registry so tool-level confirmation and audit
        logging remain mandatory. There is intentionally no process/CLI
        fallback.
        """
        tier = int(slots.get("tier", 3))

        _tg_running = False
        if tier == 2 and slots.get("action") == "send" \
                and slots.get("platform", "telegram") == "telegram":
            try:
                from jarvis.agent.adapters import telegram as tg
                _tg_running = tg.TelegramService.get().running
            except Exception:
                _tg_running = False
        if _tg_running:
            msg = slots.get("text") or text
            self.orb.set_state(OrbState.EXECUTING)

            def _native_send():
                try:
                    from jarvis.agent.adapters import telegram as tg
                    ok = tg.send_from_anywhere(msg)
                    if ok:
                        self.write_log("SYS: Pesan terkirim ke telegram.")
                        self._speak_line("Pesan terkirim ke telegram, sir.")
                    else:
                        self.write_log("ERR: kirim telegram gagal.")
                        self._speak_line("Maaf, pengiriman pesan gagal.")
                finally:
                    self._restore_orb()
            threading.Thread(target=_native_send, daemon=True,
                             name="agent-tg-send").start()
            return

        task = slots.get("task") or text
        if tier == 2 and slots.get("action") == "send":
            platform = str(slots.get("platform", "") or "").strip().lower()
            message = str(slots.get("text") or "").strip()
            if platform == "whatsapp":
                task = (
                    "Gunakan tool whatsapp_send_message untuk memenuhi "
                    f"permintaan user berikut: {text}. Payload setelah nama "
                    f"platform: {message}. Gunakan hanya kontak allowlist; "
                    "jika kontak atau isi pesan ambigu, minta klarifikasi."
                )
            else:
                task = (
                    f"Kirim pesan melalui adapter native {platform}. "
                    f"Isi pesan: {message}"
                )
        self._run_agent_native(task)

    def run_hermes(self, slots: dict, text: str, **_) -> None:
        """Deprecated method alias; execution is permanently native."""
        self.run_native_task(slots, text)

    def _run_agent_native(self, task: str) -> None:
        """MK50 — jalankan T2+ dengan ACK lalu laporan hasil yang konkret."""
        from jarvis.agent import conversation_context, interactive_dispatch
        from jarvis.agent import delivery_lifecycle
        from jarvis.agent.adapters.ui import UIAdapter

        conversation_id = "typed-desktop"
        if conversation_context.is_artifact_reference(task):
            art_path, art_kind = conversation_context.STORE.last_artifact(
                conversation_id)
            if art_path and self._open_artifact(art_path, art_kind):
                return
            if not art_path:
                self.write_log("SYS: Belum ada hasil terbaru untuk dibuka.")
                self._speak_line(
                    "Belum ada hasil terbaru yang bisa saya buka, sir.")
                return

        # Structured resolution: when several tasks could match, ASK the user
        # instead of dispatching a block the agent is expected to interpret.
        resolution = conversation_context.STORE.resolve(conversation_id, task)
        if resolution.kind == "ambiguous":
            candidates = " / ".join(resolution.candidates)
            self.write_log(
                "Jarvis: Anda sedang menjalankan beberapa tugas: "
                f"{candidates}. Sebutkan tugas mana yang dimaksud.")
            self._speak_line(
                "Anda sedang menjalankan beberapa tugas, sir. "
                "Sebutkan yang mana yang ingin dilanjutkan.")
            return
        task = conversation_context.STORE.augment(conversation_id, task)
        self._record_task_result("TUGAS", task)
        self.orb.set_state(OrbState.EXECUTING)
        task_scope = {"id": ""}

        def _on_task(metadata) -> None:
            task_scope["id"] = str(getattr(metadata, "id", "") or "")
            conversation_context.STORE.begin_task(
                conversation_id,
                task_id=task_scope["id"],
                task=str(getattr(metadata, "title", "") or task),
                source="typed",
            )

        def _speak_scoped(line: str, kind: str) -> None:
            try:
                self._speak_line(line, kind=kind, turn=task_scope["id"])
            except TypeError:
                # Test/legacy window doubles may still expose the old one-arg
                # speech surface. Production MainWindow accepts both labels.
                self._speak_line(line)

        def _typed_terminal_fallback(text: str, *, error: bool = False) -> bool:
            """Keep terminal delivery on the desktop surface when one sink fails."""
            delivered = False
            prefix = "ERR: agent task — " if error else "Agent: "
            try:
                self.write_log(prefix + str(text or "")[:600])
                delivered = True
            except Exception:
                pass
            try:
                emitter = getattr(self, "_content_sig", None)
                if emitter is not None and callable(getattr(emitter, "emit", None)):
                    emitter.emit("AGENT — hasil tugas" if not error else
                                 "AGENT — gagal", str(text or ""))
                    delivered = True
            except Exception:
                pass
            return delivered

        def _on_ack(_raw: str, report: str):
            delivery_lifecycle.acknowledged("typed", report)
            _speak_scoped(report, "ack")

        def _on_done(result: str, report: str):
            try:
                delivery = delivery_lifecycle.success(
                    result, task, source="typed", naturalize=True
                )
                conversation_context.STORE.remember_success(
                    conversation_id, task_id=task_scope["id"], task=task,
                    delivery=delivery,
                )
                short = delivery.display_text[:600]
                self._record_task_result("HASIL", delivery.display_text)
                self.write_log(f"Agent: {short}")
                self._content_sig.emit("AGENT — hasil tugas",
                                       delivery.display_text)
                _speak_scoped(delivery.speech_text, "final")
                self._restore_orb()
                return True
            except Exception:                                # noqa: BLE001
                conversation_context.STORE.fail_task(
                    conversation_id, task_scope["id"])
                # Terminal delivery must remain visible on the same surface
                # even when one sink (content panel, speech, orb) fails.
                return _typed_terminal_fallback(report or str(result or ""))

        def _on_error(err: str, report: str):
            try:
                delivery = delivery_lifecycle.failure(err, task, source="typed")
                self._record_task_result("GAGAL", delivery.display_text)
                self.write_log(f"ERR: agent task — "
                               f"{delivery.display_text[:160]}")
                _speak_scoped(delivery.speech_text, "final")
                self._restore_orb()
                return True
            except Exception:                                # noqa: BLE001
                conversation_context.STORE.fail_task(
                    conversation_id, task_scope["id"])
                return _typed_terminal_fallback(
                    report or str(err or ""), error=True
                )

        started = interactive_dispatch.start(
            task, adapter=UIAdapter(self, source="typed"), on_task=_on_task,
            on_ack=_on_ack, on_done=_on_done, on_error=_on_error)
        if started:
            self.write_log(f"SYS: Agent mengerjakan — {task[:90]} …")
        else:
            self.write_log(
                "SYS: Agent belum siap (provider belum dikonfigurasi) atau "
                "tugas serupa masih berjalan."
            )

    def _open_artifact(self, path: str, kind: str = "file") -> bool:
        """Buka artefak terakhir (gambar/file) secara lokal. Return False bila
        file hilang sehingga caller bisa jujur ke user."""
        import os
        clean = str(path or "").strip()
        if not clean or not os.path.exists(clean):
            self.write_log(f"SYS: File tidak ditemukan lagi — {clean}")
            self._speak_line("Berkasnya sudah tidak ada, sir.")
            return False
        name = os.path.basename(clean)
        if kind == "image" and callable(getattr(self, "show_image", None)):
            try:
                self.show_image(clean, f"Ini {name}, sir.")
            except Exception:                                # noqa: BLE001
                pass
        try:
            if os.name == "nt":
                os.startfile(clean)                          # noqa: S606
            else:
                import subprocess
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, clean])
        except Exception as exc:                             # noqa: BLE001
            self.write_log(f"ERR: gagal membuka {name} — {type(exc).__name__}")
            self._speak_line(f"Maaf sir, saya gagal membuka {name}.")
            return False
        self.write_log(f"SYS: Membuka {name} …")
        self._speak_line(f"Ini {name} yang tadi saya buat, sir.")
        return True

    def show_image(self, path: str, caption: str = "") -> None:
        """Tampilkan gambar di ContentStage (dipakai UIAdapter.send_image).
        Best-effort: bila stage tidak mendukung, hanya catat path di log."""
        clean = str(path or "").strip()
        emitter = getattr(self, "_content_sig", None)
        stage = getattr(self, "stage", None)
        shown = False
        if stage is not None and hasattr(stage, "show_image"):
            try:
                stage.show_image(clean, caption)
                shown = True
            except Exception:                                # noqa: BLE001
                shown = False
        if not shown and emitter is not None:
            try:
                emitter.emit("AGENT — gambar", f"{caption}\n{clean}".strip())
                shown = True
            except Exception:                                # noqa: BLE001
                shown = False
        if not shown:
            self.write_log(f"SYS: gambar tersimpan — {clean} {caption}".rstrip())

    def _run_calorie_analysis(self, question: str = "") -> None:
        """MK50 — analisis kalori makanan dari frame kamera live; hasil
        muncul sebagai pop-up DI DALAM frame kamera (CalorieOverlay) plus
        satu kalimat suara. Kamera dibuka otomatis bila belum."""
        if self.vision is None:
            self.write_log("ERR: subsistem vision tidak tersedia.")
            self._speak_line("Subsistem kamera tidak tersedia, sir.")
            return
        self._set_vision_visible(True)
        self.orb.set_state(OrbState.EXECUTING)
        self.write_log("SYS: Menganalisis kalori makanan di kamera …")
        BUS.publish("vision.calories", state="analyzing",
                    message="Menganalisis makanan…")

        def _work():
            try:
                jpeg = self.vision.latest_frame_jpeg(timeout=6.0)
                if not jpeg:
                    BUS.publish("vision.calories", state="error",
                                message="Kamera belum siap — coba lagi.")
                    self._speak_line("Kamera belum siap, sir.")
                    return
                from jarvis.vision import food_calories
                analysis = food_calories.analyze_jpeg(jpeg, question)
                if analysis.error:
                    BUS.publish("vision.calories", state="error",
                                message=analysis.error)
                else:
                    BUS.publish("vision.calories", state="result",
                                analysis=analysis)
                    self.write_log("Jarvis: " + analysis.summary_line())
                self._speak_line(analysis.summary_line())
            except Exception as e:
                _logger.error("calorie.failed", error=str(e)[:150])
                BUS.publish("vision.calories", state="error",
                            message=str(e)[:120])
            finally:
                self._restore_orb()

        threading.Thread(target=_work, daemon=True,
                         name="calorie-analysis").start()

    def _chat(self, text: str) -> None:
        # live voice pipeline first (it answers with TTS); NLP fallback
        if self.on_text_command is not None:
            threading.Thread(target=self.on_text_command, args=(text,),
                             daemon=True).start()
            return
        if self.assistant is None:
            self.write_log("ERR: tidak ada kanal percakapan yang aktif.")
            return
        self.orb.set_state(OrbState.THINKING)

        def _run():
            resp = self.assistant.handle_blocking(text)
            self.write_log(f"Jarvis: {resp.text}")
            if resp.show_on_stage:
                self._content_sig.emit(resp.source, resp.text)
            self._restore_orb()
        threading.Thread(target=_run, daemon=True, name="nlp-chat").start()

    def _restore_orb(self) -> None:
        state = _LEGACY_STATE_MAP.get(self._legacy_state, OrbState.IDLE)
        if state in (OrbState.EXECUTING, OrbState.THINKING):
            state = OrbState.IDLE
        self._state_sig.emit(state.value)

    def open_browser_agent(self, slots: dict | None = None) -> None:
        """MK50 §7 — panel browser dibuang dari ContentStage: perintah
        "buka browser" membuka browser sistem. Alur web bertujuan (multi-
        langkah) ditangani agent lewat browser_* tools (Playwright)."""
        slots = slots or {}
        from jarvis.core.native_actions import open_external_url

        url = slots.get("url") or str(config.get(
            "router.known_sites.google", "https://www.google.com"))
        result = open_external_url(url)
        if result.ok:
            self.write_log("SYS: dibuka di browser sistem (panel browser "
                           "sudah dipensiunkan, MK50 §7).")
        else:
            self.write_log(
                f"ERR: browser sistem gagal dibuka — {result.detail}")

    def _window_control_registry(self):
        if self.window_controls is None:
            from jarvis.core.window_controls import WindowControlRegistry
            self.window_controls = WindowControlRegistry(
                own_window=self, resolver=self._target_resolver)
        return self.window_controls
