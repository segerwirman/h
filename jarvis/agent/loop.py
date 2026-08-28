"""Agentic loop (jarvis.md §6) — planner + executor sampai tugas selesai.

    plan → llm.chat(tools) → eksekusi tool (read-only paralel, penulis
    serial) → hasil kembali ke messages → ulangi → jawaban akhir.

Loop tidak pernah raise: kegagalan LLM/tool menjadi pesan yang dilaporkan
lewat adapter. Setelah selesai, reflector belajar secara asinkron (§4.4).
"""
from __future__ import annotations

import asyncio
import datetime
import json
import platform
from dataclasses import dataclass
from pathlib import Path

from jarvis.core import config, latency, log
from jarvis.agent import context as ctx
from jarvis.agent import llm_client, memory_store, model_routing, registry, \
    skills
from jarvis.core import quiet
from jarvis.agent.adapters.base import Adapter, NullAdapter
from jarvis.agent.base import ToolResult
from jarvis.agent.reflect import reflect_async
from jarvis.agent.session import Session

_logger = log.get("agent.loop")

_DEFAULT_PERSONA = (
    "Kamu adalah JARVIS — asisten pribadi otonom milik user, sopan, "
    "efisien, memanggil user \"sir\", menjawab dalam bahasa user "
    "(default Indonesia).")


@dataclass
class RunResult:
    ok: bool
    text: str = ""
    cancelled: bool = False
    iterations: int = 0
    session_id: str = ""


def _persona() -> str:
    """Identitas Jarvis dari persona yang SUDAH ada di repo (§7) — file
    core/prompt.txt dipakai apa adanya, tidak ditulis ulang."""
    try:
        path = Path(config.resolve_path(
            str(config.get("agent.persona_file", "core/prompt.txt"))))
        text = path.read_text(encoding="utf-8").strip()
        return text or _DEFAULT_PERSONA
    except Exception:                                        # noqa: BLE001
        return _DEFAULT_PERSONA


def _system_prompt(task: str, adapter_name: str, *, execution_context=None) -> str:
    try:
        template = (Path(__file__).parent / "prompts" / "system.md") \
            .read_text(encoding="utf-8")
    except Exception:                                        # noqa: BLE001
        template = "{persona}\n{reflective_memories}\n{retrieved_memories}"

    from jarvis.agent.memory_access import resolve
    memory_scope = resolve(execution_context)
    memories = memory_store.search(
        task, limit=8, max_tokens=800,
        scope=memory_scope.scope, owner=memory_scope.owner,
    )
    mem_block = "\n".join(
        f"- [{m['type']}] {m['content']}" for m in memories) or "(kosong)"
    lessons = memory_store.get_reflective(
        min_importance=0.6, scope=memory_scope.scope, owner=memory_scope.owner,
    )
    lesson_block = "\n".join(f"- {m['content']}" for m in lessons) \
        or "(belum ada)"

    return template.format(
        persona=_persona(),
        reflective_memories=lesson_block,
        retrieved_memories=mem_block,
        skill_list=skills.prompt_block(),
        os=f"{platform.system()} {platform.release()}",
        datetime=datetime.datetime.now().strftime("%A, %d %B %Y %H:%M"),
        adapter_name=adapter_name,
        cwd=str(config.base_dir()),
    )


def _heavy_unconfigured_msg(task: str) -> str:
    """Pesan degrade §3.2 — jujur, bisa diucapkan TTS, language-aware."""
    try:
        from jarvis.agent.interaction import detect_language
        lang = detect_language(task)
    except Exception:                                        # noqa: BLE001
        lang = "id"
    if lang == "en":
        return ("The model for heavy tasks is not set up yet — please "
                "connect a heavy provider in Settings (gear icon)")
    return ("Model untuk tugas berat belum diatur — silakan hubungkan "
            "provider berat di Settings (ikon gear)")


def _session_tool_turn(name: str, arguments: dict, result: ToolResult) -> str:
    """Persist desktop-safe tool outcomes as opaque metadata only."""
    safe_name = str(name)
    if safe_name == "desktop_observe" or safe_name.startswith("desktop_safe"):
        parts = [
            f"{key}={str(arguments[key])}"
            for key in ("observation_id", "element_id")
            if arguments.get(key)
        ]
        suffix = f" [{', '.join(parts)}]" if parts else ""
        status = "ok" if result.ok else "desktop_safe_failed"
        return f"{safe_name} → {status}{suffix}"[:500]
    return f"{safe_name} → {'ok' if result.ok else result.error}"[:500]


