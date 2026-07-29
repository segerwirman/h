"""Jalur masuk agent native Jarvis.

    ACK instan (<1 ms) → kerja di worker thread → callback done/error
    → BUS ``agent.task.done`` / ``agent.task.failed``.

Dedup guard: task identik yang masih berjalan tidak di-spawn dua kali.
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

from jarvis.core import config, log
from jarvis.core.bus import BUS
from jarvis.agent.interaction import detect_language, render_ack
from jarvis.agent.task_contracts import PreparedAgentTask, ToolEvidence, prepare_task

_logger = log.get("agent.dispatch")

_active_lock = threading.Lock()
_active: dict[str, "TaskHandle"] = {}


class _BufferedFinalAdapter:
    """Delegate interaction/progress but hold final text until validation.

    The loop normally calls ``adapter.send`` before returning its RunResult.
    A contracted task must not expose that model-authored success claim until
    the wrapper has verified its tool evidence, so only final text is buffered.
    """

    def __init__(self, delegate):
        self._delegate = delegate
        self.name = getattr(delegate, "name", "unknown")
        self.interactive = bool(getattr(delegate, "interactive", False))
        self.outputs: list[str] = []

    async def send(self, content: str, **kwargs) -> None:
        self.outputs.append(str(content or ""))

    async def progress(self, text: str) -> None:
        await self._delegate.progress(text)

    async def ask(self, question: str,
                  options: list[str] | None = None) -> str | None:
        return await self._delegate.ask(question, options)

    async def send_image(self, path: str, caption: str = "") -> None:
        await self._delegate.send_image(path, caption)


class TaskHandle:
    def __init__(self, task: str, session):
        self.task = task
        self.session = session
        self.started_at = time.monotonic()
        self.bg_task = None                 # jarvis.agent.tasks.Task | None

    def cancel(self) -> None:
        """Batalkan lewat KEDUA jalur. ``Session.cancelled`` dibaca loop lama
        (loop.py:165) dan ``Task.cancel`` dibaca hook §8.3 — membiarkan salah
        satu saja berarti dua sumber kebenaran yang bisa bertentangan."""
        self.session.cancel()
        bg = self.bg_task
        if bg is not None:
            try:
                from jarvis.agent.tasks import REGISTRY
                REGISTRY.cancel(bg.id)
            except Exception:                                # noqa: BLE001
                pass


def _key(task: str) -> str:
    return " ".join(task.lower().split())[:160]


def available() -> bool:
    """Agent native siap? (enabled + provider LANE BERAT siap, §3).

    Dispatch adalah pintu Lane B (T2+); sejak Fase 3 kesiapannya diukur dari
    resolusi ``routing.heavy`` — bukan dari provider aktif lane ringan.
    """
    if not bool(config.get("agent.enabled", True)):
        return False
    try:
        from jarvis.agent import model_routing
        return model_routing.heavy_ready()
    except Exception:                                        # noqa: BLE001
        return False


def dispatch_risk(context=None) -> str:
    """Remote planning is bounded by its context; individual tools stay gated."""
    if (getattr(context, "surface", "") == "remote"
            and "agent" in getattr(context, "toolsets", ())):
        return "medium"
    return "high"


def is_active(task: str) -> bool:
    """Apakah task identik masih berjalan? (dipakai pesan refusal jujur)."""
    with _active_lock:
        return _key(task) in _active


def active_count() -> int:
    with _active_lock:
        return len(_active)


def active_tasks() -> list[str]:
    with _active_lock:
        return [h.task for h in _active.values()]


def cancel_all() -> int:
    with _active_lock:
        handles = list(_active.values())
    for h in handles:
        h.cancel()
    return len(handles)


def cancel_task(task_id: str) -> bool:
    """Batalkan SATU tugas berdasarkan id registry (§8.4c ``task_cancel``).

    Lewat ``TaskHandle`` supaya ``Session.cancelled`` ikut ter-set — loop lama
    (loop.py:165) membacanya, dan hook §8.3 membaca ``Task.cancel``.
    ``False`` bila handle tidak ditemukan; pemanggil boleh jatuh ke
    ``REGISTRY.cancel`` untuk task yang belum/tidak lewat dispatch.
    """
    tid = str(task_id or "").strip()
    if not tid:
        return False
    with _active_lock:
        handles = [h for h in _active.values()
                   if getattr(getattr(h, "bg_task", None), "id", None) == tid]
    for handle in handles:
        handle.cancel()
    return bool(handles)


def _prepared_task(task: str,
                   allowed_tools: list[str] | None) -> tuple[
                       PreparedAgentTask, list[str] | None]:
    """Apply a narrow task contract without broadening a caller allowlist."""

    try:
        prepared = prepare_task(task)
    except Exception as exc:                                # noqa: BLE001
        _logger.warning("agent.contract.prepare_failed", error=str(exc)[:120])
        prepared = PreparedAgentTask(task, task)

    policy_tools = prepared.allowed_tools
    if policy_tools is None:
        return prepared, allowed_tools
    if allowed_tools is None:
        return prepared, list(policy_tools)
    caller_allowed = set(allowed_tools)
    return prepared, [name for name in policy_tools if name in caller_allowed]


def _observe_session(session, evidence: list[ToolEvidence]) -> None:
    """Collect evidence through Session's existing registry callback."""

    original = session.record_tool

    def _record(name: str, args: dict, result: Any,
                elapsed_s: float) -> None:
        original(name, args, result, elapsed_s)
        safe_args = {
            str(key): value for key, value in dict(args or {}).items()
            if not str(key).startswith("_")
        }
        evidence.append(ToolEvidence(
            tool=name,
            args=safe_args,
            result=result,
            ok=bool(getattr(result, "ok", False)),
        ))

    session.record_tool = _record


