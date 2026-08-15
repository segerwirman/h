"""Jalur masuk agent native Jarvis.

    ACK instan (<1 ms) → kerja di worker thread → callback done/error
    → BUS ``agent.task.done`` / ``agent.task.failed``.

Dedup guard: task identik yang masih berjalan tidak di-spawn dua kali.
"""
from __future__ import annotations

import asyncio
import contextvars
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from jarvis.core import config, latency, log
from jarvis.core.bus import BUS
from jarvis.agent.interaction import detect_language, render_ack
from jarvis.agent.task_contracts import PreparedAgentTask, ToolEvidence, prepare_task

from jarvis.core import quiet
_logger = log.get("agent.dispatch")

#: Hasil yang lebih panjang berarti modelnya sedang MERANGKAI
#: jawaban, bukan sekadar bertindak — dan merangkai tidak bisa
#: diulang dari cache.
MAX_SPOKEN_CHARS = 200

_active_lock = threading.Lock()
_active: dict[str, "TaskHandle"] = {}


@dataclass(frozen=True)
class TaskMetadata:
    """Safe identity available after registry binding and before ACK."""

    id: str
    session_id: str
    title: str


@dataclass(frozen=True)
class DispatchSourceScope:
    """Context-local ingress label installed by editable composition seams."""

    source: str
    completion_owner: str = "auto"


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
            except Exception as exc:                                # noqa: BLE001
                quiet.swallowed("agent.dispatch.cancel_failed", exc)


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
    """Collect evidence through Session's dedicated evidence callback.

    Deliberately NOT ``record_tool``: that channel feeds the session transcript
    and telemetry, so registry hands it a redacted result. Riding on it meant
    every contract validator saw ``content=None`` and no contract could ever
    pass in production, however correct the work was (S-12).
    """

    original = session.record_evidence

    def _record(name: str, args: dict, result: Any) -> None:
        original(name, args, result)
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

    session.record_evidence = _record


def _verified_success(prepared: PreparedAgentTask,
                      evidence: list[ToolEvidence]) -> str:
    """Kalimat sukses milik kontraknya sendiri, bukan milik dispatch.

    Bentuk lama menuliskan kalimat YouTube di sini, jadi kontrak kedua apa pun
    akan mengumumkan video diputar setelah menelepon seseorang.
    """
    contract = prepared.contract
    if contract is None:
        return ""
    return contract.success_text(evidence)


def _spoken_result(result) -> str:
    """Kalimat pendek dari hasil RUN INI. Kosong bila modelnya masih diperlukan."""
    display = str(getattr(result, "display", "") or "").strip()
    if display:
        return display[:MAX_SPOKEN_CHARS]
    content = getattr(result, "content", None)
    if isinstance(content, str):
        text = content.strip()
        if text and len(text) <= MAX_SPOKEN_CHARS:
            return text
    return ""


def _collect_plan(session, steps: list[dict]) -> None:
    """Kumpulkan langkah yang BERHASIL dengan argumen aslinya (§25).

    Hanya langkah ``ok`` yang dicatat: rencananya adalah apa yang berhasil,
    bukan catatan percobaan model yang gagal di tengah jalan.

    Sesi tanpa kanal ini cukup tidak belajar apa-apa. Menuntutnya ada berarti
    satu fitur kenyamanan menjatuhkan tugas yang seharusnya berjalan.
    """
    original = getattr(session, "record_plan", None)
    if not callable(original):
        return

    def _record(name: str, args: dict, res) -> None:
        original(name, args, res)
        if getattr(res, "ok", False):
            steps.append({"tool": name, "args": dict(args or {}),
                          "display": _spoken_result(res)})

    session.record_plan = _record


