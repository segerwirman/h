"""Sinyal untuk inisiatif proaktif (DIAGNOSIS_2 MASALAH 4d).

``ProactiveEngine`` selama ini hanya punya SATU pemicu: diam 900 detik
(``actions/proactive.py:22,29-38``). Hasilnya sapaan acak yang terasa seperti
alarm, bukan perhatian — ia tidak pernah bisa menjawab "kenapa aku bilang ini
sekarang".

Modul ini mengumpulkan sinyal yang **sudah ada di repo** (tidak membangun
subsistem baru) dan mengubahnya jadi alasan yang bisa diucapkan:

    layar        jarvis/core/screen_awareness.py  -> BUS "awareness.context"
    beban sistem psutil (sumber yang sama dengan system_monitor)
    cron         jarvis/agent/cron.py             -> jadwal yang jatuh tempo
    waktu        awal/akhir hari kerja

Sekaligus modul ini yang menegakkan aturan keras. Inisiatif tanpa rem
berubah cepat dari "hadir" jadi "mengganggu":

* maksimal satu interupsi per 10 menit;
* nol interupsi saat ``focus_mode`` aktif;
* tidak pernah menyela saat user bicara/mengetik;
* dua saran berturut diabaikan -> frekuensi turun setengah;
* setiap interupsi WAJIB punya alasan. Tanpa alasan -> diam.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from jarvis.core import config, log
from jarvis.core.bus import BUS

_logger = log.get("core.proactive_signals")

MIN_GAP_S = 600.0          # 1 interupsi / 10 menit
USER_BUSY_WINDOW_S = 20.0  # sejak aktivitas user terakhir
IGNORED_STREAK_LIMIT = 2   # 2 diabaikan -> frekuensi setengah
CPU_SUSTAINED_S = 120.0
CPU_THRESHOLD = 85.0


@dataclass(frozen=True)
class Signal:
    kind: str
    reason: str          # kalimat yang bisa diucapkan apa adanya
    weight: float = 1.0


@dataclass
class _State:
    last_triggered: float = 0.0
    ignored_streak: int = 0
    last_user_activity: float = field(default_factory=time.monotonic)
    speaking: bool = False
    screen_note: str = ""
    screen_at: float = 0.0
    cpu_high_since: float = 0.0
    subscribed: bool = False


_lock = threading.RLock()
_state = _State()


# ── penyerapan sinyal dari BUS ───────────────────────────────────────────

def _on_awareness(data: dict) -> None:
    model = data.get("model")
    title = str(getattr(model, "window_title", "") or
                (model or {}).get("window_title", "")
                if isinstance(model, dict) else "")
    text = str(getattr(model, "summary", "") or "")
    blob = f"{title} {text}".lower()
    markers = ("error", "exception", "traceback", "failed", "build failed",
               "gagal", "fatal")
    if any(m in blob for m in markers):
        with _lock:
            _state.screen_note = (title or "ada error di layar")[:120]
            _state.screen_at = time.monotonic()


def _on_state(data: dict) -> None:
    value = str(data.get("state", "")).upper()
    with _lock:
        _state.speaking = value in ("SPEAKING", "LISTENING", "TRANSCRIBING")
        if value in ("LISTENING", "TRANSCRIBING"):
            _state.last_user_activity = time.monotonic()


def _on_intent(_data: dict) -> None:
    with _lock:
        _state.last_user_activity = time.monotonic()


def subscribe() -> None:
    """Pasang sekali. Aman dipanggil berulang."""
    with _lock:
        if _state.subscribed:
            return
        _state.subscribed = True
    BUS.subscribe("awareness.context", _on_awareness)
    BUS.subscribe("state", _on_state)
    BUS.subscribe("intent", _on_intent)
    _logger.info("proactive.signals_subscribed")


def note_user_activity() -> None:
    with _lock:
        _state.last_user_activity = time.monotonic()


def mark_triggered() -> None:
    with _lock:
        _state.last_triggered = time.monotonic()


def mark_ignored() -> None:
    with _lock:
        _state.ignored_streak += 1


def mark_acknowledged() -> None:
    with _lock:
        _state.ignored_streak = 0


def reset_for_tests() -> None:
    global _state
    with _lock:
        _state = _State()


# ── pengumpul sinyal ─────────────────────────────────────────────────────

def _signal_screen() -> Signal | None:
    with _lock:
        note, at = _state.screen_note, _state.screen_at
    if not note or (time.monotonic() - at) > 300:
        return None
    return Signal("screen", f"ada yang gagal di layar Anda ({note})", 1.4)


def _signal_load() -> Signal | None:
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=None)
    except Exception:                                        # noqa: BLE001
        return None
    now = time.monotonic()
    with _lock:
        if cpu >= CPU_THRESHOLD:
            if _state.cpu_high_since == 0.0:
                _state.cpu_high_since = now
            sustained = now - _state.cpu_high_since
        else:
            _state.cpu_high_since = 0.0
            sustained = 0.0
    if sustained >= CPU_SUSTAINED_S:
        return Signal("load",
                      f"CPU bertahan di {cpu:.0f}% selama beberapa menit", 1.2)
    return None


def _signal_cron() -> Signal | None:
    try:
        from jarvis.agent import cron
        jobs = cron.list_jobs() if hasattr(cron, "list_jobs") else []
    except Exception:                                        # noqa: BLE001
        return None
    now = time.time()
    for job in jobs or []:
        try:
            nxt = float(job.get("next_run") or 0)
            name = str(job.get("name") or job.get("id") or "tugas terjadwal")
        except Exception:                                    # noqa: BLE001
            continue
        if 0 < (nxt - now) <= 900:
            return Signal("cron", f"'{name}' dijadwalkan sebentar lagi", 1.1)
    return None


def _signal_time() -> Signal | None:
    hour = datetime.now().hour
    if 8 <= hour < 10:
        return Signal("time", "awal hari kerja", 0.6)
    if 17 <= hour < 19:
        return Signal("time", "menjelang akhir hari kerja", 0.6)
    return None


def collect() -> list[Signal]:
    out: list[Signal] = []
    for fn in (_signal_screen, _signal_load, _signal_cron, _signal_time):
        try:
            sig = fn()
        except Exception as exc:                             # noqa: BLE001
            _logger.warning("proactive.signal_failed", fn=fn.__name__,
                            error=str(exc)[:100])
            continue
        if sig is not None:
            out.append(sig)
    return sorted(out, key=lambda s: -s.weight)


# ── aturan keras ─────────────────────────────────────────────────────────

def effective_gap() -> float:
    """Jarak minimum antar interupsi, digandakan setelah diabaikan."""
    with _lock:
        streak = _state.ignored_streak
    factor = 2.0 if streak >= IGNORED_STREAK_LIMIT else 1.0
    return MIN_GAP_S * factor


def blocked_reason() -> str | None:
    """Kenapa TIDAK boleh menyela sekarang. ``None`` = boleh."""
    try:
        from jarvis.core.focus_mode import FocusMode
        if not FocusMode.get().should_show_proactive_suggestions():
            return "focus_mode aktif"
    except Exception:                                        # noqa: BLE001
        pass

    now = time.monotonic()
    with _lock:
        if _state.speaking:
            return "user sedang bicara / Jarvis sedang menjawab"
        if (now - _state.last_user_activity) < USER_BUSY_WINDOW_S:
            return "user baru saja beraktivitas"
        if (now - _state.last_triggered) < effective_gap():
            return "belum melewati jarak minimum antar interupsi"
    return None


def decide() -> tuple[bool, str]:
    """``(boleh, alasan)``.

    Alasan selalu terisi — itu kontraknya. Kalau Jarvis tidak bisa menjawab
    "kenapa aku bilang ini sekarang", ia seharusnya diam.
    """
    blocked = blocked_reason()
    if blocked is not None:
        return (False, blocked)
    signals = collect()
    if not signals:
        return (False, "tidak ada sinyal yang layak disebut")
    return (True, signals[0].reason)


__all__ = ["Signal", "collect", "decide", "blocked_reason", "effective_gap",
           "subscribe", "mark_triggered", "mark_ignored", "mark_acknowledged",
           "note_user_activity", "reset_for_tests", "MIN_GAP_S",
           "IGNORED_STREAK_LIMIT"]