def _verified_success(prepared: PreparedAgentTask) -> str:
    contract = prepared.contract
    if contract is None:
        return ""
    channel = str(contract.expected_channel or "channel target").strip()
    if detect_language(prepared.original_task) == "en":
        return f"The latest video from {channel} is now playing."
    return f"Video terbaru dari channel {channel} sudah diputar."


def _safe_callback(callback, value: str) -> None:
    if callback is None:
        return
    try:
        callback(value)
    except Exception:                                       # noqa: BLE001
        pass


def _release_browser_session(session_id: str) -> None:
    """Release a browser lease without making browser a dispatch dependency."""

    try:
        from jarvis.agent.tools.browser import release_browser_session
        release_browser_session(session_id)
    except Exception as exc:                                # noqa: BLE001
        _logger.warning(
            "agent.dispatch.browser_release_failed",
            session=str(session_id)[:32],
            error=str(exc)[:120],
        )


def _release_computer_session(session_id: str) -> None:
    """Release the native CUA lease on every terminal task outcome."""

    try:
        from jarvis.agent.tools.computer import release_computer_session
        release_computer_session(session_id)
    except Exception as exc:                                # noqa: BLE001
        _logger.warning(
            "agent.dispatch.computer_release_failed",
            session=str(session_id)[:32],
            error=str(exc)[:120],
        )


def dispatch_task(task: str, on_ack=None, on_done=None, on_error=None,
                  on_progress=None, adapter=None,
                  timeout_s: float | None = None,
                  allowed_tools: list[str] | None = None,
                  context=None, resources=frozenset(),
                  title: str | None = None) -> "object | None":
    """Varian §8.3 yang mengembalikan ``Task`` (atau ``None``) alih-alih bool.

    Dipakai permukaan baru (Task Deck, tool suara ``task_start``) yang butuh
    id tugas untuk menampilkan progres dan membatalkan.

    ``dispatch_async`` di bawah tetap mengembalikan ``bool`` — kontrak itu
    dipegang belasan pemanggil dan ditegaskan tes
    (``tests/test_phase2_dispatch.py:46`` ``assert started is True``,
    ``tests/test_execution_context.py:57`` ``is False``), jadi tanda tangan
    §8.3 diterapkan sebagai fungsi BARU, bukan penggantian.
    """
    return _dispatch(task, on_ack=on_ack, on_done=on_done, on_error=on_error,
                     on_progress=on_progress, adapter=adapter,
                     timeout_s=timeout_s, allowed_tools=allowed_tools,
                     context=context, resources=resources, title=title)


