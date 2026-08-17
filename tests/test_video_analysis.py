"""RED-first contracts for bounded long-video analysis."""
from __future__ import annotations

import json
import threading
import time

import pytest


def test_video_limits_and_reason_codes_are_versioned():
    from jarvis.agent.media.video_analysis import (
        VIDEO_REASON_CODES,
        VideoAnalysisLimits,
        VideoAnalysisReport,
    )

    limits = VideoAnalysisLimits()
    assert limits.max_duration_s > 0
    assert limits.max_frames > 0
    assert limits.max_candidates <= 20
    assert "video_size_limit" in VIDEO_REASON_CODES
    report = VideoAnalysisReport.failed("video_size_limit", "clip.mp4")
    assert report.schema_version == "video-analysis.v1"
    assert report.reason_code == "video_size_limit"
    assert report.as_dict()["candidates"] == []


def test_loaded_video_identity_rejects_unmatched_when_required(tmp_path):
    from jarvis.agent.media.video_analysis import VideoAnalysisError, resolve_video_source

    loaded = tmp_path / "clip.mp4"
    loaded.write_bytes(b"x")
    with pytest.raises(VideoAnalysisError) as exc:
        resolve_video_source(
            "other.mp4", loaded_paths=[str(loaded)], allow_unloaded=False
        )
    assert exc.value.code == "video_path_not_loaded"


def test_loaded_video_identity_rejects_ambiguous_basename(tmp_path):
    from jarvis.agent.media.video_analysis import resolve_video_source

    first = tmp_path / "one" / "clip.mp4"
    second = tmp_path / "two" / "clip.mp4"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"1")
    second.write_bytes(b"2")

    with pytest.raises(Exception) as exc:
        resolve_video_source(
            "clip.mp4", loaded_paths=[str(first), str(second)]
        )
    assert getattr(exc.value, "code", "") == "video_ambiguous_identity"


def test_frame_and_audio_boundaries_are_deterministic():
    from jarvis.agent.media.video_analysis import (
        VideoAnalysisLimits,
        audio_chunk_boundaries,
        frame_timestamps,
    )

    limits = VideoAnalysisLimits(
        audio_chunk_s=120, frame_interval_s=30, max_frames=4
    )
    assert audio_chunk_boundaries(305, limits) == [
        (0.0, 120.0),
        (120.0, 240.0),
        (240.0, 305.0),
    ]
    assert frame_timestamps(95, limits) == [0.0, 30.0, 60.0, 90.0]


def test_candidate_validation_ranking_and_overlap_deduplication():
    from jarvis.agent.media.video_analysis import (
        VideoAnalysisLimits,
        rank_candidates,
    )

    candidates = rank_candidates(
        [
            {"start_s": 10, "end_s": 40, "hook": "low", "score": 0.4},
            {"start_s": 12, "end_s": 35, "hook": "high", "score": 0.9},
            {"start_s": 80, "end_s": 90, "hook": "late", "score": 0.8},
            {"start_s": -1, "end_s": 5, "hook": "invalid", "score": 1.0},
        ],
        duration_s=100,
        limits=VideoAnalysisLimits(max_candidates=5, max_clip_duration_s=60),
    )
    assert [item.hook for item in candidates] == ["high", "late"]
    assert all(0 <= item.start_s < item.end_s <= 100 for item in candidates)


def test_malformed_vision_json_is_omitted_not_invented(tmp_path):
    from jarvis.agent.media.video_analysis import VideoAnalyzer

    analyzer = VideoAnalyzer(report_dir=tmp_path)
    assert analyzer.parse_observation("not-json", timestamp_s=10, duration_s=20) == []


def test_report_is_bounded_and_persisted(tmp_path):
    from jarvis.agent.media.video_analysis import (
        VideoAnalysisLimits,
        VideoAnalysisReport,
        persist_report,
    )

    report = VideoAnalysisReport(
        source_name="video.mp4",
        duration_s=12,
        candidates=[],
        omissions=["frame_failed"],
    )
    path = persist_report(report, tmp_path, VideoAnalysisLimits())
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "video-analysis.v1"
    assert payload["source_name"] == "video.mp4"
    assert str(tmp_path) in str(path)


def test_analyze_requires_loaded_identity_when_requested(tmp_path):
    from jarvis.agent.media.video_analysis import VideoAnalyzer

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"x")
    report = VideoAnalyzer(report_dir=tmp_path).analyze(
        str(source), resolve_loaded=[], require_loaded=True
    )
    assert report.status == "failed"
    assert report.reason_code == "video_path_not_loaded"


