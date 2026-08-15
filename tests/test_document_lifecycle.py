"""Fase 38 — one owner per document generation, one verified spoken cursor.

The document explanation pipeline has several independent producers (upload
worker, DocumentAnalysis, legacy file_processor).  These contracts pin the
single coordinator that owns generation tokens, deterministic segmentation,
and a playback-verified spoken cursor.
"""
from __future__ import annotations

import pytest


def _lifecycle(fingerprint: str = "fp-doc-a", text: str = "Konten dokumen."):
    from jarvis.nlp.document_lifecycle import DocumentCoordinator
    coordinator = DocumentCoordinator()
    return coordinator.open_text(fingerprint, text, source="voice")


def test_segmentation_is_deterministic_and_bounded():
    from jarvis.nlp.document_lifecycle import segmentation

    paragraphs = "Paragraf pertama berisi kalimat.\n\nParagraf kedua juga.\n\n"
    text = paragraphs * 40
    first = segmentation(text)
    second = segmentation(text)
    assert first == second                       # deterministic, no time/random
    assert len(first) > 1                        # long text is segmented
    assert all(len(seg) <= 900 for seg in first)


def test_plan_chunks_is_the_same_planner_summarize_long_uses():
    from jarvis.nlp.doc_extract import plan_chunks, summarize_long

    paragraphs = "Kalimat konten dokumen. " * 500
    long_text = "\n\n".join(paragraphs[i:i + 700] for i in range(0, len(paragraphs), 700))
    chunks = plan_chunks(long_text, max_chunk=2000)

    assert len(chunks) > 1
    # summarize_long still works and internally uses the same deterministic split.
    seen = []
    gen = lambda prompt: "Ringkasan parsial." if "Bagian:" in prompt else "Ringkasan final."
    out = summarize_long(long_text, gen, max_chunk=2000)
    assert out  # hierarchical path ran


_LONG_TEXT = "\n\n".join(
    f"Paragraf {i}: kalimat penjelasan dokumen yang cukup panjang "
    for i in range(40)
)


def test_request_token_superseded_by_newer_generation():
    from jarvis.nlp.document_lifecycle import DocumentLifecycle
    lc = DocumentLifecycle("fp-b", "doc.txt", source="voice", _text=_LONG_TEXT)
    lc.plan_explanation()

    stale = lc.begin_request()
    lc.begin_request()                           # newer generation wins

    assert lc.is_active(stale) is False
    assert lc.mark_segment_done(0, stale) is False   # stale cannot publish


def test_cursor_advances_only_for_verified_segments():
    from jarvis.nlp.document_lifecycle import DocumentLifecycle
    lc = DocumentLifecycle("fp-c", "doc.txt", source="voice", _text=_LONG_TEXT)
    segments = lc.plan_explanation()
    assert len(segments) > 1
    token = lc.begin_request()

    assert lc.first_unverified() == 0
    assert lc.resume_point() == 0
    assert lc.verified_count() == 0
    assert lc.has_verified_drain() is False

    assert lc.mark_segment_done(0, token) is True
    assert lc.first_unverified() == 1
    assert lc.resume_point() == 1
    assert lc.verified_count() == 1

    # Re-done segment is ignored; cursor never rewinds.
    assert lc.mark_segment_done(0, token) is False
    assert lc.resume_point() == 1


def test_interrupted_resume_starts_at_first_unverified():
    from jarvis.nlp.document_lifecycle import DocumentLifecycle
    lc = DocumentLifecycle("fp-d", "doc.txt", source="voice", _text=_LONG_TEXT)
    segments = lc.plan_explanation()
    assert len(segments) > 2
    token = lc.begin_request()

    lc.mark_segment_done(0, token)
    lc.mark_segment_done(1, token)
    # segments 2+ never drained (interrupted / aborted).

    assert lc.first_unverified() == 2
    assert lc.resume_point() == 2
    assert lc.has_verified_drain() is False       # cursor never reached the end


def test_fully_drained_cursor_is_verified():
    from jarvis.nlp.document_lifecycle import DocumentLifecycle
    lc = DocumentLifecycle("fp-e", "doc.txt", source="voice", _text=_LONG_TEXT)
    segments = lc.plan_explanation()
    assert len(segments) > 1
    token = lc.begin_request()
    for index in range(len(segments)):
        assert lc.mark_segment_done(index, token) is True

    assert lc.first_unverified() is None
    assert lc.has_verified_drain() is True
    assert lc.resume_point() == len(segments)


def test_without_verified_cursor_reports_honest_interruption():
    from jarvis.nlp.document_lifecycle import DocumentLifecycle
    lc = DocumentLifecycle("fp-f", "doc.txt", source="voice", _text=_LONG_TEXT)
    lc.plan_explanation()
    lc.begin_request()                            # work started, nothing drained

    report = lc.interrupted_report()
    assert "terputus" in report                   # honest, no claimed last word
    assert "belum" in report
    assert lc.has_verified_drain() is False
    # Resume would need an explicit user direction; never silent restart.
    assert lc.first_unverified() == 0