def dispatch_async(task: str, on_ack=None, on_done=None, on_error=None,
                   adapter=None, timeout_s: float | None = None,
                   allowed_tools: list[str] | None = None,
                   context=None, on_progress=None,
                   resources=frozenset()) -> bool:
    """Mulai task agent di background. False bila agent tidak tersedia ATAU
    task sama masih berjalan. Callback dipanggil dari worker thread —
    marshal ke UI thread adalah tanggung jawab caller (sama dengan Hermes)."""
    return _dispatch(task, on_ack=on_ack, on_done=on_done, on_error=on_error,
                     on_progress=on_progress, adapter=adapter,
                     timeout_s=timeout_s, allowed_tools=allowed_tools,
                     context=context, resources=resources) is not None


def _dispatch(task: str, *, on_ack=None, on_done=None, on_error=None,
              on_progress=None, adapter=None,
              timeout_s: float | None = None,
              allowed_tools: list[str] | None = None,
              context=None, resources=frozenset(),
              title: str | None = None):
    if not available():
        _logger.warning("agent.dispatch.unavailable", task=task[:80])
        return None
    if context is not None:
        from jarvis.agent import policy
        decision = policy.decide(context, capability="agent.dispatch",
                                 risk=dispatch_risk(context))
        if not decision.allowed:
            _logger.info("agent.dispatch.policy_denied", reason=decision.reason,
                         trace=context.trace_id[:12])
            return None

    from jarvis.agent.adapters.base import NullAdapter
    from jarvis.agent.session import Session
    from jarvis.agent import loop as agent_loop
    from jarvis.agent.tasks import REGISTRY

    prepared, effective_tools = _prepared_task(task, allowed_tools)

    k = _key(task)
    with _active_lock:
        if k in _active:
            _logger.info("agent.dispatch.duplicate", task=task[:80])
            return None
        adapter = adapter or NullAdapter()
        session = Session(task=task, adapter_name=adapter.name)
        session.execution_context = context
        _active[k] = TaskHandle(task, session)

    # §8.2 — task masuk registry sebagai QUEUED; worker yang mempromosikannya
    # ke RUNNING setelah slot konkurensi + resource eksklusif didapat.
    bg_task = REGISTRY.submit(task, title=title, resources=resources)
    if bg_task is None:                                      # antrean penuh
        with _active_lock:
            _active.pop(k, None)
        _logger.warning("agent.dispatch.queue_full", task=task[:80])
        return None
    REGISTRY.update(bg_task.id, session_id=session.id)
    with _active_lock:
        handle = _active.get(k)
        if handle is not None:
            handle.bg_task = bg_task

    evidence: list[ToolEvidence] = []
    run_adapter = adapter
    if prepared.contracted:
        _observe_session(session, evidence)
        run_adapter = _BufferedFinalAdapter(adapter)

    try:
        # DIAGNOSIS_2 MASALAH 4b — konfirmasi yang menyebut tugasnya.
        # compose_ack tidak pernah melempar dan selalu jatuh ke render_ack
        # bila composer mati/lambat, jadi kontrak ACK-instan tetap terjaga.
        from jarvis.agent.ack_composer import compose_ack
        acknowledgement = compose_ack(task)
    except Exception:  # noqa: BLE001 - acknowledgement must never block work
        acknowledgement = str(config.get("agent.ack_phrase", "Baik, saya kerjakan."))
    _safe_callback(on_ack, acknowledgement)
    BUS.publish("agent.task.started", task=task, session=session.id)

    hard_timeout = timeout_s or float(config.get("agent.task_timeout_s", 900))

    def _worker():
        t0 = time.monotonic()
        # Menunggu slot + resource eksklusif DI SINI, bukan di pemanggil:
        # dispatch harus tetap kembali seketika (§8.3 "kembali SEKARANG").
        if not REGISTRY.acquire_slot(bg_task):
            _logger.info("agent.dispatch.cancelled_while_queued",
                         task=task[:80], id=bg_task.id)
            _safe_callback(on_error, "Tugas dibatalkan sebelum mulai.")
            with _active_lock:
                _active.pop(k, None)
            return
        REGISTRY.mark_running(bg_task.id)
        try:
            result = asyncio.run(asyncio.wait_for(
                agent_loop.run(prepared.execution_prompt,
                               adapter=run_adapter, session=session,
                               allowed_tools=effective_tools,
                               max_iterations=int(config.get(
                                   "agent.interactive_max_iterations", 12)),
                               model_profile="heavy", context=context,
                               bg_task=bg_task),
                timeout=hard_timeout))
            elapsed = round(time.monotonic() - t0, 1)
            if result.ok:
                text = result.text
                if prepared.contract is not None:
                    validation = prepared.contract.validate(evidence)
                    if not validation.ok:
                        err = ("Verifikasi alur YouTube gagal: "
                               + validation.reason)
                        session.finish(err, ok=False)
                        _logger.warning(
                            "agent.dispatch.contract_failed",
                            task=task[:80], error=validation.reason[:300])
                        BUS.publish("agent.task.failed", task=task, error=err,
                                    elapsed_s=elapsed)
                        REGISTRY.finish(bg_task.id, error=err)
                        _safe_callback(on_error, err)
                        return
                    text = _verified_success(prepared)
                    session.finish(text, ok=True)
                _logger.info("agent.dispatch.done", elapsed_s=elapsed,
                             session=result.session_id)
                BUS.publish("agent.task.done", task=task, text=text,
                            elapsed_s=elapsed)
                REGISTRY.finish(bg_task.id, result=text)
                _safe_callback(on_done, text)
            else:
                err = result.text or "agent gagal"
                BUS.publish("agent.task.failed", task=task, error=err,
                            elapsed_s=elapsed)
                REGISTRY.finish(bg_task.id, error=err)
                _safe_callback(on_error, err)
        except asyncio.TimeoutError:
            session.cancel()
            err = f"timeout {hard_timeout:.0f}s"
            _logger.error("agent.dispatch.timeout", task=task[:80])
            BUS.publish("agent.task.failed", task=task, error=err)
            REGISTRY.finish(bg_task.id, error=err)
            _safe_callback(on_error, err)
        except Exception as e:                               # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:200]}"
            _logger.error("agent.dispatch.crashed", error=err)
            BUS.publish("agent.task.failed", task=task, error=err)
            REGISTRY.finish(bg_task.id, error=err)
            _safe_callback(on_error, err)
        finally:
            # Selalu lepas slot + resource, apa pun yang terjadi — kalau tidak,
            # satu crash membekukan seluruh antrean.
            REGISTRY.release_slot(bg_task)
            REGISTRY.finish(bg_task.id, error="selesai tanpa status")
            _release_browser_session(session.id)
            _release_computer_session(session.id)
            with _active_lock:
                _active.pop(k, None)

    threading.Thread(target=_worker, daemon=True,
                     name=f"agent-{bg_task.id}").start()
    return bg_task


