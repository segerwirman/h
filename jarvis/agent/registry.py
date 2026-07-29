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

_logger = log.get("agent.registry")

_tools: dict[str, Tool] | None = None
_lock = threading.Lock()
_log_lock = threading.Lock()


def all_tools(refresh: bool = False) -> dict[str, Tool]:
    global _tools
    with _lock:
        if _tools is None or refresh:
            _tools = _discover()
        return dict(_tools)


def get(name: str) -> Tool | None:
    return all_tools().get(name)


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
        except Exception:                                    # noqa: BLE001
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
            exclude: list[str] | None = None, context=None) -> list[dict]:
    """Schema gaya OpenAI; context membatasi schema pada capability terizinkan."""
    context_allowed = None
    if context is not None:
        from jarvis.agent.capabilities import REGISTRY as capability_registry
        context_allowed = set(capability_registry.exposed_tool_names(context))
    out = []
    for name, tool in sorted(all_tools().items()):
        if allowed is not None and name not in allowed:
            continue
        if context_allowed is not None and name not in context_allowed:
            continue
        if exclude and name in exclude:
            continue
        out.append({"type": "function", "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.json_schema()}})
    return out


async def execute(name: str, args: dict, adapter=None,
                  session=None, context=None,
                  _approved_request_id: str = "") -> ToolResult:
    """Jalankan satu tool dengan seluruh guardrail. Tidak pernah raise."""
    tool = get(name)
    if tool is None:
        return ToolResult.fail(f"tool tidak dikenal: {name}")

    args = dict(args or {})
    args.pop("_raw", None)
    policy_approval_granted = False

    if context is not None:
        from jarvis.agent.capabilities import REGISTRY as capability_registry
        from jarvis.agent import policy
        descriptor = capability_registry.descriptor_for_tool(name)
        if descriptor is None:
            return ToolResult.fail("capability tidak terdaftar untuk execution context")
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
                        name, args, adapter, session, context,
                        _approved_request_id=request.id),
                )
                return ToolResult.fail(
                    f"approval diperlukan sebelum tool dijalankan ({request.id})")
        if not decision.allowed and not (decision.needs_approval and approved_id):
            return ToolResult.fail(f"policy menolak tool: {decision.reason}")

    # konfirmasi tool berbahaya — via adapter; sesi cron menolak otomatis
    try:
        needs = tool.needs_confirmation(**args)
    except Exception:                                        # noqa: BLE001
        needs = tool.requires_confirmation
    if needs and not policy_approval_granted:
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
            res = ToolResult.fail("aksi butuh konfirmasi user dan tidak "
                                  "disetujui — jangan ulangi tanpa diminta")
            _log_call(name, args, res, 0.0, session)
            return res

    # tool yang menyatakan wants_context menerima sesi+adapter aktif
    # (todo per-sesi, clarify, delegate, snapshot kamera via UI adapter)
    if getattr(tool, "wants_context", False):
        args["_session"] = session
        args["_adapter"] = adapter
        args["_context"] = context

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


def _log_call(name: str, args: dict, res: ToolResult, elapsed_s: float,
              session) -> None:
    _logger.info("agent.tool", tool=name, ok=res.ok,
                 elapsed_ms=round(elapsed_s * 1000, 1),
                 error=(res.error or "")[:120] or None)
    if session is not None:
        try:
            session.record_tool(name, args, res, elapsed_s)
        except Exception:                                    # noqa: BLE001
            pass
    try:
        record = {
            "ts": time.time(), "tool": name,
            "session": getattr(session, "id", None),
            "args": _redact(args), "ok": res.ok,
            "error": res.error, "elapsed_ms": round(elapsed_s * 1000, 1),
        }
        with _log_lock:
            from jarvis.agent import tool_usage
            tool_usage.append_record(record)
    except Exception:                                        # noqa: BLE001
        pass


_SECRET_HINTS = ("key", "token", "password", "secret", "credential")


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
