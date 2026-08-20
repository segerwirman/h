"""P2-D offline acceptance for document read failure boundaries."""
from __future__ import annotations

import asyncio

from jarvis.nlp.base import Context
from jarvis.nlp.document import DocumentAnalysis
from jarvis.nlp.document_lifecycle import (
    DocumentCoordinator,
    DocumentExplanation,
)


_TEXT = "\n\n".join(
    f"Bagian {index}: dokumen sintetis valid untuk retry P2-D."
    for index in range(18)
)


def test_successful_synthetic_read_creates_one_coordinator_lifecycle(
        monkeypatch):
    """A successful fake reader seeds one reusable lifecycle owner."""
    coordinator = DocumentCoordinator()
    path = "p2-d-readable.txt"
    monkeypatch.setattr(
        "jarvis.nlp.document_lifecycle.COORDINATOR", coordinator
    )
    monkeypatch.setattr("jarvis.nlp.document.read_document", lambda _path: _TEXT)

    from jarvis.nlp.document_lifecycle import lifecycle_for_path

    first = lifecycle_for_path(path, source="test")
    second = lifecycle_for_path(path, source="retry")
    assert first is not None
    assert first is second
    assert coordinator.get(path) is first
    assert first.plan_explanation()


def test_empty_or_unsupported_read_returns_honest_no_lifecycle(monkeypatch):
    """Empty fake reader output cannot create an explanation owner."""
    coordinator = DocumentCoordinator()
    monkeypatch.setattr(
        "jarvis.nlp.document_lifecycle.COORDINATOR", coordinator
    )
    monkeypatch.setattr("jarvis.nlp.document.read_document", lambda _path: "")

    from jarvis.nlp.document_lifecycle import lifecycle_for_path

    assert lifecycle_for_path("p2-d-empty.pdf", source="test") is None
    assert coordinator.get("p2-d-empty.pdf") is None

    response = asyncio.run(
        DocumentAnalysis().handle(
            "jelaskan dokumen", Context(uploaded_file="p2-d-empty.pdf")
        )
    )
    assert "tidak dapat membaca" in response.text.casefold()
    assert "document_explanation" not in response.meta


def test_reader_failure_does_not_create_partial_lifecycle_or_fake_cursor(
        monkeypatch):
    """Reader exception remains an honest no-owner state."""
    coordinator = DocumentCoordinator()
    monkeypatch.setattr(
        "jarvis.nlp.document_lifecycle.COORDINATOR", coordinator
    )

    def failing_reader(_path):
        raise OSError("synthetic reader failure")

    monkeypatch.setattr("jarvis.nlp.document.read_document", failing_reader)
    from jarvis.nlp.document_lifecycle import lifecycle_for_path

    assert lifecycle_for_path("p2-d-failure.docx", source="test") is None
    assert coordinator.get("p2-d-failure.docx") is None
    assert not any(
        isinstance(value, DocumentExplanation)
        for value in coordinator._lifecycles.values()
    )


def test_retry_after_failure_creates_fresh_valid_owner_without_stale_state(
        monkeypatch):
    """A later successful read starts clean and owns a fresh generation."""
    coordinator = DocumentCoordinator()
    monkeypatch.setattr(
        "jarvis.nlp.document_lifecycle.COORDINATOR", coordinator
    )
    from jarvis.nlp.document_lifecycle import lifecycle_for_path

    monkeypatch.setattr("jarvis.nlp.document.read_document", lambda _path: "")
    assert lifecycle_for_path("p2-d-retry.txt", source="test") is None
    assert coordinator.get("p2-d-retry.txt") is None

    monkeypatch.setattr(
        "jarvis.nlp.document.read_document", lambda _path: _TEXT
    )
    lifecycle = lifecycle_for_path("p2-d-retry.txt", source="retry")
    assert lifecycle is not None
    assert lifecycle.first_unverified() == 0
    assert lifecycle.verified_count() == 0
    token = lifecycle.begin_request()
    assert lifecycle.is_active(token) is True
    assert lifecycle.first_unverified() == 0