async def run(task: str, adapter: Adapter | None = None,
              session: Session | None = None,
              allowed_tools: list[str] | None = None,
              max_iterations: int | None = None,
              model_profile: str = "heavy", context=None,
              bg_task=None) -> RunResult:
    """``bg_task`` — ``jarvis.agent.tasks.Task`` opsional (AUDIT §8.3).

    Bila diberikan, loop melaporkan progres ke registry dan menghormati
    pembatalan kooperatif. Parameter sengaja OPSIONAL: seluruh pemanggil lama
    (cron, run_sync, sub-agent, tes) tidak berubah perilakunya.
    """
    adapter = adapter or NullAdapter()
    session = session or Session(task=task, adapter_name=adapter.name)
    if not session.conversation_context:
        # This is the only bounded handoff material a child agent receives.
        # Tool outputs and full transcripts remain in the parent session.
        session.conversation_context = f"Tugas induk aktif: {task[:1200]}"
    max_iter = max_iterations or int(config.get("agent.max_iterations", 50))

    # §3 — agent loop adalah Lane B: model dari routing.heavy, BUKAN kunci
    # Gemini lane ringan. Sub-agent (delegate) dan cron ikut jalur yang sama.
    if model_profile == "heavy":
        cl, heavy_name, heavy_reason = model_routing.heavy_resolution()
        if cl is None:
            msg = _heavy_unconfigured_msg(task)
            _logger.warning("agent.run.heavy_unconfigured",
                            detail=heavy_reason[:160])
            model_routing.publish_provider_event(
                "heavy", "", "tidak ada provider berat terkonfigurasi",
                "unavailable")
            await _safe_send(adapter, msg)
            return RunResult(ok=False, text=msg, session_id=session.id)
        _logger.info("agent.run.model", profile="heavy", provider=heavy_name)
        model_routing.publish_provider_event(
            "heavy", heavy_name, heavy_reason, "selected")
    else:
        cl, heavy_name = model_routing.light_client(), ""
    tried_providers = {heavy_name} if heavy_name else set()
    if not cl.available():
        msg = (_heavy_unconfigured_msg(task) if model_profile == "heavy"
               else "Provider LLM agent belum dikonfigurasi. Buka Settings "
                    "(ikon gear) → pilih provider dan isi API key/base URL.")
        await _safe_send(adapter, msg)
        return RunResult(ok=False, text=msg, session_id=session.id)

    # Sub-agent tidak boleh menelurkan pekerjaan latar baru: delegate_task
    # sudah dilarang sejak awal, dan task_start akan membuka jalur rekursi
    # yang sama lewat pintu berbeda.
    exclude = ["delegate_task", "task_start"] if session.is_subagent else None
    # PARITY v2 §5.8 — tool dari grup yang user matikan TIDAK masuk schema.
    # Snapshot sekali di awal run: toggle di tengah run tidak berpengaruh
    # ("Changes apply to new sessions").
    try:
        from jarvis.agent import toolgroups
        disabled_tools = toolgroups.disabled_tool_names()
        if disabled_tools:
            exclude = sorted(set(exclude or []) | disabled_tools)
    except Exception as e:                                   # noqa: BLE001
        _logger.warning("agent.toolgroups_unavailable", error=str(e)[:100])
    if allowed_tools is None and context is None:
        try:
            from jarvis.agent.tool_selection import select_tool_names

            allowed_tools = select_tool_names(task, registry.all_tools())
            if allowed_tools is not None:
                _logger.info(
                    "agent.tools.shortlisted",
                    count=len(allowed_tools),
                    names=allowed_tools,
                )
        except Exception as e:                               # noqa: BLE001
            _logger.warning(
                "agent.tool_selection_failed", error=str(e)[:100]
            )
    tool_schemas = registry.schemas(allowed=allowed_tools, exclude=exclude, context=context) \
        if context is not None else registry.schemas(allowed=allowed_tools, exclude=exclude)

    messages: list[dict] = [
        {"role": "system", "content": _system_prompt(
            task, adapter.name, execution_context=context)},
        {"role": "user", "content": task},
    ]
    session.record_turn("user", task)

    final_text = ""
    iterations = 0
    _escalated: set[str] = set()      # peringatan batas hanya sekali per run
    for iterations in range(1, max_iter + 1):
        # ① batal kooperatif — antar iterasi (AUDIT §8.3)
        if session.cancelled or _cancelled(bg_task):
            await _safe_send(adapter, "Tugas dibatalkan.")
            session.finish("dibatalkan", ok=False)
            return RunResult(ok=False, cancelled=True,
                             iterations=iterations, session_id=session.id)

        # ② progres — satu-satunya sumber angka bagi UI/suara
        _task_update(bg_task, iteration=iterations, step="berpikir…")

        # §17 — eskalasi sebelum menabrak dinding, bukan sesudahnya.
        if await _iteration_escalation(adapter, session, iterations,
                                       max_iter, _escalated):
            final_text = _limit_report(session, iterations, max_iter,
                                       stopped_by_user=True)
            await _safe_send(adapter, final_text)
            session.finish(final_text, ok=False)
            reflect_async(session)
            return RunResult(ok=False, text=final_text, iterations=iterations,
                             session_id=session.id)

        # §24 — dua penanda, bukan satu: "setup" adalah segala yang terjadi
        # SEBELUM model dipanggil (persona, memory search + embedding, schema
        # tool), dan "first_llm" adalah durasi panggilan itu sendiri.
        # Satu penanda saja membuat keduanya tercampur dan tidak bisa
        # ditindaklanjuti.
        latency.mark(session.id, "setup")
        resp = await asyncio.to_thread(cl.chat, messages, tool_schemas)
        latency.mark(session.id, "first_llm")
        # §3.1 — rantai fallback berat: 402/kredit habis/timeout (retry
        # transient internal llm_client sudah tandas) → provider berikutnya.
        while (not resp.ok and model_profile == "heavy"
               and model_routing.failover_error(resp.error)):
            nxt = model_routing.next_heavy_client(tried_providers)
            if nxt is None:
                break
            cl, failover_name = nxt
            tried_providers.add(failover_name)
            _logger.warning("agent.run.failover", provider=failover_name,
                            error=str(resp.error)[:140])
            model_routing.publish_provider_event(
                "heavy", failover_name,
                "eligible quota, rate-limit, or timeout failure", "failover")
            try:
                await adapter.progress(
                    f"⚠ provider berat bermasalah — beralih ke {failover_name}")
            except Exception as exc:                                # noqa: BLE001
                quiet.swallowed("agent.loop.run_failed", exc)
            resp = await asyncio.to_thread(cl.chat, messages, tool_schemas)
        if not resp.ok:
            msg = f"LLM gagal: {resp.error}"
            session.errors.append(msg)
            await _safe_send(adapter, "Maaf, terjadi gangguan pada model — "
                                      + str(resp.error)[:160])
            session.finish(msg, ok=False)
            reflect_async(session)
            return RunResult(ok=False, text=msg, iterations=iterations,
                             session_id=session.id)

        if not resp.tool_calls:
            final_text = (resp.content or "").strip() or "Selesai."
            session.record_turn("assistant", final_text)
            await _safe_send(adapter, final_text)
            break

        # pesan assistant dengan tool_calls (format kanonik OpenAI)
        messages.append({
            "role": "assistant",
            "content": resp.content,
            "tool_calls": [{
                "id": tc.id, "type": "function",
                "function": {"name": tc.name,
                             "arguments": json.dumps(tc.arguments,
                                                     ensure_ascii=False)},
            } for tc in resp.tool_calls],
        })
        if resp.content:
            session.record_turn("assistant", resp.content)

        results = await _execute_calls(resp.tool_calls, adapter, session,
                                       context, bg_task)
        latency.mark(session.id, "first_tool")
        for tc, res in zip(resp.tool_calls, results):
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": res.for_llm()})
            session.record_turn("tool", _session_tool_turn(tc.name, tc.arguments, res))

        if ctx.over_threshold(messages):
            # §3.3 — kompresi konteks adalah side-task murah: selalu model
            # ringan (override slot auxiliary.compression tetap dihormati).
            messages = await asyncio.to_thread(
                ctx.compact, messages, model_routing.compression_client())
    else:
        final_text = _limit_report(session, iterations, max_iter)
        await _safe_send(adapter, final_text)
        session.finish(final_text, ok=False)
        reflect_async(session)
        return RunResult(ok=False, text=final_text, iterations=iterations,
                         session_id=session.id)

    session.finish(final_text, ok=True)
    reflect_async(session)                    # self-learning, tidak memblokir
    # Curator (§8) — maintenance lifecycle skill learned; gated interval,
    # best-effort, tidak pernah mengganggu hasil run
    try:
        from jarvis.agent import curator
        curator.maybe_run_async()
    except Exception as exc:                                        # noqa: BLE001
        quiet.swallowed("agent.loop.run_failed", exc)
    _logger.info("agent.run_done", session=session.id,
                 iterations=iterations, chars=len(final_text))
    return RunResult(ok=True, text=final_text, iterations=iterations,
                     session_id=session.id)


