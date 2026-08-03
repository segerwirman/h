"""J.A.R.V.I.S — Mark XLIX entry point.

    python -m jarvis.main               full assistant (voice + UI + vision)
    python -m jarvis.main --no-voice    UI/NLP only (no Gemini Live session)
    python -m jarvis.main --orb-test    orb keyboard harness in isolation

The legacy Gemini Live pipeline (``main.JarvisLive`` — mic, TTS voice Charon,
tool calling) is reused unchanged; the new ``jarvis.ui.window.JarvisUI``
facade satisfies its exact UI contract. Every subsystem degrades gracefully:
a missing dependency logs and disables itself, nothing hard-crashes.
"""
from __future__ import annotations

import multiprocessing
import sys
import threading

# MK50 §7 — panel browser dibuang dari ContentStage: QtWebEngine tidak lagi
# dimuat saat boot (efisiensi; dulu import ini load-bearing untuk panel).

from jarvis.core import config, log
from jarvis.runtime.supervisor import RuntimeSupervisor


def _start_voice_pipeline(ui, *, stop_requested: threading.Event | None = None):
    """Run the legacy JarvisLive (Gemini Live audio) against the new UI."""
    logger = log.get("voice")
    stop_requested = stop_requested or threading.Event()
    live_ref = {"instance": None}

    def request_stop() -> None:
        stop_requested.set()
        instance = live_ref["instance"]
        if instance is not None:
            instance.request_stop()

    def runner():
        try:
            import asyncio
            sys.path.insert(0, str(config.base_dir()))
            import main as legacy                # legacy pipeline, unchanged
            from jarvis.core import llm
            from jarvis.integrations import (google_voice, voice_clarify,
                                             voice_l1, voice_notices, voice_persona,
                                             voice_safety, voice_tasks,
                                             voice_text_only_observer,
                                             voice_live_transport,
                                             voice_native_tools,
                                             voice_proposal_install,
                                             whatsapp_voice)
            # Adapter credential di luar file FROZEN: suara tetap identik,
            # hanya sumber API key yang berpindah dari plaintext ke store.
            legacy._get_api_key = lambda: llm.api_key() or ""
            legacy.LIVE_MODEL = str(
                config.get("llm.live_model", legacy.LIVE_MODEL)
                or legacy.LIVE_MODEL
            )
            google_voice.install(legacy)
            # Perbaikan 'kosakata terpotong' saat suara: drain-aware playback
            # dipasang via monkeypatch (file main.py FROZEN tidak diubah).
            try:
                from jarvis.integrations import voice_playback_fix
                voice_playback_fix.install(legacy)
            except Exception as _e:                          # noqa: BLE001
                logger.warning("voice.playback_fix_failed", error=str(_e)[:120])
            # AUDIT §8.4 — tool tugas latar + antrean batas-giliran + aturan
            # multi-tasking, semuanya lewat seam yang sama. main.py dan
            # core/prompt.txt tetap tidak tersentuh.
            voice_tasks.install(legacy)
            voice_l1.install(legacy)
            # 18A proposal hook is config-gated and fail-open; it never executes.
            voice_proposal_install.install(legacy)
            voice_notices.install(legacy)
            voice_text_only_observer.install(legacy)
            voice_live_transport.install(legacy)
            whatsapp_voice.install(legacy)
            voice_native_tools.install(legacy)
            # DIAGNOSIS_2 MASALAH 2 — beri lane suara cara untuk bertanya.
            voice_clarify.install(legacy)
            # DIAGNOSIS_2 MASALAH 3 — shutdown berkonfirmasi + close_app
            # bernama. Dipasang TERAKHIR supaya deklarasi shutdown_jarvis
            # bawaan benar-benar tergantikan.
            voice_safety.install(legacy)
            # DIAGNOSIS_2 MASALAH 4c — gaya bicara, nada adaptif, inisiatif.
            voice_persona.install(legacy)
            JarvisLive = legacy.JarvisLive
            ui.wait_for_api_key()
            jarvis_live = JarvisLive(ui)
            live_ref["instance"] = jarvis_live
            if stop_requested.is_set():
                jarvis_live.request_stop()
            asyncio.run(jarvis_live.run())
        except Exception as e:
            logger.error("voice.pipeline_failed", error=str(e)[:200])
            ui.write_log(f"ERR: voice pipeline offline — {str(e)[:100]}")

    thread = threading.Thread(target=runner, daemon=False, name="jarvis-live")
    thread.request_stop = request_stop
    thread.start()
    return thread