def test_cancelled_analysis_returns_honest_reason(tmp_path):
    from jarvis.agent.media.video_analysis import VideoAnalyzer

    cancel = threading.Event()
    cancel.set()
    report = VideoAnalyzer(report_dir=tmp_path).analyze(
        str(tmp_path / "missing.mp4"), cancel_event=cancel
    )
    assert report.status == "cancelled"
    assert report.reason_code == "video_cancelled"


def test_clip_interval_validation_is_explicit():
    from jarvis.agent.media.video_analysis import (
        VideoAnalysisError,
        VideoAnalysisLimits,
        validate_clip_interval,
    )

    with pytest.raises(VideoAnalysisError) as exc:
        validate_clip_interval(10, 10, 30, VideoAnalysisLimits())
    assert exc.value.code == "video_clip_interval_invalid"


def test_render_clip_uses_actual_probe_duration_and_fake_ffmpeg(tmp_path):
    from types import SimpleNamespace
    from jarvis.agent.media.video_analysis import render_clip

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")
    output_dir = tmp_path / "out"

    def command(args):
        output = __import__("pathlib").Path(args[-2])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"clip")
        return SimpleNamespace(returncode=0)

    output = render_clip(
        str(source), 0, 8, 99, output_dir=output_dir,
        probe_runner=lambda _path: {"format": {"duration": "5"}},
        command_runner=command,
    )
    assert output.is_file()
    assert "_0_5.mp4" in output.name


def test_render_clip_rejects_failed_probe(tmp_path):
    from jarvis.agent.media.video_analysis import VideoAnalysisError, render_clip

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")
    with pytest.raises(VideoAnalysisError) as exc:
        render_clip(
            str(source), 0, 1, 2,
            probe_runner=lambda _path: {"format": {"duration": "0"}},
        )
    assert exc.value.code == "video_ffprobe_failed"


def test_render_clip_rejects_failed_ffmpeg(tmp_path):
    from types import SimpleNamespace
    from jarvis.agent.media.video_analysis import VideoAnalysisError, render_clip

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")
    with pytest.raises(VideoAnalysisError) as exc:
        render_clip(
            str(source), 0, 1, 2,
            probe_runner=lambda _path: {"format": {"duration": "2"}},
            command_runner=lambda _args: SimpleNamespace(returncode=1),
        )
    assert exc.value.code == "video_clip_failed"

def test_render_clip_is_explicit_only(tmp_path):
    from jarvis.agent.media.video_analysis import VideoAnalyzer

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")
    report = VideoAnalyzer(
        report_dir=tmp_path / "reports",
        probe_runner=lambda _path: {
            "format": {"duration": "1"},
            "streams": [{"codec_type": "video", "width": 1,
                         "height": 1, "r_frame_rate": "1/1"}],
        },
        frame_runner=lambda _path, _timestamp: b"frame",
        vision=lambda *_args: '{"candidates": []}',
    ).analyze(str(source))
    assert report.report_path
    assert not list((tmp_path / "out").glob("*.mp4"))


def test_start_video_analysis_task_result_merujuk_report(tmp_path):
    """Provenance task/report: task DONE menyimpan nama report di result,
    bukan path privat; worker lepas slotnya setelah selesai."""
    from jarvis.agent.media import video_analysis as mod
    from jarvis.agent.tasks import REGISTRY, TaskStatus

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")

    report_dir = tmp_path / "media_reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    class FakeAnalyzer:
        limits = mod.VideoAnalysisLimits(max_frames=1)

        def analyze(self, source_path, cancel_event=None, progress=None,
                    resolve_loaded=None, require_loaded=False):
            report = mod.VideoAnalysisReport(
                source_name="clip.mp4", duration_s=1,
                candidates=[], omissions=[],
            )
            report_path = report_dir / "video_1.json"
            report_path.write_text(
                json.dumps(report.as_dict()), encoding="utf-8")
            report.report_path = str(report_path)
            return report

    REGISTRY.clear()
    try:
        task = mod.start_video_analysis(str(source), analyzer=FakeAnalyzer())
        assert task is not None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if REGISTRY.get(task.id).status not in (
                TaskStatus.QUEUED, TaskStatus.RUNNING,
            ):
                break
            time.sleep(0.01)
        view = REGISTRY.get(task.id)
        assert view.status is TaskStatus.DONE
        payload = json.loads(view.result)
        assert payload["source_name"] == "clip.mp4"
        assert payload["report"] == "video_1.json"
        assert payload["candidates"] == []
    finally:
        REGISTRY.clear()
