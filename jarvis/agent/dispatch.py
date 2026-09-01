"""Jalur masuk agent native Jarvis.

    ACK instan (<1 ms) → kerja di worker thread → callback done/error
    → BUS ``agent.task.done`` / ``agent.task.failed``.

Dedup guard: task identik yang masih berjalan tidak di-spawn dua kali.
"""
from __future__ import annotations

import asyncio
import contextvars
import math
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
    conversation_id: str = ""


@dataclass(frozen=True)
class ScreenControlScope:
    """One unambiguous live registry task eligible to own Screen Control."""

    session_id: str
    task_id: str


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


def screen_control_scope() -> ScreenControlScope | None:
    """Resolve exactly one live RUNNING task without exposing prompt content."""
    with _active_lock:
        candidates = [
            handle for handle in _active.values()
            if (
                not handle.session.cancelled
                and getattr(getattr(handle, "bg_task", None), "id", None)
                and handle.session.registry_task_id
                == getattr(handle.bg_task, "id", None)
            )
        ]
    if len(candidates) != 1:
        return None
    handle = candidates[0]
    task_id = str(handle.bg_task.id)
    try:
        from jarvis.agent.tasks import REGISTRY, TaskStatus
        view = REGISTRY.get(task_id)
    except Exception:
        return None
    if (
        view is None
        or view.status != TaskStatus.RUNNING
        or view.cancelled
        or not view.active
    ):
        return None
    with _active_lock:
        if (
            handle not in _active.values()
            or handle.session.cancelled
            or handle.session.registry_task_id != task_id
        ):
            return None
    return ScreenControlScope(handle.session.id, task_id)


def communication_authorization_scope(
    task_id: str,
    capability_ids,
    *,
    ttl_s: float = 60.0,
    uses: int = 1,
):
    """Build a local auth scope for one matching live dispatch session.

    Only stable identifiers leave this boundary. The passphrase remains owned by
    the Qt sheet and the returned scope never contains tool arguments or prompt
    content.
    """
    target = str(task_id or "").strip()
    capabilities = frozenset(
        str(item).strip() for item in (capability_ids or ())
        if str(item).strip()
    )
    try:
        ttl = float(ttl_s)
        use_count = int(uses)
    except (TypeError, ValueError):
        return None
    if (
        not target
        or not capabilities
        or not math.isfinite(ttl)
        or ttl <= 0
        or use_count <= 0
    ):
        return None
    with _active_lock:
        matches = [
            handle for handle in _active.values()
            if getattr(getattr(handle, "bg_task", None), "id", None) == target
        ]
        if len(matches) != 1:
            return None
        handle = matches[0]
        session = handle.session
        trace_id = str(
            getattr(getattr(session, "execution_context", None), "trace_id", "")
            or ""
        ).strip()
        if (
            session.cancelled
            or session.registry_task_id != target
            or not trace_id
        ):
            return None
    try:
        from jarvis.agent.tasks import REGISTRY
        view = REGISTRY.get(target)
    except Exception:
        return None
    if view is None or not view.active or view.cancelled:
        return None
    try:
        from jarvis.ui.communication_auth_sheet import AuthorizationScope
        return AuthorizationScope(
            task_id=target,
            trace_id=trace_id,
            capability_ids=capabilities,
            ttl_s=ttl,
            uses=use_count,
        )
    except Exception:
        return None


def request_communication_authorization(
    task_id: str,
    capability_ids,
    *,
    ttl_s: float = 60.0,
    uses: int = 1,
) -> bool:
    """Ask the registered desktop UI to present the local-only auth sheet."""
    scope = communication_authorization_scope(
        task_id,
        capability_ids,
        ttl_s=ttl_s,
        uses=uses,
    )
    if scope is None:
        return False
    try:
        BUS.publish(
            "communication.authorization.required",
            task_id=scope.task_id,
            capability_ids=sorted(scope.capability_ids),
            ttl_s=scope.ttl_s,
            uses=scope.uses,
        )
        return True
    except Exception:
        return False