async def _replay_plan(task: str, *, adapter, session, context, allowed):
    """Jalankan rencana yang sudah terbukti. ``None`` = tetap pakai model.

    Lewat ``registry.execute`` dengan sengaja: konfirmasi, policy, dan audit
    tetap berlaku. Tujuh fase dihabiskan membuat klaim Jarvis jujur, dan
    kecepatan tidak dibeli dengan melewati satu pun dari itu.
    """
    from jarvis.agent import command_plan, registry
    from jarvis.agent.loop import RunResult

    steps = command_plan.recall(task)
    if not steps:
        return None
    names = [step["tool"] for step in steps]
    if allowed is not None and any(name not in allowed for name in names):
        return None
    if any(registry.get(name) is None for name in names):
        _logger.info("agent.replay.tool_missing", task=task[:80], tools=names)
        command_plan.forget(task)
        return None

    spoken = ""
    for index, step in enumerate(steps):
        result = await registry.execute(step["tool"], dict(step["args"]),
                                        adapter=adapter, session=session,
                                        context=context)
        if not getattr(result, "ok", False):
            error = str(getattr(result, "error", "") or "gagal")
            _logger.info("agent.replay.step_failed", tool=step["tool"],
                         index=index, error=error[:160])
            command_plan.forget(task)
            if index == 0:
                # Belum ada yang terjadi — aman menyerahkannya ke model.
                return None
            # Langkah sebelumnya SUDAH berjalan. Mengulang lewat model berarti
            # mengerjakannya dua kali; katakan apa adanya.
            return RunResult(
                ok=False,
                text=(f"Berhenti di langkah {index + 1} ({step['tool']}): "
                      f"{error}. Langkah sebelumnya sudah terlanjur berjalan, "
                      f"jadi tidak saya ulang."),
                session_id=session.id)
        spoken = _spoken_result(result) or spoken

    if not spoken:
        command_plan.forget(task)
        return None
    latency.mark(session.id, "replay")
    _logger.info("agent.replay.done", task=task[:80], tools=names)
    return RunResult(ok=True, text=spoken, session_id=session.id)


def _learn_plan(task: str, steps: list[dict], replayed: bool) -> None:
    """Simpan rencananya — atau segarkan yang sudah ada bila ini replay."""
    try:
        from jarvis.agent import command_plan

        if replayed:
            command_plan.touch(task)
            return
        if steps:
            command_plan.remember(task, steps)
    except Exception as exc:                                # noqa: BLE001
        _logger.warning("agent.dispatch.plan_learn_failed", error=str(exc)[:120])


def _learn_command(task: str, session) -> None:
    """Catat perintah + tool yang BENAR-BENAR berhasil dijalankan (§26).

    Sumbernya ``session.tool_calls``, bukan daftar bukti kontrak: bukti hanya
    dikumpulkan untuk tugas BERKONTRAK (YouTube, panggilan), sehingga memakai
    itu berarti Jarvis hampir tidak pernah belajar apa pun. ``tool_calls``
    selalu terisi dan sudah teredaksi — hanya nama dan status, tanpa isi hasil.
    """
    try:
        from jarvis.agent import command_index

        names: list[str] = []
        for item in getattr(session, "tool_calls", []) or []:
            name = str(item.get("tool", "") or "")
            if name and item.get("ok") and name not in names:
                names.append(name)
        if names:
            command_index.remember(task, names)
    except Exception as exc:                                # noqa: BLE001
        _logger.warning("agent.dispatch.learn_failed", error=str(exc)[:120])


def _safe_callback(
    callback,
    value: str,
    *,
    task_id: str = "",
    kind: str = "info",
    speech_enabled: bool = True,
) -> bool:
    """Invoke one callback inside its immutable task speech scope.

    The callback itself still owns transport selection.  For the frozen voice
    bridge this scope is observed by the editable ``JarvisLive.speak`` wrapper;
    typed and remote callbacks keep their existing behavior.
    """
    if callback is None:
        return False
    scope = None
    if task_id:
        try:
            from jarvis.integrations.voice_speech import delivery_scope

            scope = delivery_scope(
                task_id=task_id,
                kind=kind,
                speech_enabled=speech_enabled,
            )
        except Exception as exc:                                   # noqa: BLE001
            quiet.swallowed("agent.dispatch.speech_scope_unavailable", exc)
    try:
        if scope is None:
            receipt = callback(value)
        else:
            with scope:
                receipt = callback(value)
        # Legacy callbacks conventionally return None. Only an explicit False
        # means the consumer declined delivery and registry fallback must own it.
        return receipt is not False
    except Exception as exc:                                       # noqa: BLE001
        quiet.swallowed("agent.dispatch.safe_callback_failed", exc)
        return False