def _limit_report(session, iterations: int, max_iter: int,
                  *, stopped_by_user: bool = False) -> str:
    """Laporan jujur saat loop berhenti tanpa menuntaskan tugas (S-5).

    Bentuk lama menjanjikan "Progres tersimpan di sesi". Sesi memang tersimpan,
    tetapi TIDAK ADA jalur yang bisa melanjutkannya — janji itu ditulis oleh
    kode kita sendiri, bukan oleh model. Diganti fakta yang bisa diperiksa:
    berapa iterasi terpakai, tool apa yang benar-benar berhasil, dan apa yang
    gagal.
    """
    calls = list(getattr(session, "tool_calls", []) or [])
    done: list[str] = []
    for entry in calls:
        name = str(entry.get("tool", "")).strip()
        if name and entry.get("ok") and name not in done:
            done.append(name)
    failed = [str(entry.get("tool", "")) for entry in calls
              if not entry.get("ok")]

    head = ("Saya hentikan atas permintaan Anda"
            if stopped_by_user else
            f"Batas {max_iter} iterasi tercapai sebelum tugas tuntas")
    parts = [f"{head} (terpakai {iterations})."]
    if done:
        parts.append("Yang sudah berjalan: " + ", ".join(done[:8]) + ".")
    else:
        parts.append("Belum ada langkah yang berhasil diselesaikan.")
    if failed:
        parts.append(f"{len(failed)} pemanggilan tool gagal.")
    parts.append("Tugas ini tidak dilanjutkan otomatis — "
                 "minta lagi bila ingin saya teruskan.")
    return " ".join(parts)


