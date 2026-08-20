"""P2-C offline acceptance for document delivery handoff ownership."""
from __future__ import annotations

import asyncio
import threading

from jarvis.nlp.base import Context, Response
from jarvis.nlp.document_lifecycle import DocumentExplanation, DocumentLifecycle
from jarvis.ui.window_actions import CommandActionsMixin


_TEXT = "\n\n".join(
    f"Bagian {index}: dokumen sintetis untuk delivery handoff P2-C."
    for index in range(26)
)


class _CompletedTicket:
    completed = True

    async def wait_async(self):
        return "completed"


class _CancelledTicket:
    completed = False

    async def wait_async(self):
        return "cancelled"


def _explanation(identity: str = "p2-c-doc"):
    lifecycle = DocumentLifecycle(identity, "synthetic.txt", _text=_TEXT)
    token = lifecycle.begin_request()
    return lifecycle, DocumentExplanation(lifecycle, token)


def test_successful_handoff_submits_ordered_segments_once():
    lifecycle, explanation = _explanation()
    submitted: list[str] = []

    def submit(text: str):
        submitted.append(text)
        return _CompletedTicket()

    assert asyncio.run(explanation.deliver(submit)) is True
    assert submitted == lifecycle.plan_explanation()
    assert len(submitted) == lifecycle.segment_count()
    assert lifecycle.verified_count() == lifecycle.segment_count()
    assert lifecycle.has_verified_drain() is True
    assert explanation.next_submission() is None


def test_cancelled_handoff_keeps_cursor_and_resumes_same_segment():
    lifecycle, explanation = _explanation("p2-c-cancel")
    submitted: list[str] = []

    def submit(text: str):
        submitted.append(text)
        return _CancelledTicket()

    assert asyncio.run(explanation.deliver(submit)) is False
    assert submitted == [lifecycle.plan_explanation()[0]]
    assert lifecycle.first_unverified() == 0
    assert lifecycle.verified_count() == 0
    assert lifecycle.has_verified_drain() is False
    assert "belum terverifikasi" in lifecycle.interrupted_report()

    retry = explanation.next_submission()
    assert retry is not None
    assert retry[0] == 0
    assert retry[1] == submitted[0]


def test_delivery_exception_keeps_lifecycle_and_does_not_duplicate_submission():
    lifecycle, explanation = _explanation("p2-c-exception")
    submitted: list[str] = []

    def submit(text: str):
        submitted.append(text)
        raise RuntimeError("fake sink unavailable")

    assert asyncio.run(explanation.deliver(submit)) is False
    assert submitted == [lifecycle.plan_explanation()[0]]
    assert lifecycle.first_unverified() == 0
    assert lifecycle.interrupted_report()
    assert explanation.next_submission()[0] == 0


def test_ui_handoff_presents_one_terminal_interruption_without_duplicate_speech():
    lifecycle, explanation = _explanation("p2-c-ui")
    stage_events: list[tuple[str, str]] = []
    speech_submissions: list[str] = []
    restore_calls: list[bool] = []
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

    window = object.__new__(CommandActionsMixin)
    window.on_text_command = None
    window.on_speech_command = lambda text: (
        speech_submissions.append(text) or _CancelledTicket()
    )
    window.assistant = Assistant()
    window.orb = Orb()
    window._content_sig = Signal()
    window._state_sig = Signal()
    window._legacy_state = "IDLE"
    window.write_log = lambda _text: None
    window._restore_orb = lambda: (restore_calls.append(True), finished.set())

    window._chat("jelaskan dokumen")
    assert finished.wait(timeout=2) is True
    assert len(speech_submissions) == 1
    assert speech_submissions == [lifecycle.plan_explanation()[0]]
    assert len(stage_events) == 1
    assert stage_events[0][0] == "DocumentAnalysis"
    assert "terputus" in stage_events[0][1]
    assert len(restore_calls) == 1
    assert lifecycle.first_unverified() == 0
    assert lifecycle.has_verified_drain() is False
