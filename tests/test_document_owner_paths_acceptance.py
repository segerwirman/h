"""P2-B offline acceptance for shared document-owner entrypoints."""
from __future__ import annotations

import asyncio

from jarvis.nlp.base import Context
from jarvis.nlp.document import DocumentAnalysis, lifecycle_for_path
from jarvis.nlp.document_lifecycle import (
    COORDINATOR,
    DocumentExplanation,
    DocumentLifecycle,
)
from jarvis.nlp import summarize
from jarvis.ui.window_voice import WindowVoiceMixin


_TEXT = "\n\n".join(
    f"Paragraf {index}: dokumen sintetis untuk owner acceptance P2-B."
    for index in range(28)
)


def test_upload_analysis_and_summary_resolve_one_coordinator_lifecycle(
        monkeypatch):
    """All three entrypoints resolve the same coordinator-owned object."""
    COORDINATOR.clear()
    path = "p2-b-shared-owner.txt"
    window = object.__new__(WindowVoiceMixin)
    window.write_log = lambda _text: None
    window._seed_document_coordinator(path, _TEXT)

    lifecycle = COORDINATOR.get(path)
    assert lifecycle is not None
    assert WindowVoiceMixin._coordinator_for_upload() is COORDINATOR
    assert lifecycle_for_path(path, source="DocumentAnalysis") is lifecycle

    monkeypatch.setattr(
        "jarvis.nlp.document.llm.generate",
        lambda *_args, **_kwargs: "Jawaban sintetis.",
    )
    analysis_response = asyncio.run(
        DocumentAnalysis().handle("apa isi dokumen?", Context(uploaded_file=path))
    )
    assert analysis_response.meta["file"] == path

    captured: dict[str, object] = {}

    def fake_summary(text, instruction, language):
        captured.update(text=text, instruction=instruction, language=language)
        return "Ringkasan sintetis."

    monkeypatch.setattr(summarize, "summarize_text", fake_summary)
    summary_response = asyncio.run(
        summarize.AutomaticSummarization().handle(
            "ringkas dokumen", Context(uploaded_file=path, language="id")
        )
    )

    assert summary_response.meta["document_lifecycle"] is lifecycle
    assert captured["text"] == "\n\n".join(lifecycle.plan_explanation())
    assert captured["language"] == "id"


def test_stale_generation_cannot_publish_or_move_shared_cursor():
    """A newer request invalidates the old producer without cursor movement."""
    lifecycle = DocumentLifecycle("p2-b-stale", "synthetic.txt", _text=_TEXT)
    lifecycle.plan_explanation()
    stale = lifecycle.begin_request()
    current = lifecycle.begin_request()

    assert lifecycle.is_active(stale) is False
    assert lifecycle.is_active(current) is True
    assert lifecycle.mark_segment_done(0, stale) is False
    assert lifecycle.verified_count() == 0
    assert lifecycle.first_unverified() == 0

    explanation = DocumentExplanation(lifecycle, stale)
    assert explanation.next_submission() is not None
    index, _text, mark_verified = explanation.next_submission()
    assert index == 0
    assert mark_verified(verified=True) is False
    assert lifecycle.verified_count() == 0


def test_same_fingerprint_does_not_create_private_lifecycle_or_duplicate_explanation():
    """Repeated owner resolution reuses one lifecycle and one active generation."""
    coordinator = type(COORDINATOR)()
    first = coordinator.open_text("p2-b-duplicate", _TEXT, source="voice")
    second = coordinator.open_text("p2-b-duplicate", _TEXT, source="summary")
    assert first is second

    first_token = first.begin_request()
    second_token = first.begin_request()
    assert first_token != second_token
    assert first.generation_token == second_token
    assert first.is_active(first_token) is False
    assert first.is_active(second_token) is True


def test_cancelled_delivery_is_honest_and_resumable_without_duplicate_submit():
    """A failed fake ticket preserves the same first segment for retry."""
    lifecycle = DocumentLifecycle("p2-b-cancel", "synthetic.txt", _text=_TEXT)
    token = lifecycle.begin_request()
    explanation = DocumentExplanation(lifecycle, token)
    submitted: list[str] = []

    class CancelledTicket:
        completed = False

        async def wait_async(self):
            return "cancelled"

    def submit(text: str):
        submitted.append(text)
        return CancelledTicket()

    assert asyncio.run(explanation.deliver(submit)) is False
    assert submitted == [lifecycle.plan_explanation()[0]]
    assert lifecycle.first_unverified() == 0
    assert lifecycle.has_verified_drain() is False

    retry = explanation.next_submission()
    assert retry is not None
    assert retry[0] == 0
    assert retry[1] == submitted[0]
