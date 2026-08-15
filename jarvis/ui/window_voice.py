"""Voice, speech, state, logging, and upload lifecycle for MainWindow."""
from __future__ import annotations

import sys
import threading
import time

from PyQt6.QtCore import QTimer

from jarvis.agent.router import Tier as ExecutionTier
from jarvis.agent.router import classify as _classify_execution_default
from jarvis.core import config, log
from jarvis.core.bus import BUS
from jarvis.core.router import Intent
from jarvis.nlp.summarize import ACTIVITY_LOG
from jarvis.ui.orb import Corner, OrbState, PresentationMode
from jarvis.ui.stage import ContentStatus
from jarvis.ui.window_widgets import ApiKeySheet

_logger = log.get("ui")

_LEGACY_STATE_MAP = {
    "LISTENING": OrbState.LISTENING, "SPEAKING": OrbState.SPEAKING,
    "THINKING": OrbState.THINKING, "PROCESSING": OrbState.EXECUTING,
    "SLEEPING": OrbState.IDLE, "INITIALISING": OrbState.BOOT,
    "MUTED": OrbState.IDLE, "ERROR": OrbState.ERROR,
    "IDLE": OrbState.IDLE, "EXECUTING": OrbState.EXECUTING,
}


def classify_execution(text: str, context: dict):
    """Preserve the legacy ``window.classify_execution`` injection seam."""
    window = sys.modules.get("jarvis.ui.window")
    override = getattr(window, "classify_execution", None)
    if override is not None and override is not classify_execution:
        return override(text, context)
    return _classify_execution_default(text, context)


def _agent_ask_active() -> bool:
    window = sys.modules.get("jarvis.ui.window")
    override = getattr(window, "_agent_ask_active", None)
    if override is not None and override is not _agent_ask_active:
        return bool(override())
    try:
        from jarvis.agent.adapters.ui import ask_active
        return ask_active()
    except Exception:
        return False