def run(no_voice: bool = False, *, ui_factory=None) -> int:
    log.setup()
    logger = log.get("main")
    logger.info("mark_xlix.starting")
    supervisor = RuntimeSupervisor(
        on_error=lambda name, exc: logger.warning(
            "runtime.shutdown_failed", service=name, error=str(exc)[:120]))

    # Indeks aplikasi terpasang dibangun di latar (~0,03 dtk untuk ~500 entri)
    # supaya router tahu apa yang benar-benar ada, bukan menebak lewat
    # pencarian Start Menu buta. Boot tidak menunggu ini.
    try:
        from jarvis.core import app_registry
        app_registry.refresh_async()
    except Exception as exc:                                 # noqa: BLE001
        logger.warning("app_registry.boot_scan_failed", error=str(exc)[:120])

    from jarvis.core import secret_migration, secrets_store
    secrets_store.initialize()
    migration = secret_migration.migrate_legacy()
    if migration.pending:
        logger.warning("secrets.migration_pending",
                       count=len(migration.pending),
                       detail="credential lama dipertahankan karena store gagal")

    # startup config validation (Fase 6) — lists missing config, no secrets
    for issue in config.validate():
        logger.warning("config.issue", detail=issue)

    # services (each optional)
    from jarvis.nlp.assistant import SmartAssistant
    assistant = SmartAssistant()
    assistant.register_defaults()

    vision = None
    try:
        from jarvis.vision.process import VisionSystem
        vision = VisionSystem()
    except Exception as e:
        logger.warning("vision.unavailable", error=str(e)[:150])

    social = assistant.module("SocialMediaMonitoring")

    from jarvis.ui.window import JarvisUI
    build_ui = ui_factory or JarvisUI
    ui = build_ui(services={"assistant": assistant, "vision": vision})
    try:
        from jarvis.integrations import desktop_safe_lifecycle
        desktop_safe_lifecycle.install(ui._win.__class__)
    except Exception as exc:                                 # noqa: BLE001
        logger.warning("desktop_safe.ui_teardown_unavailable", error=str(exc)[:120])

    # Wake Trigger (Module 10) — idempotent: an active/speaking session is
    # never re-woken, and the acknowledgment goes through MainWindow._speak_line.
    try:
        from jarvis.core.wake import WakeTrigger

        def _session_busy() -> bool:
            # LISTENING/SPEAKING/THINKING → session already active; a double
            # clap must not start a second one (nor echo-trigger on TTS).
            return ui._win._legacy_state in ("LISTENING", "SPEAKING",
                                             "THINKING", "EXECUTING")

        wake = WakeTrigger(session_active_fn=None if no_voice else _session_busy)
        wake.start()

        def on_wake_triggered(data):
            logger.info("wake.triggered", detail="Double clap detected")
            ui.write_log("SYS: Wake trigger (tepuk tangan 2x) terdeteksi.")
            if not no_voice and hasattr(ui._win, '_speak_line'):
                ui._win._speak_line("Ya, sir. Saya mendengarkan.")

        from jarvis.core.bus import BUS
        BUS.subscribe("wake.triggered", on_wake_triggered, ui=True)
    except Exception as e:
        logger.warning("wake.unavailable", error=str(e)[:150])
        wake = None

    # Relay.app integration (Fase 5) — read-only, webhook-fed, optional
    relay = None
    try:
        from jarvis.integrations.relay.service import RelayService
        relay = RelayService.get()
        relay.start()
        if relay.enabled:
            ui.write_log("SYS: Relay.app aktif — webhook "
                         + ("berjalan." if relay.webhook_running
                            else "GAGAL start (cek RELAY_WEBHOOK_SECRET)."))
    except Exception as e:
        logger.warning("relay.unavailable", error=str(e)[:150])

    # MK50 — agent native: Telegram adapter + cron scheduler (opsional;
    # tanpa token/whitelist → nonaktif senyap, Jarvis tetap jalan)
    telegram_svc = None
    cron_sched = None
    try:
        from jarvis.integrations import telegram_control
        telegram_control.migrate_legacy()
        if telegram_control.enabled():
            from jarvis.gateway.runtime import telegram_runtime
            if telegram_control.start_runtime():
                telegram_svc = telegram_runtime()
                ui.write_log("SYS: Telegram agent aktif (paired gateway).")
            else:
                status = telegram_control.status()
                logger.warning(
                    "agent.telegram_start_blocked",
                    blocked_by=str(status.get("blocked_by", "unknown")),
                    state=str(status.get("state", "unknown")),
                )
                ui.write_log(
                    "SYS: Telegram dikonfigurasi tetapi belum berjalan — "
                    f"{status.get('state', 'periksa Settings')}."
                )
        else:
            logger.info("agent.telegram_disabled")
    except Exception as e:
        logger.warning("agent.telegram_unavailable", error=str(e)[:150])
    try:
        from jarvis.agent.cron import CronScheduler
        cron_sched = CronScheduler.get()
        cron_sched.start()
    except Exception as e:
        logger.warning("agent.cron_unavailable", error=str(e)[:150])

    # Phase 17H — separate monitor-only lifecycle; never reuses agent cron.
    monitor_worker = None
    try:
        from jarvis.monitoring import runtime as monitor_runtime
        monitor_worker = monitor_runtime.start()
        if monitor_worker.launch():
            supervisor.add_stop("monitor_worker", monitor_worker.stop)
            supervisor.add_thread("monitor_worker", monitor_worker.thread)
    except Exception as exc:
        logger.warning("monitor.worker_unavailable", error=type(exc).__name__)

    # ── cinematic boot: visual-only readiness checks, never a briefing ──
    from jarvis.core.boot import BootSequence
    from jarvis.ui.orb import OrbState

    ui._win.orb.start_cinematic_boot()
    ui._win.orb.set_status_word("BOOTING")

    def on_boot_done(_ready: str, results) -> None:
        ui.write_log("SYS: CORE ONLINE — command input ready.")
        # Fase 17D: opt-in, daemon-only local briefing after readiness.
        # No fetch/scheduler/Telegram authority enters the boot callback.
        try:
            from jarvis.integrations import boot_briefing
            boot_briefing.start_if_enabled(
                lambda text: (
                    ui._win._record_task_result("HASIL", text),
                    ui._win._speak_line(text),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("boot.briefing_unavailable", error=type(exc).__name__)
        if no_voice:
            ui.set_state("IDLE")
        else:
            ui.set_state("IDLE")
        if social is not None:
            social.start()

    BootSequence(on_boot_done).start()

    if not no_voice:
        voice_thread = _start_voice_pipeline(ui)
        supervisor.add_stop("voice", voice_thread.request_stop)
        supervisor.add_thread("voice", voice_thread)
    else:
        ui.write_log("SYS: mode --no-voice — pipeline suara dilewati.")

    if vision is not None:
        supervisor.add_stop("vision", vision.stop)
    if social is not None:
        supervisor.add_stop("social", social.stop)
    if wake is not None:
        supervisor.add_stop("wake", wake.stop)
    if relay is not None:
        supervisor.add_stop("relay", relay.stop)
    if telegram_svc is not None:
        supervisor.add_stop("telegram", telegram_svc.stop)
    if cron_sched is not None:
        supervisor.add_stop("cron", cron_sched.stop)
    try:
        from jarvis.core import screen_awareness
        supervisor.add_stop("screen_awareness", screen_awareness.get().stop)
    except Exception as e:
        logger.warning("awareness.unavailable", error=str(e)[:120])

    try:
        ui.root.mainloop()
    finally:
        supervisor.shutdown()
    return 0


def main() -> int:
    if "--orb-test" in sys.argv:
        import runpy
        runpy.run_module("jarvis.ui.orb", run_name="__main__")
        return 0
    return run(no_voice="--no-voice" in sys.argv)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