def bind_communication_grant(
    grant_id: str,
    *,
    task_id: str,
    trace_id: str,
    capability_ids,
) -> bool:
    """Attach one validated opaque override grant to its live session.

    A failed binding always revokes the supplied grant. Validation is
    non-consuming; registry.execute remains the only owner that consumes uses.
    """
    opaque_id = str(grant_id or "").strip()
    target = str(task_id or "").strip()
    trace = str(trace_id or "").strip()
    capabilities = frozenset(
        str(item).strip() for item in (capability_ids or ())
        if str(item).strip()
    )

    def _reject() -> bool:
        if opaque_id:
            try:
                from jarvis.agent.execution_grants import MANAGER
                MANAGER.revoke(opaque_id)
            except Exception:
                pass
        return False

    if not opaque_id or not target or not trace or not capabilities:
        return _reject()
    try:
        from jarvis.agent import communication_mode
        from jarvis.agent.execution_grants import (
            MANAGER,
            PURPOSE_COMMUNICATION_OVERRIDE,
        )
        from jarvis.agent.tasks import REGISTRY
        if not communication_mode.active():
            return _reject()
        view = REGISTRY.get(target)
        if view is None or not view.active or view.cancelled:
            return _reject()
        generation = communication_mode.generation()
        grant = MANAGER.get(opaque_id)
        if (
            grant is None
            or grant.purpose != PURPOSE_COMMUNICATION_OVERRIDE
            or grant.task_id != target
            or grant.trace_id != trace
            or grant.capability_ids != capabilities
            or grant.generation != generation
            or any(
                not MANAGER.verify(
                    opaque_id,
                    purpose=PURPOSE_COMMUNICATION_OVERRIDE,
                    task_id=target,
                    trace_id=trace,
                    capability_id=capability_id,
                    generation=generation,
                    consume=False,
                )
                for capability_id in capabilities
            )
        ):
            return _reject()
    except Exception:
        return _reject()

    previous = ""
    with _active_lock:
        matches = [
            handle for handle in _active.values()
            if getattr(getattr(handle, "bg_task", None), "id", None) == target
        ]
        if len(matches) != 1:
            return _reject()
        handle = matches[0]
        session = handle.session
        session_trace = str(
            getattr(getattr(session, "execution_context", None), "trace_id", "")
            or ""
        ).strip()
        if (
            session.cancelled
            or session.registry_task_id != target
            or session_trace != trace
        ):
            return _reject()
        current = REGISTRY.get(target)
        if current is None or not current.active or current.cancelled:
            return _reject()
        previous = str(session.communication_grant_id or "")
        session.communication_grant_id = opaque_id
    if previous and previous != opaque_id:
        MANAGER.revoke(previous)
    return True


def cancel_all() -> int:
    try:
        BUS.publish("agent.tasks.cancel_all")
    except Exception as exc:                                # noqa: BLE001
        quiet.swallowed("agent.dispatch.cancel_all_publish_failed", exc)
    with _active_lock:
        handles = list(_active.values())
    for h in handles:
        bg = h.bg_task
        if bg is not None:
            _clear_captcha_handoff_session(
                h.session.id,
                "agent.tasks.cancel_all",
            )
            _release_screen_control_session(
                h.session.id,
                "agent.tasks.cancel_all",
            )
            _revoke_execution_grants(bg.id)
            h.session.execution_grant_id = ""
            h.session.communication_grant_id = ""
            h.session.registry_task_id = ""
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
        _clear_captcha_handoff_session(handle.session.id, "task_cancelled")
        _release_screen_control_session(handle.session.id, "task_cancelled")
        _revoke_execution_grants(tid)
        handle.session.execution_grant_id = ""
        handle.session.communication_grant_id = ""
        handle.session.registry_task_id = ""
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


async def _replay_plan(
    task: str,
    *,
    adapter,
    session,
    context,
    allowed,
    overlay=None,
):
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
        result = await registry.execute(
            step["tool"],
            dict(step["args"]),
            adapter=adapter,
            session=session,
            context=context,
            overlay=overlay,
        )
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


def _release_screen_control_session(
    session_id: str,
    reason: str = "task_terminal",
) -> None:
    """Release matching Screen Control authority on every terminal path."""
    try:
        from jarvis.ui.screen_control import COORDINATOR
        COORDINATOR.release_session(session_id, reason)
    except Exception as exc:                                # noqa: BLE001
        _logger.warning(
            "agent.dispatch.screen_control_cleanup_failed",
            session=str(session_id)[:32],
            error=type(exc).__name__,
        )