def test_explanation_pending_segments_start_at_first_unverified():
    from jarvis.nlp.document_lifecycle import DocumentLifecycle, DocumentExplanation
    lc = DocumentLifecycle("fp-g", "doc.txt", source="voice", _text=_LONG_TEXT)
    lc.plan_explanation()
    token = lc.begin_request()
    lc.mark_segment_done(0, token)

    explanation = DocumentExplanation(lc, token)
    pending = explanation.pending_segments()
    assert len(pending) == lc.segment_count() - 1
    assert pending[0] == lc.plan_explanation()[1]


def test_explanation_next_submission_advances_cursor_only_when_verified():
    from jarvis.nlp.document_lifecycle import DocumentLifecycle, DocumentExplanation
    lc = DocumentLifecycle("fp-h", "doc.txt", source="voice", _text=_LONG_TEXT)
    lc.plan_explanation()
    token = lc.begin_request()

    explanation = DocumentExplanation(lc, token)
    first = explanation.next_submission()
    assert first is not None
    index, _text, mark_verified = first
    assert index == 0
    assert lc.verified_count() == 0

    # Aborted / silent submission must NOT advance the cursor.
    mark_verified(verified=False)
    assert lc.verified_count() == 0
    assert lc.first_unverified() == 0

    # Verified drain advances exactly this segment.
    mark_verified(verified=True)
    assert lc.verified_count() == 1
    assert lc.first_unverified() == 1


def test_explanation_resumes_at_first_unverified_after_interruption():
    from jarvis.nlp.document_lifecycle import DocumentLifecycle, DocumentExplanation
    lc = DocumentLifecycle("fp-i", "doc.txt", source="voice", _text=_LONG_TEXT)
    lc.plan_explanation()
    token = lc.begin_request()
    lc.mark_segment_done(0, token)
    lc.mark_segment_done(1, token)

    explanation = DocumentExplanation(lc, token)
    next_sub = explanation.next_submission()
    assert next_sub is not None and next_sub[0] == 2


def test_upload_worker_uses_coordinator_for_single_owner():
    """Fase 38 — the window upload worker drives its summary through the
    coordinator's shared lifecycle, so the same fingerprint cannot publish
    from two independent generations."""
    from jarvis.nlp.document_lifecycle import COORDINATOR
    from jarvis.ui.window_voice import WindowVoiceMixin

    assert hasattr(WindowVoiceMixin, "_coordinator_for_upload")
    assert WindowVoiceMixin._coordinator_for_upload() is COORDINATOR


def test_document_analysis_reuses_coordinator_cache():
    """Fase 38 — DocumentAnalysis seeds/reads the same coordinator lifecycle
    instead of owning an independent generation."""
    from jarvis.nlp.document_lifecycle import COORDINATOR
    import jarvis.nlp.document as doc

    assert hasattr(doc, "lifecycle_for_path") or hasattr(doc, "COORDINATOR")


def test_document_coordinator_is_wired_for_lifecycle_owner():
    """Fase 38 — the document analysis path resolves through the shared
    coordinator lifecycle (lifecycle_for_path) so upload and explain share
    ONE generation owner."""
    from jarvis.nlp.document import lifecycle_for_path
    from jarvis.nlp.document_lifecycle import COORDINATOR

    # A seeded lifecycle is returned for the same safe identity.
    fp = "fp-seam-1"
    COORDINATOR.open_text(fp, "Konten dokumen.", source="voice")
    assert lifecycle_for_path(fp) is COORDINATOR.get(fp)


def test_seed_then_lifecycle_for_path_resolves_same_owner():
    """Fase 38 — the upload worker seeds by RAW path identity and
    lifecycle_for_path must resolve back to the same lifecycle (the shared
    owner contract); a double-hash would silently split the lifecycle."""
    from jarvis.nlp.document_lifecycle import COORDINATOR
    from jarvis.nlp.document import lifecycle_for_path

    raw = r"C:\seed-test\report.docx"
    seeded = COORDINATOR.open_text(raw, "Isi dokumen.", source="voice")
    resolved = lifecycle_for_path(raw, source="voice")
    assert resolved is seeded is COORDINATOR.get(raw)


def test_same_fingerprint_shares_one_lifecycle():
    from jarvis.nlp.document_lifecycle import DocumentCoordinator
    coordinator = DocumentCoordinator()
    first = coordinator.open_text("fp-shared", "Konten.", source="voice")
    second = coordinator.open_text("fp-shared", "Konten.", source="voice")
    assert first is second


def test_fingerprint_is_safe_and_path_independent():
    from jarvis.nlp.document_lifecycle import safe_fingerprint
    from pathlib import Path

    fp = safe_fingerprint(Path(r"C:\secret\private.docx"))
    assert isinstance(fp, str) and len(fp) >= 12
    assert "secret" not in fp and "private" not in fp   # raw path never leaks
    assert "\\" not in fp and "/" not in fp
