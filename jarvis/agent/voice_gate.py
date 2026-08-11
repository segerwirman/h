"""Ordering gate between Gemini Live transcription and voice tool actions.

Gemini Live can emit a FunctionCall before input transcription is final.  The
gate stores only FunctionCall metadata until ``Transcription.finished`` is
true, then asks the shared tier router for the lane.  It does not touch audio,
VAD, STT, TTS, or playback.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator

from jarvis.agent.router import Route, Tier, classify


@dataclass(frozen=True)
class VoiceToolBatch:
    calls: tuple[Any, ...]
    text: str
    route: Route
    timed_out: bool = False


@dataclass
class _CallRecord:
    state: str
    result: Any = None


class FunctionCallHistory:
    """Bounded cross-reconnect lifecycle for non-empty FunctionCall IDs.

    A released batch is deliberately absent from this history. ``start`` is the
    first terminal boundary: once execution may have begun, reconnect must not
    repeat an external side effect. A completed response is cached before the
    network send and remains replayable until/after delivery.
    """

    def __init__(self, limit: int = 256) -> None:
        self._limit = max(1, int(limit))
        self._ids: deque[str] = deque()
        self._records: dict[str, _CallRecord] = {}

    def __contains__(self, call_id: object) -> bool:
        return self.state(call_id) != "new"

    def __iter__(self) -> Iterator[str]:
        return iter(tuple(self._ids))

    def state(self, call_id: object) -> str:
        value = str(call_id or "")
        if not value:
            return "new"
        record = self._records.get(value)
        return record.state if record is not None else "new"

    def result(self, call_id: object) -> Any:
        value = str(call_id or "")
        record = self._records.get(value)
        return record.result if record is not None else None

    def start(self, call_id: object) -> bool:
        value = str(call_id or "")
        if not value:
            return True
        if value in self._records:
            return False
        self._append(value, _CallRecord("in_flight"))
        return True

    def mark_unknown(self, call_id: object) -> None:
        value = str(call_id or "")
        record = self._records.get(value)
        if record is not None and record.state == "in_flight":
            record.state = "unknown"

    def store_result(self, call_id: object, result: Any) -> None:
        value = str(call_id or "")
        if not value:
            return
        record = self._records.get(value)
        if record is None:
            return
        if record.state == "cancelled":
            return
        record.state = "result_cached"
        record.result = result

    def mark_delivered(
        self,
        call_id: object,
        *,
        result: Any = None,
    ) -> None:
        value = str(call_id or "")
        if not value:
            return
        record = self._records.get(value)
        if record is None or record.state == "cancelled":
            return
        if result is not None:
            record.result = result
        record.state = "delivered"

    def cancel(self, call_id: object) -> None:
        value = str(call_id or "")
        if not value:
            return
        record = self._records.get(value)
        if record is None:
            self._append(value, _CallRecord("cancelled"))
        else:
            return

    def _append(self, call_id: str, record: _CallRecord) -> None:
        while len(self._ids) >= self._limit:
            self._records.pop(self._ids.popleft(), None)
        self._ids.append(call_id)
        self._records[call_id] = record


class VoiceToolGate:
    """Per-turn state machine that prevents actions on partial speech."""

    def __init__(
        self,
        classifier: Callable[[str, dict], Route] = classify,
        *,
        source: str = "voice",
        history: FunctionCallHistory | None = None,
    ) -> None:
        self._classifier = classifier
        self._source = source
        self._history = history or FunctionCallHistory()
        self.reset()

    def reset(self) -> None:
        self._parts: list[str] = []
        self._final_text: str | None = None
        self._route: Route | None = None
        self._pending: list[Any] = []
        self._pending_ids: set[str] = set()
        self._fallback_task = ""
        self._agent_claimed = False

    @property
    def route(self) -> Route | None:
        return self._route

    @property
    def text(self) -> str:
        if self._final_text is not None:
            return self._final_text
        return " ".join(self._parts).strip()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def add_transcription(
        self,
        text: str = "",
        *,
        finished: bool = False,
    ) -> VoiceToolBatch | None:
        part = str(text or "").strip()
        if part:
            self._parts.append(part)
        if not finished:
            return None

        self._final_text = " ".join(self._parts).strip()
        # A timeout decision is intentionally sticky: once a partial command
        # has defaulted to heavy, a late final marker must not downgrade it
        # and allow a legacy light action after the native handoff.
        if self._route is None:
            self._route = self._classify_final(self._final_text)
        return self._take_ready(timed_out=False)

    def queue_calls(self, calls: Iterable[Any]) -> VoiceToolBatch | None:
        incoming = []
        for call in calls:
            call_id = _call_id(call)
            if call_id and call_id in self._pending_ids:
                continue
            if call_id and self._history.state(call_id) == "cancelled":
                continue
            incoming.append(call)
            if call_id:
                self._pending_ids.add(call_id)
        if not self._fallback_task:
            self._fallback_task = _task_from_pending_calls(incoming) or ""
        self._pending.extend(incoming)
        return self._take_ready(timed_out=False)

    def cancel(self, ids: Iterable[str]) -> int:
        cancelled = {str(value) for value in ids if str(value or "")}
        before = len(self._pending)
        kept = []
        for call in self._pending:
            call_id = _call_id(call)
            if call_id in cancelled:
                self._pending_ids.discard(call_id)
            else:
                kept.append(call)
        self._pending = kept
        for call_id in cancelled:
            self._history.cancel(call_id)
        return before - len(self._pending)

    def timeout(self) -> VoiceToolBatch | None:
        """Release pending calls using the best transcript available.

        Gemini Live does not consistently emit ``finished=True`` before its
        FunctionCall.  Promoting every such turn to T2 made complete commands
        like "buka WhatsApp" fail whenever no heavy provider was configured.
        A non-empty transcript is therefore classified by the same
        deterministic router used at a normal final boundary.  Empty or
        unclassifiable input remains fail-closed on the heavy lane.
        """

        if self._route is None and (self._pending or self.text):
            self._final_text = self.text
            self._route = (
                self._classify_final(self._final_text)
                if self._final_text
                else _safe_heavy(
                    "voice transcription did not reach a final boundary"
                )
            )
        if not self._pending:
            return None
        return self._take_ready(timed_out=True)

    def claim_agent_task(self) -> str | None:
        """Return a heavy task once, regardless of FunctionCall batch count."""

        if (
            self._agent_claimed
            or self._route is None
            or self._route.tier < Tier.AGENT
        ):
            return None
        self._agent_claimed = True
        # Gemini Live kadang mengirim FunctionCall lebih awal daripada final
        # transcript. Bila transcript hilang, gunakan argumen web_search yang
        # eksplisit; jangan menampilkan kegagalan berita sebagai error STT.
        return self.text or self._fallback_task or _task_from_pending_calls(self._pending)

    def _classify_final(self, text: str) -> Route:
        try:
            route = self._classifier(text, {"source": self._source})
            if isinstance(route, Route):
                return route
        except Exception:  # noqa: BLE001 - voice boundary is never-raise
            pass
        return _safe_heavy("voice router failed; safe heavy default")

    def _take_ready(self, *, timed_out: bool) -> VoiceToolBatch | None:
        if not self._pending or self._route is None:
            return None
        calls = tuple(self._pending)
        self._pending.clear()
        self._pending_ids.clear()
        return VoiceToolBatch(calls, self.text, self._route, timed_out)


def _call_id(call: Any) -> str:
    return str(getattr(call, "id", "") or "")


def _task_from_pending_calls(calls: Iterable[Any]) -> str | None:
    """Bangun fallback task dari FunctionCall tanpa menebak isi speech.

    Hanya web_search dipulihkan karena query-nya data eksplisit dari tool call.
    Tool lain tanpa transcript tetap fail-closed agar tidak berubah menjadi aksi
    desktop yang tidak benar-benar diucapkan user.
    """
    for call in calls:
        if str(getattr(call, "name", "")) != "web_search":
            continue
        args = getattr(call, "args", {}) or {}
        if not isinstance(args, dict):
            continue
        query = str(args.get("query", "")).strip()
        if not query:
            continue
        mode = str(args.get("mode", "")).strip().lower()
        if mode == "news":
            return query if query.lower().startswith(("berita", "news")) \
                else f"cari berita {query}"
        return f"cari informasi tentang {query}"
    return None


def _safe_heavy(reason: str) -> Route:
    return Route(
        tier=Tier.AGENT,
        lane="heavy",
        model_profile="heavy",
        reason=reason,
        confidence=0.0,
    )


__all__ = ["FunctionCallHistory", "VoiceToolBatch", "VoiceToolGate"]