async def _iteration_escalation(adapter, session, iterations: int,
                                max_iter: int, warned: set) -> bool:
    """Peringatkan mendekati batas; tawarkan berhenti pada run interaktif.

    Return ``True`` bila user memilih berhenti. Tidak menjawab BUKAN berarti
    berhenti — pekerjaan lanjut sampai batas, karena memblokir tugas gara-gara
    user sedang tidak di meja adalah kegagalan yang lebih buruk.
    """
    if "warned" in warned or max_iter < 3:
        return False
    threshold = max(1, int(max_iter * 0.8))
    if iterations < threshold:
        return False
    warned.add("warned")
    try:
        await adapter.progress(
            f"⚠ mendekati batas iterasi ({iterations}/{max_iter})")
    except Exception as exc:                                        # noqa: BLE001
        quiet.swallowed("agent.loop.iteration_escalation_failed", exc)
    if not bool(getattr(adapter, "interactive", False)):
        return False
    if not bool(config.get("agent.iteration_escalation.enabled", True)):
        return False
    try:
        answer = await adapter.ask(
            f"Sudah {iterations} dari {max_iter} iterasi dan tugas belum "
            "tuntas. Lanjutkan sampai batas, atau hentikan sekarang dan "
            "laporkan yang sudah ada?",
            ["Lanjutkan", "Hentikan"])
    except Exception:                                        # noqa: BLE001
        return False
    return str(answer or "").strip().casefold() in (
        "hentikan", "berhenti", "stop", "batal", "cancel")


def _cancelled(bg_task) -> bool:
    """Batal kooperatif — tidak pernah melempar meski registry bermasalah."""
    try:
        return bg_task is not None and bg_task.cancel.is_set()
    except Exception:                                        # noqa: BLE001
        return False


def _task_update(bg_task, **fields) -> None:
    """Progres ke registry → BUS → UI. Best-effort: kegagalan pelaporan tidak
    boleh menjatuhkan tugas yang sedang berjalan."""
    if bg_task is None:
        return
    try:
        from jarvis.agent.tasks import REGISTRY
        REGISTRY.update(bg_task.id, **fields)
    except Exception as exc:                                        # noqa: BLE001
        quiet.swallowed("agent.loop.task_update_failed", exc)


def _mark_pending_tool(bg_task, tool_name: str, tools: dict) -> None:
    """Write the pending-tool marker (NAME only, never arguments)."""
    if bg_task is None:
        return
    try:
        from jarvis.agent.tasks import REGISTRY
        read_only = bool(tools.get(tool_name) is not None
                         and tools[tool_name].read_only)
        REGISTRY.ledger_pending_tool(bg_task.id, tool_name,
                                     read_only=read_only)
    except Exception as exc:                                    # noqa: BLE001
        quiet.swallowed("agent.loop.pending_tool_failed", exc)


def _clear_pending_tool(bg_task) -> None:
    """Clear the pending marker after a known outcome."""
    if bg_task is None:
        return
    try:
        from jarvis.agent.tasks import REGISTRY
        REGISTRY.ledger_pending_tool(bg_task.id, "", read_only=None)
    except Exception as exc:                                    # noqa: BLE001
        quiet.swallowed("agent.loop.clear_pending_tool_failed", exc)


