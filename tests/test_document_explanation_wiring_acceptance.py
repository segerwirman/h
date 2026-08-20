"""P2-A offline acceptance for coordinator-to-explanation wiring."""
from __future__ import annotations

import asyncio
import threading

from jarvis.nlp.base import Context, Response
from jarvis.nlp.document import DocumentAnalysis
from jarvis.nlp.document_lifecycle import (
    COORDINATOR,
    DocumentExplanation,
    DocumentLifecycle,
)
from jarvis.ui.window_actions import CommandActionsMixin


_TEXT = "\n\n".join(
    f"Bagian {index}: isi dokumen sintetis untuk acceptance P2-A."
    for index in range(24)
)


def test_coordinator_result_exposes_one_document_explanation_owner(monkeypatch):
    """DocumentAnalysis returns the coordinator's active generation directly."""
    COORDINATOR.clear()
    path = "p2-a-synthetic-document.txt"
    lifecycle = COORDINATOR.open_text(path, _TEXT, source="test")
    monkeypatch.setattr("jarvis.nlp.document.llm.generate",
                        lambda *_args, **_kwargs: "tidak dipakai")

    response = asyncio.run(
        DocumentAnalysis().handle("jelaskan dokumen", Context(uploaded_file=path))
    )

    explanation = response.meta["document_explanation"]
    assert isinstance(explanation, DocumentExplanation)
    assert response.meta["document_lifecycle"] is lifecycle
    assert explanation.pending_segments() == lifecycle.plan_explanation()
    assert lifecycle.generation_token
    assert lifecycle.is_active(lifecycle.generation_token)


def test_delivery_success_publishes_each_coordinator_segment_once():
    """A successful fake sink drains each segment once and reaches terminal state."""
    lifecycle = DocumentLifecycle("p2-a-success", "synthetic.txt", _text=_TEXT)
    token = lifecycle.begin_request()
    explanation = DocumentExplanation(lifecycle, token)
    submitted: list[str] = []

    class Ticket:
        completed = True

        async def wait_async(self):
            return "completed"

    def submit(text: str):
        submitted.append(text)
        return Ticket()

    assert asyncio.run(explanation.deliver(submit)) is True
    assert submitted == lifecycle.plan_explanation()
    assert len(submitted) == lifecycle.segment_count()
    assert lifecycle.has_verified_drain() is True


def test_delivery_failure_keeps_result_visible_and_does_not_duplicate_terminal_sink():
    """A failed sink leaves the same first segment resumable without a result loss."""
    lifecycle = DocumentLifecycle("p2-a-failure", "synthetic.txt", _text=_TEXT)
    token = lifecycle.begin_request()
    explanation = DocumentExplanation(lifecycle, token)
    submitted: list[str] = []

    class FailedTicket:
        completed = False

        async def wait_async(self):
            return "aborted"

    assert asyncio.run(
        explanation.deliver(lambda text: submitted.append(text) or FailedTicket())
    ) is False
    assert submitted == [lifecycle.plan_explanation()[0]]
    assert lifecycle.first_unverified() == 0
    assert lifecycle.has_verified_drain() is False

    resumed = explanation.next_submission()
    assert resumed is not None
    assert resumed[0] == 0
    assert resumed[1] == submitted[0]


def test_chat_uses_one_explanation_delivery_and_reports_failure_once():
    """The UI seam consumes the coordinator explanation, not a raw transcript."""
    lifecycle = DocumentLifecycle("p2-a-chat", "synthetic.txt", _text=_TEXT)
    token = lifecycle.begin_request()
    explanation = DocumentExplanation(lifecycle, token)
    stage_events: list[tuple[str, str]] = []
    speech_submissions: list[str] = []
    finished = threading.Event()

    class Orb:
        def set_state(self, _state):
            pass

    class Signal:
        def emit(self, source, text):
            stage_events.append((source, text))

    class Assistant:
        ctx = Context(uploaded_file="synthetic.txt")

        def handle_blocking(self, _text):
            return Response(
                "Penjelasan dokumen siap.",
                show_on_stage=True,
                source="DocumentAnalysis",
                meta={
                    "document_explanation": explanation,
                    "document_lifecycle": lifecycle,
                },
            )

    class FailedTicket:
        completed = False

        async def wait_async(self):
            return "aborted"

    window = object.__new__(CommandActionsMixin)
    window.on_text_command = None
    window.on_speech_command = lambda text: (
        speech_submissions.append(text) or FailedTicket()
    )
    window.assistant = Assistant()
    window.orb = Orb()
    window._content_sig = Signal()
    window._state_sig = Signal()
    window._legacy_state = "IDLE"
    window.write_log = lambda _text: None
    window._restore_orb = lambda: finished.set()

    window._chat("jelaskan dokumen")
    assert finished.wait(timeout=2) is True
    assert speech_submissions == [lifecycle.plan_explanation()[0]]
    assert len(stage_events) == 1
    assert "terputus" in stage_events[0][1]
    assert lifecycle.first_unverified() == 0
    assert lifecycle.has_verified_drain() is False