def _clear_captcha_handoff_session(
    session_id: str,
    reason: str = "task_terminal",
) -> None:
    """Retire an opaque process-local handoff before task identity is erased."""
    try:
        from jarvis.agent.captcha_handoff import OWNER

        OWNER.clear_session(session_id, reason)
    except Exception as exc:                                # noqa: BLE001
        _logger.warning(
            "agent.dispatch.captcha_handoff_cleanup_failed",
            session=str(session_id)[:32],
            error=type(exc).__name__,
        )


def _revoke_execution_grants(task_id: str) -> None:
    """Revoke every process-local grant when its registry task terminates."""

    try:
        from jarvis.agent.execution_grants import MANAGER
        MANAGER.revoke_task(task_id)
    except Exception as exc:                                # noqa: BLE001
        _logger.warning(
            "agent.dispatch.execution_grant_cleanup_failed",
            id=str(task_id)[:32],
            error=type(exc).__name__,
        )


def dispatch_task(task: str, on_ack=None, on_done=None, on_error=None,
                  on_progress=None, on_task=None, adapter=None,
                  timeout_s: float | None = None,
                  allowed_tools: list[str] | None = None,
                  context=None, resources=frozenset(),
                  title: str | None = None,
                  source: str = "",
                  direct_grant_capability_ids=()) -> "object | None":
    """Varian §8.3 yang mengembalikan ``Task`` (atau ``None``) alih-alih bool.

    Dipakai permukaan baru (Task Deck, tool suara ``task_start``) yang butuh
    id tugas untuk menampilkan progres dan membatalkan.

    ``dispatch_async`` di bawah tetap mengembalikan ``bool`` — kontrak itu
    dipegang belasan pemanggil dan ditegaskan tes
    (``tests/test_phase2_dispatch.py:46`` ``assert started is True``,
    ``tests/test_execution_context.py:57`` ``is False``), jadi tanda tangan
    §8.3 diterapkan sebagai fungsi BARU, bukan penggantian.
    """
    return _dispatch(
        task, on_ack=on_ack, on_done=on_done, on_error=on_error,
        on_progress=on_progress, on_task=on_task, adapter=adapter,
        timeout_s=timeout_s, allowed_tools=allowed_tools,
        context=context, resources=resources, title=title, source=source,
        direct_grant_capability_ids=direct_grant_capability_ids,
    )


def dispatch_async(task: str, on_ack=None, on_done=None, on_error=None,
                   adapter=None, timeout_s: float | None = None,
                   allowed_tools: list[str] | None = None,
                   context=None, on_progress=None, on_task=None,
                   resources=frozenset(), source: str = "",
                   direct_grant_capability_ids=()) -> bool:
    """Mulai task agent di background. False bila agent tidak tersedia ATAU
    task sama masih berjalan. Callback dipanggil dari worker thread —
    marshal ke UI thread adalah tanggung jawab caller (sama dengan Hermes)."""
    return _dispatch(
        task, on_ack=on_ack, on_done=on_done, on_error=on_error,
        on_progress=on_progress, on_task=on_task, adapter=adapter,
        timeout_s=timeout_s, allowed_tools=allowed_tools,
        context=context, resources=resources, source=source,
        direct_grant_capability_ids=direct_grant_capability_ids,
    ) is not None