class WindowVoiceMixin:
    """Own voice intercept and facade-facing speech/state seams."""

    _VOICE_ACTIONS = ("vision_open", "vision_close", "home", "reply",
                      "gesture_arm", "gesture_disarm", "calorie_analyze")

    def _on_boot_check(self, d: dict) -> None:
        mark = "✓" if d["ok"] else "✗"
        if d.get("degraded"):
            mark = "~"
        self.orb.set_status_word(f"{d['subsystem']} {mark}")
        self.write_log(f"SYS: [{mark}] {d['subsystem']} — {d.get('detail','')}")
        if not d["ok"]:
            self.notifications.push(d["subsystem"], d.get("detail", ""),
                                    "warning" if d.get("degraded") else "error")

    def _on_notify(self, d: dict) -> None:
        self.write_log(f"SYS: ◈ {d.get('title','')}: {d.get('body','')[:120]}")
        self.notifications.push(d.get("title", ""), d.get("body", ""), "info")

    def _on_bus_log(self, d: dict) -> None:
        msg = d.get("message", "")
        src = d.get("source", "")
        self.activity.add_line(d.get("level", "INFO"), f"[{src}] {msg}")

    def _record_task_result(self, kind: str, text: str) -> None:
        """Tambahkan ringkasan task ke drawer F1; aman dari worker thread."""
        drawer = getattr(self, "task_results", None)
        if drawer is not None:
            drawer.add_entry(kind, text)

    def _append_log(self, text: str) -> None:
        level = "INFO"
        tl = text.lower()
        if tl.startswith("you:"):
            level = "USER"
        elif tl.startswith("jarvis:"):
            level = "AI"
        elif "err" in tl[:6]:
            level = "ERROR"
        self.activity.add_line(level, text)
        if tl.startswith("jarvis:"):
            self._record_task_result("AGENT", text[7:].strip())
        elif tl.startswith("sys:") and ("mengerjakan" in tl or "🔧" in text):
            self._record_task_result("PROSES", text[4:].strip())
        ACTIVITY_LOG.add(text)
        if level == "USER":
            if self._skip_next_intercept:
                self._skip_next_intercept = False
            else:
                self._voice_intercept(text[4:].strip())

    def _voice_intercept(self, spoken: str) -> None:
        """Voice transcript routing. Browser intents (URL, search, browser
        open, tab controls) take the SAME canonical path as typed commands —
        browser sistem untuk aksi ringan — sehingga voice dan keyboard tidak
        divergen. Free-form conversation tetap ke live assistant."""
        if not spoken:
            return
        if self.reply_flow.handle_utterance(spoken):
            return
        # Fase 15 — jawaban konfirmasi lewat suara. Kanal baru, gerbang lama:
        # ucapan tegas menerbitkan event BUS yang sama persis dengan kata yang
        # diketik. ReplyFlow di atas sudah lewat, jadi dua konteks konfirmasi
        # tidak saling mencuri: selama ReplyFlow berstatus CONFIRM, "ya" tetap
        # miliknya.
        if self._handle_spoken_confirmation(spoken):
            return
        route = classify_execution(spoken, {"source": "voice"})
        _logger.info(
            "router.decision",
            source="voice",
            tier=int(route.tier),
            lane=route.lane,
            reason=route.reason,
        )
        if route.tier >= ExecutionTier.AGENT:
            # The root Gemini Live seam owns the actual voice hand-off.  This
            # UI intercept observes the transcript after the fact, so it must
            # only suppress duplicate legacy actions for heavy requests.
            return
        c = self.router.classify(spoken)
        if c.intent is Intent.SYSTEM and c.slots.get("action") in self._VOICE_ACTIONS:
            self.run_system(c.slots, spoken)
        elif c.intent is Intent.OPEN_BROWSER_AGENT:
            self.open_browser_agent(c.slots)
        elif c.intent is Intent.OPEN_URL:
            self.open_url(c.slots.get("url", ""))
        elif c.intent is Intent.SEARCH_WEB:
            self.run_search(c.slots.get("query", spoken))

    def _handle_spoken_confirmation(self, spoken: str) -> bool:
        """Terbitkan confirm/cancel bila ucapan ini menjawab pertanyaan aktif.

        Hanya berlaku SELAMA ada pertanyaan yang menunggu. Di luar jendela itu
        "ya" tetap percakapan biasa — kata setuju tidak boleh melayang lalu
        menyetujui aksi yang belum pernah ditanyakan.
        """
        pending = (self._pending_close_decision is not None
                   or self._pending_voice_proposal_id is not None
                   or _agent_ask_active())
        if not pending:
            return False
        try:
            from jarvis.agent import voice_consent
            decision = voice_consent.decide(spoken)
        except Exception as exc:                             # noqa: BLE001
            _logger.warning("voice.consent_unavailable", error=str(exc)[:100])
            return False
        if decision is None:
            return False
        BUS.publish(decision)
        self.write_log(
            f"SYS: konfirmasi suara — {'disetujui' if decision == 'confirm' else 'dibatalkan'}.")
        return True

    def _speech(self):
        """Antrean bicara tunggal milik window ini (§28).

        Dibuat malas supaya window yang dipakai tes tidak perlu menyalakan
        thread apa pun.
        """
        queue = getattr(self, "_speech_queue", None)
        if queue is None:
            from jarvis.core.speech_queue import SpeechQueue

            queue = SpeechQueue(speaker=self._speak_now)
            self._speech_queue = queue
            worker = threading.Thread(
                target=self._speech_worker, daemon=True, name="jarvis-speech")
            self._speech_worker_thread = worker
            worker.start()
        return queue

    def _speech_worker(self) -> None:
        import time as _time

        while True:
            try:
                if not self._speech_queue.run_once():
                    _time.sleep(0.05)
            except Exception:                                # noqa: BLE001
                _time.sleep(0.2)

    def _speak_now(self, line: str):
        """Kirim SATU kalimat ke lane suara. Dipanggil hanya oleh antrean."""
        submit = getattr(self, "on_speech_command", None)
        if callable(submit):
            return submit(line)
        if self.on_text_command is None:
            return None
        msg = ("Ucapkan kalimat berikut PERSIS seperti tertulis, tanpa "
               "tambahan: «" + line + "»")
        self.on_text_command(msg)
        return None

    def _speak_line(self, line: str, *, kind: str = "info",
                    turn: str = "") -> None:
        """Say one exact sentence via the live voice; log regardless.

        §28 — bentuk lama melahirkan thread baru per kalimat, dan 42 pemanggil
        memakainya. Tidak ada yang menyerialkan mereka, sehingga ACK, progres,
        hasil, dan konfirmasi bisa berbunyi bersamaan. Sekarang semuanya lewat
        satu antrean yang juga MEMBUANG yang sudah basi.
        """
        self.write_log(f"Jarvis: {line}")
        self._speech().say(line, kind=kind, turn=turn)

    def _show_content(self, title: str, text: str) -> None:
        if self.info_panel is None:
            self.write_log(f"ERR: panel info tidak tersedia — {title}")
            return
        lines = [line for line in text.splitlines() if line.strip()]
        self.info_panel.add_card("result", title, lines or [text],
                                 source="Jarvis", ts="")
        self.stage.show_child("info")
        self._schedule_info_recenter()

    def _schedule_info_recenter(self) -> None:
        """Setelah kartu INFO tampil, kembalikan orb ke tengah sesudah jeda —
        kartu tetap terlihat di panel, hanya orb yang un-dock. Hanya berlaku
        untuk stage 'info' agar konten yang dibaca (vision/browser) tak direbut.
        """
        delay = int(config.get("ui.info_panel.orb_recenter_ms", 4000))
        if delay <= 0:
            return
        if self._info_recenter_tmr is None:
            self._info_recenter_tmr = QTimer(self)
            self._info_recenter_tmr.setSingleShot(True)
            self._info_recenter_tmr.timeout.connect(self._recenter_orb_for_info)
        self._info_recenter_tmr.start(delay)

    def _recenter_orb_for_info(self) -> None:
        """Orb pulang ke tengah bila stage masih menampilkan kartu INFO dan
        pipeline sedang tenang (bukan SPEAKING/EXECUTING)."""
        if self.stage.current != "info":
            return
        if self._legacy_state in ("SPEAKING", "EXECUTING"):
            # jangan ganggu layout saat masih bicara/mengerjakan; coba lagi.
            self._schedule_info_recenter()
            return
        self.orb.undock()

    def _apply_state(self, state: str) -> None:
        if state == "SPEAKING" and self._legacy_state != "SPEAKING":
            self._speaking_since = time.monotonic()   # barge-in grace anchor
        self._legacy_state = state
        orb_state = _LEGACY_STATE_MAP.get(state, OrbState.IDLE)
        self.orb.set_state(orb_state)
        self._dot.set_state(orb_state)
        if state == "SPEAKING":
            self.orb.set_presentation(PresentationMode.DOCKED_CONTENT_STAGE
                                      if self.stage.status is ContentStatus.ACTIVE
                                      else PresentationMode.FULL_EMPTY_STAGE)
        if state == "MUTED":
            self.orb.set_status_word("MUTED")
        elif orb_state not in (OrbState.SPEAKING, OrbState.EXECUTING):
            # stay docked while the stage is showing content — the orb must
            # not jump back over the page the user is reading
            if self.stage.current is None:
                self.orb.undock()
            else:
                self.orb.dock(Corner.BOTTOM_RIGHT)

    def toggle_mute(self) -> None:
        self._muted = not self._muted
        self.notifications.set_muted(self._muted)
        if self._muted:
            self._apply_state("MUTED")
            self.write_log("SYS: Microphone muted.")
        else:
            self._apply_state("LISTENING")
            self.write_log("SYS: Microphone active.")

    def _toggle_fullscreen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _do_interrupt(self) -> None:
        """ESC. Interupsi suara adalah do-not-regress dan SELALU menang.

        Hanya bila Jarvis benar-benar tidak sedang bicara DAN ada panel
        terbuka, ESC berarti "kembali". Urutan ini tidak boleh dibalik:
        memotong ucapan adalah alasan utama tombol ini ada.
        """
        speaking = self._legacy_state in ("SPEAKING", "TRANSCRIBING")
        # S-30 — kamera BUKAN panel biasa. Ia perangkat fisik yang dinyalakan
        # user secara eksplisit, dengan LED menyala. Menutupnya sebagai efek
        # samping interupsi adalah mengambil keputusan yang tidak pernah
        # diminta — dan sejak barge-in benar-benar memicu (S-24/S-25) jalur ini
        # hidup: user bicara menimpa Jarvis, lalu saat _do_interrupt berjalan
        # Jarvis kerap SUDAH selesai bicara, sehingga cabang "tutup panel" yang
        # diambil. Menutup kamera tetap bisa lewat perintah eksplisit.
        if (not speaking and self.stage.current
                and self.stage.current != "vision"):
            # ESC adalah close panel, bukan navigasi mundur tersembunyi. Riwayat
            # dibersihkan bersama toggle agar klik/ESC setelah panel switch tidak
            # mendarat pada panel lama secara membingungkan.
            self._close_stage_panels()
            return
        if self.on_interrupt:
            self.on_interrupt()

    def write_log(self, text: str) -> None:
        self._log_sig.emit(text)

    def _check_config(self) -> bool:
        try:
            from jarvis.core import llm
            return bool(llm.api_key())
        except Exception:
            return False

    def _center_sheet(self) -> None:
        if self._api_sheet is None:
            return
        c = self.centralWidget()
        w, h = 480, 240
        self._api_sheet.setGeometry((c.width() - w) // 2,
                                    (c.height() - h) // 2, w, h)

    def _show_api_sheet(self) -> None:
        if self._api_sheet is None:
            self._api_sheet = ApiKeySheet(self.centralWidget())
            self._api_sheet.done.connect(self._on_api_key)
        self._center_sheet()
        self._api_sheet.show()
        self._api_sheet.raise_()

    def _on_api_key(self, key: str) -> None:
        from jarvis.core import llm, secrets_store
        if not secrets_store.set("jarvis/llm/gemini", key):
            self.write_log("ERR: API key gagal disimpan terenkripsi.")
            return
        llm.reset_client()
        self._ready = True
        if self._api_sheet:
            self._api_sheet.hide()
        self.write_log("SYS: API key tersimpan — sistem online.")

    def _on_file(self, path: str) -> None:
        self._current_file = path
        if self.assistant is not None:
            self.assistant.ctx.uploaded_file = path
        self.write_log(f"FILE: {path}")

        import os
        ext = os.path.splitext(path)[1].lower()
        if ext in {'.pdf', '.docx', '.doc', '.txt', '.md', '.csv'}:
            self._handle_document_upload(path)
        elif ext in {'.png', '.jpg', '.jpeg', '.webp'}:
            self._handle_image_upload(path)
        else:
            if self.on_text_command:
                msg = (f"[FILE_UPLOADED] path={path} | Briefly tell the user you "
                       f"can see the file and ask what to do with it.")
                threading.Thread(target=self.on_text_command, args=(msg,),
                                 daemon=True).start()

    def _handle_document_upload(self, path: str) -> None:
        """Upload → Extracting → Ready, with explicit status and a spoken
        outcome.  The upload worker only extracts, caches into the shared
        document coordinator, and reports readiness.  A long-form summary is
        produced only by an explicit explain request (the single long-form
        owner), never as an automatic upload monolog (Fase 38)."""
        self.orb.set_state(OrbState.THINKING)
        import os
        name = os.path.basename(path)

        def _run():
            try:
                self._content_sig.emit(f"Dokumen: {name}",
                                       "⏳ Membaca dan mengekstrak teks…")
                from jarvis.nlp.document import read_document_ex
                text, err = read_document_ex(path)
                if err:
                    self._content_sig.emit(f"Dokumen: {name} — GAGAL", err)
                    self._speak_line(f"Maaf, {err}")
                    return
                self._seed_document_coordinator(path, text)
                self._content_sig.emit(
                    f"Dokumen: {name}",
                    "Dokumen terbaca — siap dijelaskan. Katakan 'jelaskan "
                    "dokumen' untuk mendengar penjelasannya.")
                self._speak_line(
                    f"Dokumen {name} sudah saya baca. Katakan jelaskan "
                    "dokumen untuk mendengar penjelasannya.")
            except Exception as e:
                self.write_log(f"ERR: document upload — {str(e)[:80]}")
                self._content_sig.emit(f"Dokumen: {name} — GAGAL",
                                       "Terjadi kesalahan internal saat "
                                       "memproses dokumen.")
                self._speak_line("Maaf, terjadi kesalahan saat memproses "
                                 "dokumen ini.")
            finally:
                self._restore_orb()
        threading.Thread(target=_run, daemon=True, name="doc-upload").start()

    @staticmethod
    def _coordinator_for_upload():
        """Expose the shared coordinator for the Fase 38 single-owner contract."""
        from jarvis.nlp.document_lifecycle import COORDINATOR
        return COORDINATOR

    def _seed_document_coordinator(self, path: str, text: str) -> None:
        """Register the uploaded document in the shared coordinator so upload,
        explain, and summarize all share ONE generation owner (Fase 38)."""
        try:
            from jarvis.nlp.document_lifecycle import COORDINATOR
            import os
            # open_text() applies safe_fingerprint() internally, so pass the
            # RAW path identity — never a pre-hashed value, or the lifecycle
            # key would diverge from the one lifecycle_for_path() looks up.
            COORDINATOR.open_text(
                path, text, source="voice",
                title=os.path.basename(path))
        except Exception as e:                     # noqa: BLE001
            self.write_log(f"ERR: document coordinator seed — {str(e)[:80]}")

    def _handle_image_upload(self, path: str) -> None:
        self.orb.set_state(OrbState.THINKING)
        import os
        from pathlib import Path
        img_url = Path(path).as_uri()
        html = f'<img src="{img_url}" width="400" />'
        self._content_sig.emit(f"Gambar: {os.path.basename(path)}", html)

        def _run():
            try:
                from jarvis.core import llm
                from google import genai
                from google.genai import types
                client_key = llm.api_key()
                if not client_key:
                    self._speak_line("API key belum dikonfigurasi untuk melihat gambar.")
                    return
                client = genai.Client(api_key=client_key)
                with open(path, "rb") as f:
                    image_bytes = f.read()
                ext = os.path.splitext(path)[1].lower()
                mime = f"image/{ext[1:]}" if ext != '.jpg' else "image/jpeg"
                response = client.models.generate_content(
                    model='gemini-3.5-flash',
                    contents=[
                        types.Part.from_bytes(data=image_bytes, mime_type=mime),
                        "Deskripsikan gambar ini dengan singkat dalam Bahasa Indonesia (maksimal 2 kalimat)."
                    ]
                )
                desc = response.text or "Gambar telah dimuat."
                self._speak_line(desc)
            except Exception as e:
                self.write_log(f"ERR: image upload — {str(e)[:80]}")
            finally:
                self._restore_orb()
        threading.Thread(target=_run, daemon=True, name="img-upload").start()