def run_sync(task: str, adapter=None, timeout_s: float | None = None,
             allowed_tools: list[str] | None = None) -> str:
    """Jalur blocking untuk cron/tes. Return teks hasil ('' saat gagal)."""
    if not available():
        return ""
    from jarvis.agent.adapters.base import NullAdapter
    from jarvis.agent.session import Session
    from jarvis.agent import loop as agent_loop

    prepared, effective_tools = _prepared_task(task, allowed_tools)
    adapter = adapter or NullAdapter()
    session = Session(task=task, adapter_name=adapter.name)
    evidence: list[ToolEvidence] = []
    run_adapter = adapter
    if prepared.contracted:
        _observe_session(session, evidence)
        run_adapter = _BufferedFinalAdapter(adapter)
    try:
        result = asyncio.run(asyncio.wait_for(
            agent_loop.run(prepared.execution_prompt, adapter=run_adapter,
                           session=session, allowed_tools=effective_tools,
                           model_profile="heavy"),
            timeout=timeout_s or float(
                config.get("agent.task_timeout_s", 900))))
        if not result.ok:
            return ""
        if prepared.contract is not None:
            validation = prepared.contract.validate(evidence)
            if not validation.ok:
                _logger.warning("agent.run_sync.contract_failed",
                                error=validation.reason[:300])
                return ""
            return _verified_success(prepared)
        return result.text
    except Exception as e:                                   # noqa: BLE001
        _logger.error("agent.run_sync_failed",
                      error=f"{type(e).__name__}: {str(e)[:150]}")
        return ""
    finally:
        _release_browser_session(session.id)
        _release_computer_session(session.id)