def _release_dynamic_resources(held) -> None:
    """Release per-tool locks before any process-local human handoff wait."""
    if not held:
        return
    from jarvis.agent.tasks import REGISTRY

    REGISTRY.release_held(held)


async def _finish_captcha_handoff(result, session, bg_task):
    """Keep the opaque handoff outside ToolResult and model-visible state."""
    try:
        from jarvis.agent.captcha_handoff import OWNER

        outcome = await OWNER.suspend_if_staged(session, bg_task)
    except Exception as exc:                                    # noqa: BLE001
        quiet.swallowed("agent.loop.captcha_handoff_failed", exc)
        return ToolResult.fail("desktop_handoff_cancelled")
    if outcome is None:
        return result
    if outcome == "resumed":
        return ToolResult.success(
            {"status": "captcha_handoff_completed"},
            display="CAPTCHA handoff selesai; observasi desktop baru diperlukan",
        )
    return ToolResult.fail("desktop_handoff_cancelled")


def _short_args(arguments) -> str:
    try:
        items = list(dict(arguments or {}).values())
    except Exception:                                        # noqa: BLE001
        return ""
    text = " ".join(str(v) for v in items[:2])
    return " ".join(text.split())[:60]


async def _acquire_for(bg_task, tool_name: str):
    """Kunci resource eksklusif satu tool, tanpa memblokir event loop.

    Lapis dinamis §8.2: saat submit kita belum tahu tool mana yang dipilih
    model, jadi inilah titik yang benar-benar mencegah dua agent berebut
    mouse. ``None`` = dibatalkan selagi menunggu.
    """
    if bg_task is None:
        return []
    try:
        from jarvis.agent import toolgroups
        from jarvis.agent.tasks import REGISTRY
        needed = toolgroups.resources_for_tool(tool_name)
    except Exception:                                        # noqa: BLE001
        return []
    if not needed:
        return []
    while True:
        if _cancelled(bg_task):
            return None
        got = REGISTRY.try_acquire(bg_task, needed)
        if got is not None:
            return got
        await asyncio.sleep(0.02)


async def _execute_calls(tool_calls, adapter, session, context, bg_task=None):
    """Read-only → paralel; ada penulis → semuanya serial berurutan (aman)."""
    tools = registry.all_tools()

    async def _one(tc):
        # ③ batal kooperatif — sebelum setiap tool call (AUDIT §8.3)
        if _cancelled(bg_task):
            return ToolResult.fail("dibatalkan sebelum tool dijalankan")
        _task_update(bg_task, step=f"{tc.name} → {_short_args(tc.arguments)}")
        try:
            await adapter.progress(f"🔧 {tc.name}")
        except Exception as exc:                                    # noqa: BLE001
            quiet.swallowed("agent.loop.one_failed", exc)
        held = await _acquire_for(bg_task, tc.name)
        if held is None:
            return ToolResult.fail("dibatalkan sebelum tool dijalankan")
        # Durable pending-tool marker (Fase 38 item 7): record the tool NAME
        # (never its arguments) and read-only classification just before
        # execution.  Cleared immediately after a known outcome below, so a
        # process death between the two writes leaves a visible pending marker
        # instead of a silently-replayed or falsely-safe task.
        _mark_pending_tool(bg_task, tc.name, tools)
        try:
            result = await registry.execute(
                tc.name, tc.arguments, adapter, session, context)
        finally:
            _clear_pending_tool(bg_task)
            _release_dynamic_resources(held)
        result = await _finish_captcha_handoff(result, session, bg_task)
        if tc.name == "image_generate" and result.ok:
            paths = result.meta.get("paths", [])
            if isinstance(paths, list):
                for path in paths[:2]:
                    try:
                        await adapter.send_image(str(path), str(result.content or ""))
                    except Exception as exc:                        # noqa: BLE001
                        quiet.swallowed("agent.loop.one_failed", exc)
        return result

    all_read_only = all(
        (tools.get(tc.name) is not None and tools[tc.name].read_only)
        for tc in tool_calls)
    if all_read_only and len(tool_calls) > 1:
        return await asyncio.gather(*[_one(tc) for tc in tool_calls])
    results = []
    for tc in tool_calls:
        results.append(await _one(tc))
    return results


async def _safe_send(adapter, text: str) -> None:
    try:
        await adapter.send(text)
    except Exception as e:                                   # noqa: BLE001
        _logger.warning("agent.adapter_send_failed", error=str(e)[:100])
