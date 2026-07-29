"""Self-learning reflector (§4.4) — dijalankan asinkron setelah sesi selesai.

Ekstrak HANYA yang bernilai jangka panjang; kegagalan nyata menjadi memori
``reflective`` yang diinjeksi sebagai guardrail di sesi berikutnya.
"""
from __future__ import annotations

import json
import threading

from jarvis.core import log
from jarvis.agent import memory_store

_logger = log.get("agent.reflect")

_PROMPT = """Analisis sesi agent berikut. Ekstrak HANYA yang bernilai jangka panjang.
Abaikan basa-basi dan detail sekali pakai.

Transkrip (dipadatkan):
{transcript}

Tool yang dipakai: {tools}
Error yang terjadi: {errors}

Kembalikan JSON persis dengan bentuk:
{{
  "semantic":   [{{"content": "...", "importance": 0.0}}],
  "procedural": [{{"content": "...", "importance": 0.0}}],
  "reflective": [{{"content": "...", "importance": 0.0}}],
  "contradicts": []
}}

Aturan:
- Kosongkan array kalau memang tidak ada yang layak diingat. JANGAN mengarang.
- "reflective" hanya diisi kalau ada kegagalan NYATA yang bisa dihindari lain kali,
  ditulis sebagai instruksi (mis. "Jangan X sebelum Y").
- importance > 0.7 hanya untuk hal yang benar-benar penting.
- "contradicts" berisi id memori lama yang kini terbukti salah (jika disebut di konteks).
"""


def reflect_async(session) -> None:
    """Fire-and-forget — tidak pernah memblokir user."""
    threading.Thread(target=lambda: _safe_reflect(session), daemon=True,
                     name="agent-reflect").start()


def _safe_reflect(session) -> None:
    try:
        reflect(session)
    except Exception as e:                                   # noqa: BLE001
        _logger.warning("reflect.failed", error=str(e)[:150])


def reflect(session) -> dict | None:
    if session.turn_count < 2 or session.is_subagent:
        return None                                          # sesi remeh
    # §7.1 — slot auxiliary 'reflect': override provider/model bila diset,
    # default tetap provider utama (auto)
    from jarvis.agent import auxiliary
    cl = auxiliary.client_for("reflect")
    if not cl.available():
        return None

    transcript = "\n".join(
        f"{t['role']}: {str(t['content'])[:400]}"
        for t in session.transcript[-40:])
    tools = ", ".join(sorted({t["tool"] for t in session.tool_calls})) or "-"
    errors = "; ".join(session.errors[-10:]) or "-"

    raw = cl.generate(_PROMPT.format(transcript=transcript[:12_000],
                                     tools=tools, errors=errors),
                      json_mode=True)
    data = _parse_json(raw)
    if not isinstance(data, dict):
        return None

    from jarvis.agent.memory_access import resolve
    try:
        memory_scope = resolve(getattr(session, "execution_context", None))
    except PermissionError:
        return None
    written = 0
    for mem_id in data.get("contradicts") or []:
        if isinstance(mem_id, str) and mem_id:
            # Contradictions are only actionable within the same scoped store.
            memory_store.supersede(
                mem_id, scope=memory_scope.scope, owner=memory_scope.owner,
            )

    for mtype in ("semantic", "procedural", "reflective"):
        for item in data.get(mtype) or []:
            try:
                imp = float(item.get("importance", 0))
                content = str(item.get("content", "")).strip()
            except (AttributeError, TypeError, ValueError):
                continue
            if content and imp >= 0.3:                       # filter noise
                memory_store.write(
                    mtype, content, imp, source_session=session.id,
                    scope=memory_scope.scope, owner=memory_scope.owner,
                )
                written += 1
    _logger.info("reflect.done", session=session.id, written=written)
    return data


def _parse_json(raw: str):
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None
