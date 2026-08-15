"""Pemasangan tiga lapis Task Deck ke MainWindow (AUDIT_REPORT §8.5).

Semua lewat pola yang SUDAH ADA di repo — tidak ada mekanisme baru:

    stage.register("tasks", TaskDeckPanel())
    tombol ActionPanel  → stage.show("tasks")
    BUS.subscribe(..., ui=True) → di-marshal ke thread Qt oleh drain_ui

Glyph ikon didaftarkan ke ``actionpanel._ICONS`` **saat modul ini diimpor**,
sebelum ``ActionPanel`` dikonstruksi. Itu disengaja: ``jarvis/ui/actionpanel.py``
termasuk zona FROZEN, dan ``ActionPanel.__init__`` sudah punya penjaga
``if name in sig`` (actionpanel.py:172) sehingga nama tanpa sinyal bawaan
tidak menjatuhkan panel — tombolnya tetap dibuat dan disimpan di
``_buttons``, tinggal disambungkan dari sini.
"""
from __future__ import annotations

from jarvis.core import config, log
from jarvis.core.bus import BUS
from jarvis.ui import actionpanel as _actionpanel

_logger = log.get("ui.task_wiring")

ICON_NAME = "tasks"

# Glyph sengaja sekelas dengan ikon lain (◉ ⇪ ♫ ⌂ …): satu karakter, digambar
# GlyphButton yang sama, ukuran & stroke dari config. Tidak ada library ikon
# baru untuk satu ikon.
_actionpanel._ICONS.setdefault(
    ICON_NAME, ("▤", "Task Deck — tugas latar"))


def _aggregate_progress(views) -> tuple[float | None, int]:
    active = [v for v in views if v.active]
    if not active:
        return None, 0
    return sum(v.progress for v in active) / len(active), len(active)


def hydrate_recovery_views(win) -> list:
    """Reconcile stale prior-incarnation tasks into non-active deck records.

    Visual/log-first (Fase 38 item 8): nothing is queued, nothing runs.  The
    returned recovery views ride the same snapshot + BUS wiring as live tasks,
    so there is no second recovery UI.
    """
    try:
        from jarvis.agent.tasks import REGISTRY
        from jarvis.agent.task_ledger import TaskLedger
        ledger = TaskLedger()
        views = REGISTRY.hydrate_recovery(ledger)
        if views:
            _logger.info("task_wiring.recovery_hydrated", count=len(views))
            # snapshot() already folds recovery views in; repaint the deck now
            # so a recovery record is visible before the first BUS event.
            deck = getattr(win, "task_deck", None)
            if deck is not None:
                deck.set_tasks(REGISTRY.snapshot())
        return views
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("task_wiring.recovery_unavailable",
                        error=str(exc)[:120])
        return []