def _finish_with_delivery(
    registry,
    task_id: str,
    *,
    callback,
    value: str,
    kind: str = "final",
    result: str = "",
    error: str = "",
    completion_owner: str = "auto",
) -> bool:
    """Expose terminal state, resolve speech owner, then publish completion."""
    owner = str(completion_owner or "auto").casefold()
    prepare = getattr(registry, "prepare_finish", None)
    publish = getattr(registry, "publish_finish", None)
    if callable(prepare) and callable(publish):
        automatic = owner not in {"registry", "caller"}
        provisional_owner = (
            "caller" if automatic and callback is not None else
            "registry" if automatic else owner
        )
        prepared = prepare(
            task_id,
            result=result,
            error=error,
            completion_owner=provisional_owner,
        )
        if prepared is None:
            # Another terminal path already claimed this task. Do not invoke
            # this callback or publish a duplicate completion.
            return False
        delivered = _safe_callback(
            callback,
            value,
            task_id=task_id,
            kind=kind,
            speech_enabled=owner != "registry",
        )
        if automatic:
            owner = "caller" if delivered else "registry"
        publish(task_id, completion_owner=owner)
        return delivered

    # Narrow compatibility for injected registries that only implement finish().
    delivered = _safe_callback(
        callback,
        value,
        task_id=task_id,
        kind=kind,
        speech_enabled=owner != "registry",
    )
    if owner not in {"registry", "caller"}:
        owner = "caller" if delivered else "registry"
    registry.finish(
        task_id,
        result=result,
        error=error,
        completion_owner=owner,
    )
    return delivered


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


def _clear_desktop_safe_session(session_id: str) -> None:
    """Revoke in-memory semantic refs when every agent run reaches a terminal path."""

    try:
        from jarvis.agent.tools.desktop_safe_click import desktop_safe_session
        desktop_safe_session().clear_session(session_id)
    except Exception as exc:                                # noqa: BLE001
        _logger.warning(
            "agent.dispatch.desktop_safe_cleanup_failed",
            session=str(session_id)[:32],
            error=str(exc)[:120],
        )


def dispatch_task(task: str, on_ack=None, on_done=None, on_error=None,
                  on_progress=None, on_task=None, adapter=None,
                  timeout_s: float | None = None,
                  allowed_tools: list[str] | None = None,
                  context=None, resources=frozenset(),
                  title: str | None = None,
                  source: str = "") -> "object | None":
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
                     on_progress=on_progress, on_task=on_task, adapter=adapter,
                     timeout_s=timeout_s, allowed_tools=allowed_tools,
                     context=context, resources=resources, title=title,
                     source=source)


def dispatch_async(task: str, on_ack=None, on_done=None, on_error=None,
                   adapter=None, timeout_s: float | None = None,
                   allowed_tools: list[str] | None = None,
                   context=None, on_progress=None, on_task=None,
                   resources=frozenset(), source: str = "") -> bool:
    """Mulai task agent di background. False bila agent tidak tersedia ATAU
    task sama masih berjalan. Callback dipanggil dari worker thread —
    marshal ke UI thread adalah tanggung jawab caller (sama dengan Hermes)."""
    return _dispatch(task, on_ack=on_ack, on_done=on_done, on_error=on_error,
                     on_progress=on_progress, on_task=on_task, adapter=adapter,
                     timeout_s=timeout_s, allowed_tools=allowed_tools,
                     context=context, resources=resources, source=source) is not None