def _dispatch(task: str, *, on_ack=None, on_done=None, on_error=None,
              on_progress=None, on_task=None, adapter=None,
              timeout_s: float | None = None,
              allowed_tools: list[str] | None = None,
              context=None, resources=frozenset(),
              title: str | None = None,
              source: str = "", direct_grant_capability_ids=()):
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
    from jarvis.agent import communication_mode
    if communication_mode.active():
        _logger.info("agent.dispatch.communication_locked")
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
    session.registry_task_id = bg_task.id
    with _active_lock:
        handle = _active.get(k)
        if handle is not None:
            handle.bg_task = bg_task

    requested_direct_caps = frozenset(
        str(item).strip() for item in (direct_grant_capability_ids or ())
        if str(item).strip()
    )
    if requested_direct_caps:
        failure = ""
        try:
            from jarvis.agent.capabilities import REGISTRY as capabilities
            eligible = {
                descriptor.id for descriptor in capabilities.descriptors()
                if descriptor.direct_grant
            }
            if not requested_direct_caps.issubset(eligible):
                failure = "direct grant capability denied"
                raise ValueError(failure)
            trace_id = str(getattr(context, "trace_id", "") or "")
            if not trace_id:
                failure = "direct grant trace required"
                raise ValueError(failure)
            from jarvis.agent.execution_grants import (
                MANAGER as execution_grants,
                PURPOSE_DIRECT_EXECUTION,
            )
            grant = execution_grants.issue(
                purpose=PURPOSE_DIRECT_EXECUTION,
                task_id=bg_task.id,
                trace_id=trace_id,
                capability_ids=requested_direct_caps,
                ttl_s=min(
                    float(timeout_s or config.get("agent.task_timeout_s", 900)),
                    900.0,
                ),
                uses=max(1, len(requested_direct_caps)),
                generation=0,
            )
            session.execution_grant_id = grant.id
            if session.cancelled:
                failure = "direct grant task cancelled"
                raise RuntimeError(failure)
        except Exception as exc:                               # noqa: BLE001
            _revoke_execution_grants(bg_task.id)
            session.execution_grant_id = ""
            session.communication_grant_id = ""
            session.registry_task_id = ""
            REGISTRY.finish(
                bg_task.id,
                error=failure or "direct grant unavailable",
                completion_owner="caller",
            )
            with _active_lock:
                _active.pop(k, None)
            _logger.warning(
                "agent.dispatch.direct_grant_failed",
                id=bg_task.id,
                error=type(exc).__name__,
            )
            return None

    scoped = getattr(adapter, "scoped", None)
    if callable(scoped):
        try:
            adapter = scoped(task_id=bg_task.id)
        except Exception as exc:                               # noqa: BLE001
            _logger.warning("agent.dispatch.adapter_scope_failed",
                            error=type(exc).__name__)
    capability_overlay = None
    try:
        from jarvis.agent.local_run_capabilities import (
            mint_selected_tab_overlay,
        )

        capability_overlay = mint_selected_tab_overlay(
            session_id=session.id,
            task_id=bg_task.id,
            adapter=adapter,
        )
    except ValueError:
        # Remote/headless/non-UI dispatch is expected and stays unchanged.
        capability_overlay = None
    except Exception as exc:                                  # noqa: BLE001
        _logger.warning(
            "agent.dispatch.selected_tab_overlay_unavailable",
            error=type(exc).__name__,
        )
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
    elif ingress_scope is not None and ingress_scope.conversation_id:
        # Editable seam for ingress paths whose caller (FROZEN main.py) cannot
        # supply on_task: bind the real registry ID to immediate context here,
        # before ACK, so the FROZEN voice path is addressable like typed ones.
        try:
            from jarvis.agent import conversation_context
            conversation_context.STORE.begin_task(
                ingress_scope.conversation_id,
                task_id=str(metadata.id),
                task=str(metadata.title or task)[:800],
                source=ingress_scope.source,
            )
        except Exception as exc:                               # noqa: BLE001
            quiet.swallowed("agent.dispatch.context_bind_failed", exc)

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
    # Fase 42 — tutup turn voice_ack: total_ms-nya = rentang gelap
    # akhir-ucapan → dispatch (ACK area). No-op untuk input non-voice.
    latency.voice_handoff()
    _safe_callback(
        on_ack,
        acknowledgement,
        task_id=bg_task.id,
        kind="ack",
    )
    def _abort_pre_worker(reason: str) -> None:
        """Tutup SEMUA state yang dibuka sebelum worker mengambil ownership.

        Worker belum pernah hidup, jadi pemanggil yang menemui kegagalan di
        jendela ini wajib menutup semuanya sendiri. Satu helper untuk kedua
        penjaga di bawah agar daftar tutupnya tidak pernah menyimpang — Fase 54
        dan 55 menunjukkan daftar yang diduplikasi adalah daftar yang kelak
        hanya separuh diperbaiki.
        """
        latency.cancel(session.id)
        REGISTRY.finish(
            bg_task.id,
            error=reason,
            completion_owner="caller",
        )
        _release_browser_session(session.id)
        _release_computer_session(session.id)
        _clear_desktop_safe_session(session.id)
        _clear_captcha_handoff_session(session.id)
        _release_screen_control_session(session.id)
        _revoke_execution_grants(bg_task.id)
        session.execution_grant_id = ""
        session.communication_grant_id = ""
        session.registry_task_id = ""
        with _active_lock:
            _active.pop(k, None)

    # Sisa jendela sebelum worker juga bisa gagal, bukan hanya thread-nya.
    # ``EventBus.publish`` hanya menaungi kegagalan SUBSCRIBER (``bus.py:58``);
    # ``self._ui_queue.put(...)`` di baris 64 berada DI LUAR penjaga itu, jadi
    # antrean UI yang menolak item membuat exception merambat ke sini — setelah
    # turn dibuka, setelah registry submit, dan setelah ACK dikirim.
    try:
        BUS.publish("agent.task.started", task=task, session=session.id)
        hard_timeout = timeout_s or float(config.get("agent.task_timeout_s", 900))
    except Exception:
        _abort_pre_worker("dispatch gagal sebelum worker dimulai")
        raise

    def _worker():
        t0 = time.monotonic()
        acquired = False
        try:
            # Menunggu slot + resource eksklusif DI SINI, bukan di pemanggil:
            # dispatch harus tetap kembali seketika (§8.3 "kembali SEKARANG").
            acquired = REGISTRY.acquire_slot(bg_task)
            if not acquired:
                _logger.info(
                    "agent.dispatch.cancelled_while_queued",
                    task=task[:80],
                    id=bg_task.id,
                )
                # acquire_slot already publishes cancellation. The matching
                # callback is UI/telemetry only; cancelled tasks stay voice-silent.
                _safe_callback(
                    on_error,
                    "Tugas dibatalkan sebelum mulai.",
                    task_id=bg_task.id,
                    kind="final",
                    speech_enabled=False,
                )
                return
            REGISTRY.mark_running(bg_task.id)
            replayed = False

            async def _execute():
                nonlocal replayed
                # §25 — perintah yang PERSIS sama dan sudah terbukti berhasil
                # dijalankan langsung, tanpa satu pun panggilan model.
                shortcut = await _replay_plan(
                    task,
                    adapter=run_adapter,
                    session=session,
                    context=context,
                    allowed=effective_tools,
                    overlay=capability_overlay,
                )
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
                    bg_task=bg_task, overlay=capability_overlay)

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
        except asyncio.CancelledError:
            # ``CancelledError`` adalah ``BaseException`` sejak 3.8, jadi ia
            # melewati ``except Exception`` di bawah dan hanya ditangani
            # ``finally``. Terukur: task tercatat "selesai tanpa status" dan
            # ``on_error`` tidak pernah dipanggil — pemakai mendapat keheningan
            # padahal task-nya gagal. Pembatalan tetap layak diberitahu.
            session.cancel()
            err = "tugas dibatalkan"
            _logger.info("agent.dispatch.cancelled", task=task[:80])
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
            # satu crash membekukan seluruh antrean. Jalur batal-saat-mengantre
            # belum memiliki slot, jadi jangan mengarang release yang tak dimiliki.
            if acquired:
                REGISTRY.release_slot(bg_task)
            REGISTRY.finish(bg_task.id, error="selesai tanpa status")
            _release_browser_session(session.id)
            _release_computer_session(session.id)
            _clear_desktop_safe_session(session.id)
            _clear_captcha_handoff_session(session.id)
            _release_screen_control_session(session.id)
            _revoke_execution_grants(bg_task.id)
            session.execution_grant_id = ""
            session.communication_grant_id = ""
            session.registry_task_id = ""
            with _active_lock:
                _active.pop(k, None)

    try:
        # Konstruksi DAN start berada di dalam penjaga yang sama. Keduanya
        # terjadi setelah seluruh state dibuka, dan keduanya bisa gagal karena
        # alasan OS (batas thread, memori). Fase 54 hanya menjaga start();
        # konstruksi yang gagal terbukti meninggalkan tiga yatim yang sama.
        worker_thread = threading.Thread(
            target=lambda: worker_context.run(_worker),
            daemon=True,
            name=f"agent-{bg_task.id}",
        )
        worker_thread.start()
    except Exception:
        _abort_pre_worker("worker gagal dibuat atau dimulai")
        raise
    return bg_task


_source_scope: contextvars.ContextVar[DispatchSourceScope | None] = (
    contextvars.ContextVar("agent_dispatch_source_scope", default=None)
)


@contextmanager
def source_scope(
    source: str,
    *,
    completion_owner: str = "auto",
    conversation_id: str = "",
) -> Iterator[DispatchSourceScope]:
    label = str(source or "agent")[:32]
    owner = str(completion_owner or "auto").casefold()
    if owner not in {"auto", "registry", "caller"}:
        owner = "auto"
    scope = DispatchSourceScope(label, owner, str(conversation_id or "")[:96])
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
