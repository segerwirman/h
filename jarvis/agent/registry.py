"""Tool registry — auto-discovery dari ``jarvis/agent/tools/``.

Modul tool yang gagal import (dependency opsional hilang, kredensial kosong)
di-skip dengan log; Jarvis tetap jalan. Eksekusi tool selalu lewat
``execute()``: timeout, konfirmasi, logging JSONL, tidak pernah raise.
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import pkgutil
import threading
import time

from jarvis.core import config, log
from jarvis.agent.base import Tool, ToolResult

from jarvis.core import quiet
_logger = log.get("agent.registry")

_tools: dict[str, Tool] | None = None
_lock = threading.Lock()
_log_lock = threading.Lock()

#: Naik setiap kali tool ditemukan ulang. Semua cache turunan berpegang pada
#: angka ini — cache yang tidak pernah basi adalah cache yang menyembunyikan
#: bug.
_generation = 0
_schema_lock = threading.Lock()
_schema_cache: dict[tuple, dict] = {}
_schema_fingerprint: tuple | None = None


def generation() -> int:
    """Nomor generasi registry saat ini; berubah bila tool ditemukan ulang."""
    return _generation


def fingerprint() -> tuple:
    """Identitas himpunan tool saat ini — dasar SEMUA cache turunan.

    Nomor generasi saja tidak cukup: ``_tools`` bisa diganti langsung (tes
    melakukannya, dan apa pun yang menyuntik registry bisa juga) tanpa lewat
    ``_discover``. Cache yang berpegang pada generasi saja akan menjawab dari
    himpunan tool yang sudah tidak ada — dan itu diam-diam, yang membuatnya
    jauh lebih mahal daripada menghitung ulang.
    """
    tools = _tools
    return (_generation, tuple(sorted(tools)) if tools else ())


def all_tools(refresh: bool = False) -> dict[str, Tool]:
    global _tools, _generation
    with _lock:
        if _tools is None or refresh:
            _tools = _discover()
            _generation += 1
    if refresh:
        invalidate_schema_cache()
    return dict(_tools)


def invalidate_schema_cache() -> None:
    global _schema_fingerprint
    with _schema_lock:
        _schema_cache.clear()
        _schema_fingerprint = None


def _tool_schema(name: str, tool: Tool, mark: tuple) -> dict:
    """Schema satu tool. Murni terhadap toolnya, jadi aman di-cache.

    §29 — ``json_schema()`` untuk 103 tool memakan 21,9 ms setiap kali
    ``schemas()`` dipanggil, dan hasilnya identik selama himpunan toolnya
    sama. Tidak ada context atau policy yang ikut ke sini dengan sengaja:
    penyaringan itu tetap dihitung segar di ``schemas()``, karena cache basi
    di sana berarti izin yang sudah dicabut masih berlaku.
    """
    global _schema_fingerprint
    with _schema_lock:
        if _schema_fingerprint != mark:
            _schema_cache.clear()
            _schema_fingerprint = mark
        key = (name, id(tool))
        cached = _schema_cache.get(key)
        if cached is not None:
            return cached
    built = {"type": "function", "function": {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.json_schema()}}
    with _schema_lock:
        if _schema_fingerprint == mark:
            _schema_cache[key] = built
    return built


def get(name: str) -> Tool | None:
    return all_tools().get(name)


def _grant_scope(session, context, field_name: str) -> tuple[str, str, str]:
    grant_id = str(getattr(session, field_name, "") or "")
    task_id = str(getattr(session, "registry_task_id", "") or "")
    trace_id = str(getattr(context, "trace_id", "") or "")
    return grant_id, task_id, trace_id


def _communication_admission(descriptor, session, context) -> tuple[bool, bool]:
    """Return ``(allowed, consumes_override)`` for the current lock state."""
    from jarvis.agent import communication_mode

    if not communication_mode.active():
        return True, False
    if communication_mode.is_escape(descriptor.tool_name):
        return True, False
    grant_id, task_id, trace_id = _grant_scope(
        session,
        context,
        "communication_grant_id",
    )
    if not grant_id or not task_id or not trace_id:
        return False, False
    try:
        from jarvis.agent.execution_grants import (
            MANAGER,
            PURPOSE_COMMUNICATION_OVERRIDE,
        )
        valid = MANAGER.verify(
            grant_id,
            purpose=PURPOSE_COMMUNICATION_OVERRIDE,
            task_id=task_id,
            trace_id=trace_id,
            capability_id=descriptor.id,
            generation=communication_mode.generation(),
            consume=False,
        )
    except Exception:
        return False, False
    return bool(valid), bool(valid)


def _consume_communication_override(descriptor, session, context) -> bool:
    from jarvis.agent import communication_mode
    from jarvis.agent.execution_grants import (
        MANAGER,
        PURPOSE_COMMUNICATION_OVERRIDE,
    )

    if not communication_mode.active():
        return False
    grant_id, task_id, trace_id = _grant_scope(
        session,
        context,
        "communication_grant_id",
    )
    if not grant_id or not task_id or not trace_id:
        return False
    try:
        return MANAGER.verify(
            grant_id,
            purpose=PURPOSE_COMMUNICATION_OVERRIDE,
            task_id=task_id,
            trace_id=trace_id,
            capability_id=descriptor.id,
            generation=communication_mode.generation(),
            consume=True,
        )
    except Exception:
        return False


def _direct_confirmation_granted(descriptor, session, context) -> bool:
    if not descriptor.direct_grant:
        return False
    grant_id, task_id, trace_id = _grant_scope(
        session,
        context,
        "execution_grant_id",
    )
    if not grant_id or not task_id or not trace_id:
        return False
    try:
        from jarvis.agent.execution_grants import (
            MANAGER,
            PURPOSE_DIRECT_EXECUTION,
        )
        return MANAGER.verify(
            grant_id,
            purpose=PURPOSE_DIRECT_EXECUTION,
            task_id=task_id,
            trace_id=trace_id,
            capability_id=descriptor.id,
            generation=0,
            consume=True,
        )
    except Exception:
        return False


def _discover() -> dict[str, Tool]:
    import jarvis.agent.tools as tools_pkg

    found: dict[str, Tool] = {}
    for modinfo in pkgutil.iter_modules(tools_pkg.__path__):
        if modinfo.name.startswith("_"):
            continue
        mod_name = f"jarvis.agent.tools.{modinfo.name}"
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:                               # noqa: BLE001
            _logger.warning("agent.tools.module_skipped", module=modinfo.name,
                            error=str(e)[:120])
            continue
        # modul boleh menyediakan gate ketersediaan (kredensial dsb.)
        gate = getattr(mod, "available", None)
        try:
            if callable(gate) and not gate():
                _logger.info("agent.tools.module_disabled", module=modinfo.name)
                continue
        except Exception as exc:                                    # noqa: BLE001
            quiet.swallowed("agent.registry.discover_skipped", exc)
            continue
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if (issubclass(cls, Tool) and cls is not Tool
                    and cls.__module__ == mod_name and cls.name):
                try:
                    tool = cls()
                    if not tool.is_available():
                        continue
                    found[tool.name] = tool
                except Exception as e:                       # noqa: BLE001
                    _logger.warning("agent.tools.init_failed", tool=cls.name,
                                    error=str(e)[:120])
    _logger.info("agent.tools.discovered", count=len(found),
                 names=sorted(found))
    return found


def schemas(allowed: list[str] | None = None,
            exclude: list[str] | None = None, context=None,
            overlay=None) -> list[dict]:
    """Schema gaya OpenAI; protected local tools need an exact overlay."""
    from jarvis.agent.capabilities import REGISTRY as capability_registry
    from jarvis.agent.local_run_capabilities import LocalRunCapabilityOverlay

    context_allowed = None
    if context is not None:
        context_allowed = set(capability_registry.exposed_tool_names(context))
    out = []
    mark = fingerprint()
    # §29 — SATU snapshot descriptor untuk seluruh loop. Bentuk lama memanggil
    # ``descriptor_for_tool`` per tool dan tiap panggilan membangun ulang daftar
    # 103-item: 16,5 ms di setiap ``schemas()``. Indeksnya lokal dan mati saat
    # fungsi ini selesai, jadi tidak ada jawaban basi yang bisa bertahan.
    descriptors_by_tool = capability_registry.by_tool_name()
    overlay_allowed = (
        {
            name
            for name in overlay.tool_names
            if (descriptor := descriptors_by_tool.get(name)) is not None
            and descriptor.enabled
            and descriptor.toolset == "selected_tab"
        }
        if isinstance(overlay, LocalRunCapabilityOverlay)
        else set()
    )
    protected_toolsets = {"desktop_safe", "selected_tab"}
    for name, tool in sorted(all_tools().items()):
        descriptor = descriptors_by_tool.get(name)
        if descriptor is not None and descriptor.toolset in protected_toolsets:
            if descriptor.toolset == "selected_tab":
                if name not in overlay_allowed:
                    continue
            elif context is None:
                continue
        if allowed is not None and name not in allowed:
            continue
        if (
            context_allowed is not None
            and name not in context_allowed
            and name not in overlay_allowed
        ):
            continue
        if exclude and name in exclude:
            continue
        out.append(_tool_schema(name, tool, mark))
    return out


async def execute(name: str, args: dict, adapter=None,
                  session=None, context=None, overlay=None,
                  _approved_request_id: str = "") -> ToolResult:
    """Jalankan satu tool dengan seluruh guardrail. Tidak pernah raise."""
    tool = get(name)
    if tool is None:
        return ToolResult.fail(f"tool tidak dikenal: {name}")

    args = dict(args or {})
    args.pop("_raw", None)
    policy_approval_granted = False
    confirmation_granted = False
    from jarvis.agent.capabilities import REGISTRY as capability_registry
    descriptor = capability_registry.descriptor_for_tool(name)
    if descriptor is None:
        return ToolResult.fail("capability tidak terdaftar untuk execution context")
    if descriptor.toolset == "desktop_safe" and context is None:
        return ToolResult.fail("desktop_safe membutuhkan execution context desktop-local")
    if descriptor.toolset == "selected_tab":
        from jarvis.agent.local_run_capabilities import selected_tab_context

        context, overlay_error = selected_tab_context(
            overlay,
            tool_name=name,
            session=session,
            adapter=adapter,
        )
        if overlay_error:
            return ToolResult.fail(overlay_error)
    communication_allowed, communication_override = _communication_admission(
        descriptor,
        session,
        context,
    )
    if not communication_allowed:
        requested = False
        if _is_active_native_desktop_adapter(adapter):
            try:
                from jarvis.agent import dispatch
                requested = dispatch.request_communication_authorization(
                    str(getattr(session, "registry_task_id", "") or ""),
                    {descriptor.id},
                )
            except Exception:
                requested = False
        detail = (
            "; otorisasi lokal diminta"
            if requested else ""
        )
        return ToolResult.fail(
            f"execution dikunci selama mode komunikasi aktif{detail}"
        )

    if context is not None:
        from jarvis.agent import policy
        decision = policy.decide(context, capability=descriptor.id, risk=descriptor.risk)
        if decision.needs_approval:
            from jarvis.agent.approval import ApprovalStore
            from jarvis.agent import approval_continuations
            from jarvis.agent.paths import data_dir
            store = ApprovalStore(data_dir() / "approvals.sqlite")
            approved_id = str(_approved_request_id or "").strip()
            if approved_id:
                if not store.approved_for(approved_id, context.trace_id, descriptor.id):
                    return ToolResult.fail("approval tidak valid untuk tool execution ini")
                policy_approval_granted = True
            else:
                request = store.request(context.trace_id, descriptor.id, decision.reason)
                approval_continuations.register(
                    request.id,
                    is_approved=lambda: store.approved_for(
                        request.id, context.trace_id, descriptor.id),
                    runner=lambda: execute(
                        name, args, adapter, session, context, overlay,
                        _approved_request_id=request.id),
                )
                return ToolResult.fail(
                    f"approval diperlukan sebelum tool dijalankan ({request.id})")
        if not decision.allowed and not (decision.needs_approval and approved_id):
            return ToolResult.fail(f"policy menolak tool: {decision.reason}")

    if descriptor.toolset == "selected_tab":
        from jarvis.agent.policy import selected_tab_context_error

        context_error = selected_tab_context_error(
            context,
            capability=descriptor.id,
            risk=descriptor.risk,
            runtime_session=session,
        )
        if context_error:
            return ToolResult.fail(context_error)

    # konfirmasi tool berbahaya — via adapter; sesi cron menolak otomatis
    try:
        needs = tool.needs_confirmation(**args)
    except Exception:                                        # noqa: BLE001
        needs = tool.requires_confirmation
    direct_confirmation = False
    if needs and not policy_approval_granted:
        direct_confirmation = _direct_confirmation_granted(
            descriptor,
            session,
            context,
        )
    if needs and not policy_approval_granted and not direct_confirmation:
        if descriptor.toolset == "desktop_safe" and not _is_active_native_desktop_adapter(adapter):
            return ToolResult.fail(
                "desktop_safe confirmation membutuhkan adapter desktop-local")
        # §17 — permintaan identik yang SUDAH ditolak tidak ditanyakan ulang.
        # Pesan gagal lama sudah berbunyi "jangan ulangi tanpa diminta", tetapi
        # itu menitipkan jaminan pada kepatuhan model. Tiap pengulangan memakan
        # satu iterasi, dan begitulah batas iterasi habis tanpa pekerjaan nyata
        # (S-5). Penolakan mengikat SATU permintaan (tool + argumen), bukan
        # seluruh tool selamanya.
        denied_key = _confirmation_key(name, args)
        if _confirmation_denied(session, denied_key):
            res = ToolResult.fail(
                "permintaan identik sudah ditolak user di sesi ini — "
                "jangan tanyakan lagi; lanjutkan tanpa aksi ini atau "
                "tanyakan apa yang user inginkan")
            _log_call(name, args, res, 0.0, session)
            return res
        approved = False
        if adapter is not None:
            try:
                ans = await adapter.ask(tool.confirmation_text(**args),
                                        ["Lanjut", "Batal"])
                approved = str(ans or "").strip().lower() in (
                    "lanjut", "ya", "yes", "confirm", "konfirmasi", "ok", "1")
            except Exception as e:                           # noqa: BLE001
                _logger.warning("agent.confirm_failed", tool=name,
                                error=str(e)[:100])
        if not approved:
            _remember_denial(session, denied_key)
            res = ToolResult.fail("aksi butuh konfirmasi user dan tidak "
                                  "disetujui — jangan ulangi tanpa diminta")
            _log_call(name, args, res, 0.0, session)
            return res
        confirmation_granted = True

    # tool yang menyatakan wants_context menerima sesi+adapter aktif
    # (todo per-sesi, clarify, delegate, snapshot kamera via UI adapter)
    if getattr(tool, "wants_context", False):
        args["_session"] = session
        args["_adapter"] = adapter
        args["_context"] = context
        if descriptor.toolset == "desktop_safe":
            args["_desktop_safe_confirmation"] = confirmation_granted

    if communication_override:
        # Re-check after policy/approval/confirmation awaits and consume exactly
        # one use immediately before the actual side effect.
        if not _consume_communication_override(descriptor, session, context):
            return ToolResult.fail(
                "execution dikunci atau izin komunikasi sudah tidak valid"
            )

    t0 = time.perf_counter()
    try:
        res = await asyncio.wait_for(tool.run(**args),
                                     timeout=float(tool.timeout_s))
        if not isinstance(res, ToolResult):
            res = ToolResult.success(res)
    except asyncio.TimeoutError:
        res = ToolResult.fail(f"timeout {tool.timeout_s}s")
    except TypeError as e:
        res = ToolResult.fail(f"argumen tidak valid: {str(e)[:200]}")
    except Exception as e:                                   # noqa: BLE001
        res = ToolResult.fail(f"{type(e).__name__}: {str(e)[:300]}")
    elapsed = time.perf_counter() - t0
    _log_call(name, args, res, elapsed, session)
    return res


def _confirmation_key(name: str, args: dict) -> str:
    """Identitas satu permintaan berkonfirmasi: nama tool + argumen publik."""
    import json

    public = {str(k): v for k, v in dict(args or {}).items()
              if not str(k).startswith("_")}
    try:
        payload = json.dumps(public, sort_keys=True, ensure_ascii=False,
                             default=str)
    except Exception:                                        # noqa: BLE001
        payload = str(sorted(public))
    return f"{name}:{payload}"[:600]


def _confirmation_denied(session, key: str) -> bool:
    try:
        return key in getattr(session, "denied_confirmations", ())
    except Exception:                                        # noqa: BLE001
        return False


def _remember_denial(session, key: str) -> None:
    if session is None:
        return
    try:
        denied = getattr(session, "denied_confirmations", None)
        if denied is None:
            denied = set()
            setattr(session, "denied_confirmations", denied)
        denied.add(key)
    except Exception as exc:                                        # noqa: BLE001
        quiet.swallowed("agent.registry.remember_denial_failed", exc)


def _is_active_native_desktop_adapter(adapter) -> bool:
    """Accept confirmation only from the live, native JARVIS desktop bridge."""
    try:
        from jarvis.agent.adapters.ui import UIAdapter
        return type(adapter) is UIAdapter and adapter._win() is not None
    except Exception:  # noqa: BLE001
        return False


def _log_call(name: str, args: dict, res: ToolResult, elapsed_s: float,
              session) -> None:
    safe_args = _audit_args(name, args)
    safe_error = _audit_error(name, res.error)
    _logger.info("agent.tool", tool=name, ok=res.ok,
                 elapsed_ms=round(elapsed_s * 1000, 1),
                 error=(safe_error or "")[:120] or None)
    if session is not None:
        try:
            session_result = ToolResult(
                ok=res.ok, content=None, display=None, error=safe_error, meta={})
            record_tool = getattr(session, "record_tool", None)
            if callable(record_tool):
                record_tool(name, safe_args, session_result, elapsed_s)
        except Exception as exc:                                    # noqa: BLE001
            quiet.swallowed("agent.registry.log_call_failed", exc)
        # Kanal bukti kontrak (S-12) — hasil UTUH, terpisah dari audit di atas.
        # Tanpa ini validator kontrak hanya pernah melihat content=None dan
        # tidak ada kontrak yang bisa lolos, seberapa benar pun pekerjaannya.
        try:
            record_evidence = getattr(session, "record_evidence", None)
            if callable(record_evidence):
                record_evidence(name, safe_args, res)
        except Exception as exc:                                    # noqa: BLE001
            quiet.swallowed("agent.registry.log_call_failed", exc)
        # Kanal rencana (§25) — argumen ASLI, karena rencana yang dijalankan
        # ulang besok tidak boleh berisi nilai bertopeng. Tetap no-op kecuali
        # dispatch memasang pengumpulnya.
        try:
            record_plan = getattr(session, "record_plan", None)
            if callable(record_plan):
                record_plan(name, args, res)
        except Exception as exc:                                    # noqa: BLE001
            quiet.swallowed("agent.registry.log_call_failed", exc)
    try:
        record = {
            "ts": time.time(), "tool": name,
            "session": getattr(session, "id", None),
            "args": _audit_args(name, args), "ok": res.ok,
            "error": _audit_error(name, res.error), "elapsed_ms": round(elapsed_s * 1000, 1),
        }
        with _log_lock:
            from jarvis.agent import tool_usage
            tool_usage.append_record(record)
    except Exception as exc:                                        # noqa: BLE001
        quiet.swallowed("agent.registry.log_call_failed", exc)


_SECRET_HINTS = ("key", "token", "password", "secret", "credential")
_DESKTOP_SAFE_AUDIT_ARGS = frozenset({"observation_id", "element_id"})
_DESKTOP_VISUAL_AUDIT_TOOLS = frozenset({"desktop_visual_observe"})


def _audit_args(name: str, args: dict) -> dict:
    """Keep desktop-safe and visual audit opaque; values/UI text never enter telemetry."""
    if str(name) in _DESKTOP_VISUAL_AUDIT_TOOLS:
        return {"action": str(name)}
    if str(name).startswith("desktop_safe") or str(name) == "desktop_observe":
        out = {key: str(args[key]) for key in _DESKTOP_SAFE_AUDIT_ARGS
               if key in args and str(args[key])}
        out["action"] = str(name)
        return out
    return _redact(args)


def _audit_error(name: str, error: str | None) -> str | None:
    if error and str(name) in _DESKTOP_VISUAL_AUDIT_TOOLS:
        return "desktop_visual_failed"
    if error and (str(name).startswith("desktop_safe") or str(name) == "desktop_observe"):
        return "desktop_safe_failed"
    return error


def _redact(args: dict) -> dict:
    out = {}
    for k, v in args.items():
        if any(h in k.lower() for h in _SECRET_HINTS):
            out[k] = "***"
        elif isinstance(v, str) and len(v) > 800:
            out[k] = v[:800] + "…"
        else:
            out[k] = v
    return out
