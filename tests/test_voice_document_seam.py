"""RED-first contracts for the voice document seam (Fase 43 runtime).

Covers the two runtime failures found in ``logs/jarvis.log``:
- Gemini Live FunctionCall ``file_processor`` carries a basename that the
  FROZEN ``main.py::_execute_tool`` never resolves, so
  ``actions.file_processor`` returns ``File not found``.
- An explicit spoken "jelaskan dokumen ini" on the Live lane never reaches
  the document coordinator; it becomes a single legacy ``file_processor``
  analysis with no per-segment verified cursor.

The seam ``jarvis/integrations/voice_document.py`` is the smallest
non-FROZEN interception point: it wraps ``JarvisLive._execute_tool`` so
loaded-file identity resolves basenames, and explicit explanation requests
route through ``DocumentLifecycle``/``DocumentExplanation`` with drain-aware
speech tickets and structured ``voice.document.*`` telemetry.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from pathlib import Path

import pytest

from jarvis.nlp.document_lifecycle import COORDINATOR, lifecycle_for_path
from jarvis.integrations import voice_document

_LONG_TEXT = (
    "Sebuah dokumen uji untuk penjelasan berurutan. " * 40
)
_VIDEO_TEXT = "\n\n".join(
    "Transkrip video uji yang dibangun dari audio. " * 25
    for _ in range(4)
)


@pytest.fixture(autouse=True)
def _clean_coordinator():
    COORDINATOR.clear()
    yield
    COORDINATOR.clear()


def _submitter(returned_status: str, submitted: list[str]):
    class Ticket:
        def __init__(self, status):
            self._status = status
            self.completed = status == "completed"
            self.aborted = status == "aborted"

        async def wait_async(self):
            return self._status

    def submit(text: str):
        submitted.append(text)
        return Ticket(returned_status)

    return submit


def _fake_live(window=None, *, traces=None) -> SimpleNamespace:
    win = window if window is not None else SimpleNamespace()
    return SimpleNamespace(
        ui=SimpleNamespace(_win=win, current_file=getattr(win, "_current_file", None)),
        _traces=traces if traces is not None else [],
    )


def _fake_trace(live) -> None:
    live._traces = []

    def _trace(event, **fields):
        live._traces.append((event, fields))

    live._trace = _trace


def _completed_ticket_fc(**args):
    return SimpleNamespace(id="fc-1", name="file_processor", args=dict(args))


async def _lane_ready(_live) -> bool:
    return True


# ── 1. Basename → loaded full path ────────────────────────────────────────


def test_resolve_loaded_path_matches_basename_of_loaded_file(tmp_path):
    loaded = str(tmp_path / "report.pdf")
    live = _fake_live(SimpleNamespace(_current_file=loaded))

    assert voice_document.resolve_loaded_path(live, "report.pdf") == loaded
    assert voice_document.resolve_loaded_path(live, str(loaded)) == loaded


def test_resolve_loaded_path_rejects_ambiguous_and_unmatched_basename(tmp_path):
    a = str(tmp_path / "dup.pdf")
    b = str(tmp_path / "sub" / "dup.pdf")
    # Two genuinely loaded identities with the SAME basename must be ambiguous.
    live = SimpleNamespace(
        ui=SimpleNamespace(
            _win=SimpleNamespace(_current_file=a),
            assistant=SimpleNamespace(
                ctx=SimpleNamespace(uploaded_file=b)),
        ),
    )
    assert voice_document.loaded_file_candidates(live) == [a, b]
    assert voice_document.resolve_loaded_path(live, "dup.pdf") is None
    assert voice_document.resolve_loaded_path(live, "") is None

    # An arbitrary basename that is NOT loaded must never trigger disk search.
    assert voice_document.resolve_loaded_path(live, "not_loaded.pdf") is None


def test_install_wraps_execute_tool_and_rewrites_basename(monkeypatch, tmp_path):
    loaded = str(tmp_path / "report.pdf")
    calls: list[dict] = []

    class Live:
        def __init__(self, window):
            self.ui = SimpleNamespace(_win=window, current_file=window._current_file)

        async def _execute_tool(self, fc):
            calls.append(dict(getattr(fc, "args", None) or {}))
            return "legacy-ran"

    module = SimpleNamespace(JarvisLive=Live)
    assert voice_document.install(module) is True
    assert voice_document.install(module) is False  # idempotent

    live = Live(SimpleNamespace(_current_file=loaded))
    fc = _completed_ticket_fc(file_path="report.pdf", action="summarize")
    result = asyncio.run(live._execute_tool(fc))

    assert result == "legacy-ran"
    assert calls == [{"file_path": loaded, "action": "summarize"}]


# ── 2. Explicit "jelaskan dokumen" routes to the coordinator ───────────────


def test_explanation_request_routes_to_coordinator_lifecycle(monkeypatch, tmp_path):
    path = str(tmp_path / "seed.pdf")
    COORDINATOR.open_text(path, _LONG_TEXT, source="voice", title="seed.pdf")
    lifecycle = lifecycle_for_path(path)
    assert lifecycle is not None

    submitted: list[str] = []
    live = _fake_live(SimpleNamespace(
        _current_file=path,
        on_speech_command=_submitter("completed", submitted),
    ))
    _fake_trace(live)
    monkeypatch.setattr(voice_document, "_await_lane", _lane_ready)

    payload = asyncio.run(voice_document.route_document_explanation(
        live, path, {"instruction": "jelaskan dokumen ini"}))

    assert submitted == lifecycle.plan_explanation()
    assert lifecycle.has_verified_drain() is True
    assert payload["silent"] is True
    assert "selesai dibacakan" in payload["result"]

    events = [name for name, _ in live._traces]
    assert "voice.document.request" in events
    assert "voice.document.completed" in events
    req = next(fields for name, fields in live._traces
               if name == "voice.document.request")
    assert req["generation"]
    assert req["cursor_before"] == 0
    done = next(fields for name, fields in live._traces
                if name == "voice.document.completed")
    assert done["segments_verified"] == lifecycle.segment_count()


def test_resume_lanjutkan_penjelasan_starts_at_first_unverified(monkeypatch, tmp_path):
    path = str(tmp_path / "seed.pdf")
    COORDINATOR.open_text(path, _LONG_TEXT, source="voice")
    lifecycle = lifecycle_for_path(path)

    # First request: first segment verified, second aborted.
    first_submitted: list[str] = []
    live = _fake_live(SimpleNamespace(
        _current_file=path,
        on_speech_command=_submitter("aborted", first_submitted),
    ))
    monkeypatch.setattr(voice_document, "_await_lane", _lane_ready)
    asyncio.run(voice_document.route_document_explanation(
        live, path, {"instruction": "jelaskan dokumen ini"}))
    assert lifecycle.first_unverified() == 0

    # Second request "lanjutkan penjelasan" with a completed submitter must
    # deliver every remaining segment from the verified cursor onward.
    second_submitted: list[str] = []
    live2 = _fake_live(SimpleNamespace(
        _current_file=path,
        on_speech_command=_submitter("completed", second_submitted),
    ))
    _fake_trace(live2)
    payload = asyncio.run(voice_document.route_document_explanation(
        live2, path, {"instruction": "lanjutkan penjelasan"}))

    assert second_submitted == lifecycle.plan_explanation()
    assert lifecycle.has_verified_drain() is True
    assert payload["silent"] is True


# ── 3. Aborted ticket keeps first segment unverified ──────────────────────


def test_aborted_ticket_keeps_first_unverified_and_reports_interruption(monkeypatch, tmp_path):
    path = str(tmp_path / "seed.pdf")
    COORDINATOR.open_text(path, _LONG_TEXT, source="voice")
    lifecycle = lifecycle_for_path(path)

    submitted: list[str] = []
    live = _fake_live(SimpleNamespace(
        _current_file=path,
        on_speech_command=_submitter("aborted", submitted),
    ))
    _fake_trace(live)
    monkeypatch.setattr(voice_document, "_await_lane", _lane_ready)

    payload = asyncio.run(voice_document.route_document_explanation(
        live, path, {"instruction": "jelaskan dokumen ini"}))

    assert submitted == lifecycle.plan_explanation()[:1]
    assert lifecycle.first_unverified() == 0
    assert "terputus" in payload["result"]

    events = [name for name, _ in live._traces]
    assert "voice.document.interrupted" in events
    interrupted = next(fields for name, fields in live._traces
                       if name == "voice.document.interrupted")
    assert interrupted["first_unverified"] == 0
    assert interrupted["generation"]


# ── 4. Honest routing decisions ────────────────────────────────────────────


def test_lane_busy_does_not_advance_cursor(monkeypatch, tmp_path):
    path = str(tmp_path / "seed.pdf")
    COORDINATOR.open_text(path, _LONG_TEXT, source="voice")
    lifecycle = lifecycle_for_path(path)
    submitted: list[str] = []
    live = _fake_live(SimpleNamespace(
        _current_file=path,
        on_speech_command=_submitter("completed", submitted),
    ))
    _fake_trace(live)

    async def _lane_busy(_live):
        return False

    monkeypatch.setattr(voice_document, "_await_lane", _lane_busy)
    payload = asyncio.run(voice_document.route_document_explanation(
        live, path, {"instruction": "jelaskan dokumen ini"}))

    assert submitted == []
    assert lifecycle.first_unverified() == 0
    assert "sibuk" in payload["result"]
    assert [name for name, _ in live._traces] == ["voice.document.lane_busy"]


def test_unreadable_document_reports_honestly(monkeypatch, tmp_path):
    path = str(tmp_path / "unreadable.pdf")  # not seeded, no readable content
    live = _fake_live(SimpleNamespace(_current_file=path))
    monkeypatch.setattr(voice_document, "_await_lane", _lane_ready)

    payload = asyncio.run(voice_document.route_document_explanation(
        live, path, {"instruction": "jelaskan dokumen ini"}))
    assert payload["silent"] is True
    assert "tidak dapat" in payload["result"] or "tidak memiliki" in payload["result"]


# ── 5. Video explain ───────────────────────────────────────────────────────


def test_video_explain_builds_lifecycle_from_transcript(monkeypatch, tmp_path):
    video = str(tmp_path / "clip.mp4")
    monkeypatch.setattr(voice_document, "_transcribe_video",
                        lambda _path: _VIDEO_TEXT)

    submitted: list[str] = []
    live = _fake_live(SimpleNamespace(
        _current_file=video,
        on_speech_command=_submitter("completed", submitted),
    ))
    _fake_trace(live)
    monkeypatch.setattr(voice_document, "_await_lane", _lane_ready)

    payload = asyncio.run(voice_document.route_video_explanation(
        live, video, {"instruction": "jelaskan video ini"}))

    assert len(submitted) > 1
    assert payload["silent"] is True
    assert "selesai dibacakan" in payload["result"]
    events = [name for name, _ in live._traces]
    assert "voice.document.video.request" in events
    assert "voice.document.completed" in events


def test_video_explain_without_transcript_is_honest(monkeypatch, tmp_path):
    video = str(tmp_path / "silent.mp4")
    monkeypatch.setattr(voice_document, "_transcribe_video", lambda _path: "")

    submitted: list[str] = []
    live = _fake_live(SimpleNamespace(
        _current_file=video,
        on_speech_command=_submitter("completed", submitted),
    ))
    _fake_trace(live)
    monkeypatch.setattr(voice_document, "_await_lane", _lane_ready)

    payload = asyncio.run(voice_document.route_video_explanation(
        live, video, {"instruction": "jelaskan video ini"}))

    assert submitted == []
    assert "tidak mengklaim menjelaskan" in payload["result"]
    assert payload["silent"] is True
    assert "voice.document.video.no_transcript" in [n for n, _ in live._traces]


def test_video_explain_missing_ffmpeg_is_honest(monkeypatch, tmp_path):
    video = str(tmp_path / "clip.mp4")
    submitted: list[str] = []
    live = _fake_live(SimpleNamespace(
        _current_file=video,
        on_speech_command=_submitter("completed", submitted),
    ))
    _fake_trace(live)
    monkeypatch.setattr(voice_document, "_await_lane", _lane_ready)
    monkeypatch.setattr(voice_document, "_ffmpeg_available", lambda: False)

    payload = asyncio.run(voice_document.route_video_explanation(
        live, video, {"instruction": "jelaskan video ini"}))
    assert submitted == []
    assert payload["silent"] is True


# ── 6. File suffix routing decisions ──────────────────────────────────────


def _write_seed(tmp_path, name="seed.pdf") -> str:
    path = str(tmp_path / name)
    Path(path).write_text(_LONG_TEXT, encoding="utf-8")
    return path


def test_dispatch_ignores_non_explanation_document_actions(monkeypatch, tmp_path):
    """A plain 'summarize' call must NOT be hijacked into a read-aloud."""
    path = _write_seed(tmp_path)
    COORDINATOR.open_text(path, _LONG_TEXT, source="voice")
    live = _fake_live(SimpleNamespace(_current_file=path))

    monkeypatch.setattr(voice_document, "_await_lane", _lane_ready)
    result = asyncio.run(voice_document._route_file_processor(
        live, _completed_ticket_fc(file_path="seed.pdf", action="summarize")))
    assert result is None  # falls through to the legacy file_processor


def test_dispatch_routes_explicit_document_explanation(monkeypatch, tmp_path):
    path = _write_seed(tmp_path)
    COORDINATOR.open_text(path, _LONG_TEXT, source="voice")
    submitted: list[str] = []
    live = _fake_live(SimpleNamespace(
        _current_file=path,
        on_speech_command=_submitter("completed", submitted),
    ))
    _fake_trace(live)
    monkeypatch.setattr(voice_document, "_await_lane", _lane_ready)

    response = asyncio.run(voice_document._route_file_processor(
        live, _completed_ticket_fc(file_path="seed.pdf",
                                   instruction="jelaskan dokumen ini")))
    assert response is not None
    assert getattr(response, "response", {}).get("silent") is True
    assert "selesai dibacakan" in getattr(response, "response", {}).get("result", "")
