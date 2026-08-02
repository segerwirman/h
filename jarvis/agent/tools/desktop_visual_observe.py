"""Desktop-local visual summary only; never issues UI action authority."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel

from jarvis.agent.base import Tool, ToolResult
from jarvis.automation.visual_observe import VisualObserveService


class _NoParams(BaseModel):
    pass


_REPORT_KEYS = frozenset({"visual_observation_id", "brightness", "complexity", "dominant_tone"})
_REPORT_DOMAINS = {
    "brightness": frozenset({"dark", "balanced", "bright"}),
    "complexity": frozenset({"low", "medium", "high"}),
    "dominant_tone": frozenset({"warm", "neutral", "cool"}),
}


def _safe_report(report) -> dict | None:
    """Reject, never strip, analyzer output outside the non-actionable contract."""
    if not isinstance(report, dict) or set(report) != _REPORT_KEYS:
        return None
    observation_id = str(report.get("visual_observation_id", ""))
    if not observation_id or len(observation_id) > 64:
        return None
    if any(report.get(key) not in allowed for key, allowed in _REPORT_DOMAINS.items()):
        return None
    return {key: report[key] for key in ("visual_observation_id", "brightness", "complexity", "dominant_tone")}


class DesktopVisualObserve(Tool):
    name = "desktop_visual_observe"
    description = (
        "Ambil ringkasan visual desktop lokal yang sangat terbatas dan non-actionable. "
        "Tidak mengembalikan gambar, OCR, teks UI, koordinat, selector, atau referensi aksi."
    )
    params_schema = _NoParams
    read_only = True
    wants_context = True
    timeout_s = 15

    def __init__(self, *, service: VisualObserveService | None = None):
        self._service = service or VisualObserveService()

    async def run(self, _session=None, _context=None, **_) -> ToolResult:
        from jarvis.agent.policy import desktop_safe_context_error

        error = desktop_safe_context_error(
            _context, capability="desktop_safe.desktop_visual_observe", risk="low",
            runtime_session=_session,
        )
        if error:
            return ToolResult.fail(error)
        session_id = str(getattr(_session, "id", "") or "")
        if not session_id:
            return ToolResult.fail("desktop_safe_context_session_required")
        try:
            report = await asyncio.to_thread(self._service.observe, session_id=session_id)
        except Exception:
            return ToolResult.fail("desktop_visual_failed")
        safe_report = _safe_report(report)
        if safe_report is None:
            return ToolResult.fail("desktop_visual_failed")
        return ToolResult.success(safe_report, display="ringkasan visual desktop lokal tersedia")


__all__ = ["DesktopVisualObserve"]