def install(win) -> bool:
    """Pasang strip + deck + arc halo. ``False`` bila fitur dimatikan config."""
    if not bool(config.get("ui.task_deck.enabled", True)):
        return False
    try:
        from jarvis.agent.tasks import REGISTRY
        from jarvis.agent.task_ledger import TaskLedger
        from jarvis.ui.task_deck import TaskDeckPanel
        from jarvis.ui.task_strip import TaskStrip
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("task_deck.unavailable", error=str(exc)[:120])
        return False

    # Attach the durable lifecycle ledger to the GLOBAL registry exactly once.
    # Registry tests build fresh TaskRegistry instances without a ledger, so
    # they never write the real agent.sqlite; only the live boot path does.
    if getattr(REGISTRY, "_ledger", None) is None:
        try:
            ledger = TaskLedger()
            REGISTRY._ledger = ledger
            _logger.info("task_wiring.ledger_attached", path=str(ledger.path))
        except Exception as exc:                             # noqa: BLE001
            _logger.warning("task_wiring.ledger_attach_failed",
                            error=str(exc)[:120])

    central = win.centralWidget()

    # ── lapis 2: panel penuh di ContentStage ─────────────────────────────
    deck = TaskDeckPanel(parent=central)
    win.task_deck = deck
    win.stage.register("tasks", deck)

    history = _ensure_history(win)

    def _open_deck(task_id: str | None = None) -> None:
        # Klik icon tasks yang sama = tutup, termasuk selama LOADING. Gunakan
        # close helper Window agar history/indikator ikut dibersihkan.
        if win.stage.current == "tasks" or win.stage.is_loading("tasks"):
            closer = getattr(win, "_close_stage_panels", None)
            if callable(closer):
                closer()
            else:
                win.stage.hide_all()
            return
        # LOADING dulu, baru ACTIVE setelah ekor JSONL terbaca — kontrak
        # ContentStage dipakai apa adanya, bukan diakali.
        if history is not None:
            history.record("tasks")
        win.stage.begin_loading("tasks")
        deck.set_tasks(REGISTRY.snapshot())
        if task_id:
            deck.select(task_id)
        deck.refresh_log_async()

    def _on_loading(active: bool) -> None:
        if active:
            return
        deck.set_tasks(REGISTRY.snapshot())
        win.stage.activate("tasks")

    deck.loading_changed.connect(_on_loading)
    deck.cancel_requested.connect(lambda tid: _cancel(tid))
    deck.back_requested.connect(lambda: _go_back(win))

    # ── lapis 1: mini strip di atas ActionPanel ──────────────────────────
    strip = TaskStrip(central)
    win.task_strip = strip
    strip.chip_clicked.connect(_open_deck)
    strip.cancel_requested.connect(lambda tid: _cancel(tid))
    strip.raise_()

    def _cancel(task_id: str) -> None:
        try:
            from jarvis.agent import dispatch
            if not dispatch.cancel_task(task_id):
                REGISTRY.cancel(task_id)
        except Exception as exc:                             # noqa: BLE001
            _logger.warning("task_cancel_failed", error=str(exc)[:120])

    # ── tombol ActionPanel ───────────────────────────────────────────────
    button = getattr(win.action_panel, "_buttons", {}).get(ICON_NAME)
    if button is not None:
        button.clicked.connect(lambda: _open_deck())
    else:
        _logger.info("task_deck.icon_absent",
                     detail="tambahkan 'tasks' ke ui.action_panel.icons")

    # ── lapis 3: arc progres di halo orb (BUKAN state EXECUTING) ─────────
    def _refresh(_data: dict | None = None) -> None:
        views = REGISTRY.snapshot()
        strip.set_tasks(views)
        _reposition(win)
        fraction, count = _aggregate_progress(views)
        setter = getattr(win.orb, "set_task_progress", None)
        if callable(setter):
            setter(fraction, count)
        if win.stage.current == "tasks":
            deck.set_tasks(views)

    for topic in ("task.submitted", "task.updated", "task.finished"):
        BUS.subscribe(topic, _refresh, ui=True)

    win._task_refresh = _refresh
    # Reconcile stale prior-incarnation records BEFORE the first refresh so a
    # recovery record is visible immediately and never mistaken for a live
    # worker.  The refresh below then re-renders the same combined snapshot.
    hydrate_recovery_views(win)
    _refresh()
    return True


def _ensure_history(win):
    """Riwayat panel — dipakai tombol kembali dan ESC."""
    existing = getattr(win, "stage_history", None)
    if existing is not None:
        return existing
    try:
        from jarvis.ui.stage_history import StageHistory
        history = StageHistory(win.stage)
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("stage_history.unavailable", error=str(exc)[:120])
        return None
    win.stage_history = history
    return history


def _go_back(win) -> None:
    history = getattr(win, "stage_history", None)
    if history is None:
        win.stage.hide_all()
        return
    history.back()


def _reposition(win) -> None:
    """Tepat di atas ActionPanel — tidak menutupi ContentStage maupun panel."""
    strip = getattr(win, "task_strip", None)
    if strip is None or not strip.isVisible():
        return
    central = win.centralWidget()
    if central is None:
        return
    above = int(config.get("action_panel.above_input_px", 60))
    panel_h = int(getattr(win.action_panel, "panel_h", 56))
    width = max(0, central.width() - 36)
    y = central.height() - above - panel_h - strip.height() - 4
    strip.setGeometry(18, max(0, y), width, strip.height())
    strip.raise_()


def reposition(win) -> None:
    _reposition(win)


__all__ = ["install", "reposition", "ICON_NAME"]