def _dispatch(task: str, *, on_ack=None, on_done=None, on_error=None,
              on_progress=None, on_task=None, adapter=None,
              timeout_s: float | None = None,
              allowed_tools: list[str] | None = None,
              context=None, resources=frozenset(),
              title: str | None = None,
              source: str = ""):
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
    ingress_scope = current_source_scope()
    forced_completion_owner = (
        ingress_scope.completion_owner
        if ingress_scope is not None
        else "auto"
    )
    worker_context = contextvars.copy_context()

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
    # ke RUNNING setelah slot konkurensi + resource eksklusif didapat. Terminal
    # ownership is resolved from the callback matching the actual outcome.
    # Explicit ``source`` wins over the ingress scope: typed callers dispatch
    # from the UI thread without an active scope, but still identify as "ui".
    task_source = str(
        (source or "")
        or (ingress_scope.source if ingress_scope is not None else "")
        or getattr(adapter, "source", "")
        or getattr(adapter, "name", "")
        or "agent"
    )[:32]
    bg_task = REGISTRY.submit(
        task,
        title=title,
        resources=resources,
        completion_owner="registry",
        source=task_source,
    )
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

    scoped = getattr(adapter, "scoped", None)
    if callable(scoped):
        try:
            adapter = scoped(task_id=bg_task.id)
        except Exception as exc:                               # noqa: BLE001
            _logger.warning("agent.dispatch.adapter_scope_failed",
                            error=type(exc).__name__)
    metadata = TaskMetadata(
        id=bg_task.id,
        session_id=session.id,
        title=str(bg_task.title or title or task)[:160],
    )
    if on_task is not None:
        try:
            on_task(metadata)
        except Exception as exc:                               # noqa: BLE001
            quiet.swallowed("agent.dispatch.task_callback_failed", exc)

    evidence: list[ToolEvidence] = []
    plan_steps: list[dict] = []
    _collect_plan(session, plan_steps)
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
    # §24 — pengukuran dibuka di ACK, bukan di awal fungsi: ACK adalah titik
    # user mulai menunggu, dan itulah latensi yang ia rasakan.
    latency.start(session.id, task=task)
    _safe_callback(
        on_ack,
        acknowledgement,
        task_id=bg_task.id,
        kind="ack",
    )
    BUS.publish("agent.task.started", task=task, session=session.id)

    hard_timeout = timeout_s or float(config.get("agent.task_timeout_s", 900))

    def _worker():
        t0 = time.monotonic()
        # Menunggu slot + resource eksklusif DI SINI, bukan di pemanggil:
        # dispatch harus tetap kembali seketika (§8.3 "kembali SEKARANG").
        if not REGISTRY.acquire_slot(bg_task):
            _logger.info("agent.dispatch.cancelled_while_queued",
                         task=task[:80], id=bg_task.id)
            # acquire_slot already publishes cancellation. The matching callback
            # is UI/telemetry only; cancelled tasks are intentionally voice-silent.
            _safe_callback(
                on_error,
                "Tugas dibatalkan sebelum mulai.",
                task_id=bg_task.id,
                kind="final",
                speech_enabled=False,
            )
            with _active_lock:
                _active.pop(k, None)
            return
        REGISTRY.mark_running(bg_task.id)
        try:
            replayed = False

            async def _execute():
                nonlocal replayed
                # §25 — perintah yang PERSIS sama dan sudah terbukti berhasil
                # dijalankan langsung, tanpa satu pun panggilan model.
                shortcut = await _replay_plan(
                    task, adapter=run_adapter, session=session,
                    context=context, allowed=effective_tools)
                if shortcut is not None:
                    replayed = True
                    return shortcut
                return await agent_loop.run(
                    prepared.execution_prompt,
                    adapter=run_adapter, session=session,
                    allowed_tools=effective_tools,
                    max_iterations=int(config.get(
                        "agent.interactive_max_iterations", 12)),
                    model_profile="heavy", context=context,
                    bg_task=bg_task)

            result = asyncio.run(asyncio.wait_for(
                _execute(), timeout=hard_timeout))
            elapsed = round(time.monotonic() - t0, 1)
            if result.ok:
                text = result.text
                if prepared.contract is not None:
                    validation = prepared.contract.validate(evidence)
                    if not validation.ok:
                        err = (f"{prepared.contract.failure_label}: "
                               + validation.reason)
                        session.finish(err, ok=False)
                        _logger.warning(
                            "agent.dispatch.contract_failed",
                            task=task[:80], error=validation.reason[:300])
                        _finish_with_delivery(
                            REGISTRY,
                            bg_task.id,
                            callback=on_error,
                            value=err,
                            error=err,
                            completion_owner=forced_completion_owner,
                        )
                        BUS.publish("agent.task.failed", task=task, error=err,
                                    elapsed_s=elapsed)
                        return
                    text = _verified_success(prepared, evidence)
                    session.finish(text, ok=True)
                # §26 — belajar HANYA dari sukses yang terbukti. Bukti tool
                # sudah dikumpulkan untuk kontrak (Fase 14); memakai sumber
                # yang sama berarti indeks tidak pernah mengabadikan klaim
                # palsu — dan sekaligus tidak pernah lebih longgar daripada
                # kontraknya.
                _learn_command(task, session)
                _learn_plan(task, plan_steps, replayed)
                _logger.info("agent.dispatch.done", elapsed_s=elapsed,
                             session=result.session_id)
                _finish_with_delivery(
                    REGISTRY,
                    bg_task.id,
                    callback=on_done,
                    value=text,
                    result=text,
                    completion_owner=forced_completion_owner,
                )
                BUS.publish("agent.task.done", task=task, text=text,
                            elapsed_s=elapsed)
            else:
                err = result.text or "agent gagal"
                _finish_with_delivery(
                    REGISTRY,
                    bg_task.id,
                    callback=on_error,
                    value=err,
                    error=err,
                    completion_owner=forced_completion_owner,
                )
                BUS.publish("agent.task.failed", task=task, error=err,
                            elapsed_s=elapsed)
        except asyncio.TimeoutError:
            session.cancel()
            err = f"timeout {hard_timeout:.0f}s"
            _logger.error("agent.dispatch.timeout", task=task[:80])
            _finish_with_delivery(
                REGISTRY,
                bg_task.id,
                callback=on_error,
                value=err,
                error=err,
                completion_owner=forced_completion_owner,
            )
            BUS.publish("agent.task.failed", task=task, error=err)
        except Exception as e:                               # noqa: BLE001
            err = f"{type(e).__name__}: {str(e)[:200]}"
            _logger.error("agent.dispatch.crashed", error=err)
            _finish_with_delivery(
                REGISTRY,
                bg_task.id,
                callback=on_error,
                value=err,
                error=err,
                completion_owner=forced_completion_owner,
            )
            BUS.publish("agent.task.failed", task=task, error=err)
        finally:
            latency.finish(session.id)
            # Selalu lepas slot + resource, apa pun yang terjadi — kalau tidak,
            # satu crash membekukan seluruh antrean.
            REGISTRY.release_slot(bg_task)
            REGISTRY.finish(bg_task.id, error="selesai tanpa status")
            _release_browser_session(session.id)
            _release_computer_session(session.id)
            _clear_desktop_safe_session(session.id)
            with _active_lock:
                _active.pop(k, None)

    threading.Thread(
        target=lambda: worker_context.run(_worker),
        daemon=True,
        name=f"agent-{bg_task.id}",
    ).start()
    return bg_task


_source_scope: contextvars.ContextVar[DispatchSourceScope | None] = (
    contextvars.ContextVar("agent_dispatch_source_scope", default=None)
)


@contextmanager
def source_scope(
    source: str,
    *,
    completion_owner: str = "auto",
) -> Iterator[DispatchSourceScope]:
    label = str(source or "agent")[:32]
    owner = str(completion_owner or "auto").casefold()
    if owner not in {"auto", "registry", "caller"}:
        owner = "auto"
    scope = DispatchSourceScope(label, owner)
    token = _source_scope.set(scope)
    try:
        yield scope
    finally:
        _source_scope.reset(token)


def current_source_scope() -> DispatchSourceScope | None:
    return _source_scope.get()


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
            return _verified_success(prepared, evidence)
        return result.text
    except Exception as e:                                   # noqa: BLE001
        _logger.error("agent.run_sync_failed",
                      error=f"{type(e).__name__}: {str(e)[:150]}")
        return ""
    finally:
        _release_browser_session(session.id)
        _release_computer_session(session.id)
        _clear_desktop_safe_session(session.id)
