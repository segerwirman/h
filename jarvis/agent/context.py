"""Manajemen context window — estimasi token + kompaksi turn lama (§6).

Estimasi kasar 1 token ≈ 4 karakter — cukup untuk ambang 70%; presisi tidak
dibutuhkan karena kompaksi hanya soal "kapan", bukan "berapa tepat".
"""
from __future__ import annotations

import json

from jarvis.core import config, log

_logger = log.get("agent.context")


def estimate_tokens(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        try:
            total += len(json.dumps(m, ensure_ascii=False, default=str)) // 4
        except Exception:                                    # noqa: BLE001
            total += len(str(m)) // 4
    return total


def over_threshold(messages: list[dict]) -> bool:
    window = int(config.get("agent.context_window_tokens", 128_000))
    ratio = float(config.get("agent.context_threshold", 0.7))
    return estimate_tokens(messages) > window * ratio


def compact(messages: list[dict], llm) -> list[dict]:
    """Ringkas turn lama menjadi satu pesan; pertahankan system prompt +
    ``keep_last`` turn terakhir utuh. ``llm`` = LLMClient (blocking)."""
    keep_last = int(config.get("agent.compact_keep_last", 10))
    if len(messages) <= keep_last + 2:
        return messages

    system = [m for m in messages[:1] if m.get("role") == "system"]
    body = messages[len(system):]
    head, tail = body[:-keep_last], body[-keep_last:]
    # jangan memutus pasangan assistant(tool_calls) ↔ tool di perbatasan
    while tail and tail[0].get("role") == "tool":
        head.append(tail.pop(0))
    if not head:
        return messages

    lines = []
    for m in head:
        role = m.get("role", "?")
        if role == "assistant" and m.get("tool_calls"):
            names = [tc.get("function", {}).get("name", "?")
                     for tc in m["tool_calls"]]
            lines.append(f"assistant memanggil tool: {', '.join(names)}")
        content = m.get("content")
        if content:
            text = content if isinstance(content, str) else \
                " ".join(p.get("text", "") for p in content
                         if isinstance(p, dict))
            lines.append(f"{role}: {text[:600]}")
    digest = "\n".join(lines)[:16_000]

    summary = ""
    try:
        summary = llm.generate(
            "Ringkas riwayat kerja agent berikut menjadi poin-poin padat "
            "(fakta yang ditemukan, aksi yang sudah dilakukan, keputusan, "
            "state saat ini). Maksimal 300 kata.\n\n" + digest)
    except Exception as e:                                   # noqa: BLE001
        _logger.warning("context.compact_llm_failed", error=str(e)[:100])
    if not summary:
        summary = digest[:2000]

    compacted = system + [{
        "role": "user",
        "content": ("[RINGKASAN KONTEKS — turn sebelumnya dipadatkan]\n"
                    + summary),
    }] + tail
    _logger.info("context.compacted", before=len(messages),
                 after=len(compacted))
    return compacted
