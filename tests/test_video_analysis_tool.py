"""Tool and routing contracts for local video analysis."""
from __future__ import annotations

import asyncio
import json
import types


def _fake_tool(module: str):
    """Fresh class per module so select_tool_names sees each tool's own module.

    A single shared nested Tool class (with ``self.__class__.__module__ = ...``
    set in __init__) mutates the SAME class, so the last tool constructed leaks
    its module onto every tool — which made browser_media resolve to
    "task_tools" and broke the browser-video routing assertion.
    """
    cls = type("Tool", (), {})
    cls.__module__ = f"jarvis.agent.tools.{module}"
    return cls()


def test_video_tool_is_non_blocking_and_never_renders_clip(monkeypatch):
    from jarvis.agent.tools import video_analysis

    fake = types.SimpleNamespace(id="T-media", title="video", status=types.SimpleNamespace(value="queued"))
    monkeypatch.setattr(video_analysis, "start_video_analysis", lambda *a, **k: fake)
    result = asyncio.run(video_analysis.VideoAnalyze().run("clip.mp4"))
    assert result.ok is True
    assert result.content["id"] == "T-media"
    assert result.content["clip_rendered"] is False


def test_video_selector_prefers_local_analysis_over_browser_playback():
    from jarvis.agent.tool_selection import select_tool_names

    tools = {
        "video_analyze": _fake_tool("video_analysis"),
        "video_clip": _fake_tool("video_analysis"),
        "task_status": _fake_tool("task_tools"),
        "task_cancel": _fake_tool("task_tools"),
    }
    selected = select_tool_names("analisis video lokal dan cari momen viral", tools)
    assert "video_analyze" in selected
    assert "video_clip" in selected


def test_video_tool_rejects_direct_path_outside_workspace(monkeypatch):
    from jarvis.agent.tools import video_analysis

    monkeypatch.setattr(video_analysis, "is_allowed_path", lambda _path: False)
    result = asyncio.run(video_analysis.VideoAnalyze().run("C:/private/clip.mp4"))
    assert result.ok is False
    assert result.error == "video_path_not_allowed"


def test_video_clip_rejects_partial_provenance():
    from jarvis.agent.tools.video_analysis import VideoClip

    result = asyncio.run(VideoClip().run(
        "clip.mp4", start_s=0, end_s=1, duration_s=2, task_id="T-1"
    ))
    assert result.ok is False
    assert result.error == "video_provenance_mismatch"


def test_video_clip_accepts_valid_task_report_provenance(tmp_path, monkeypatch):
    """Provenance positif: task DONE + report nyata di media_reports +
    fingerprint cocok → clip dirender. Kebalikan dari test partial-provenance."""
    from types import SimpleNamespace

    from jarvis.agent import tasks as tasks_mod
    from jarvis.agent.tasks import TaskStatus
    from jarvis.agent.tools import video_analysis as tool_mod

    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")

    report_dir = tmp_path / "media_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_name = "video_20260816_0001.json"
    report_payload = {
        "schema_version": "video-analysis.v1",
        "source_name": "clip.mp4",
        "metadata": {"fingerprint": tool_mod.source_fingerprint(str(source))},
    }
    (report_dir / report_name).write_text(
        json.dumps(report_payload), encoding="utf-8")

    done = SimpleNamespace(
        active=False,
        status=TaskStatus.DONE,
        result=json.dumps({"report": report_name}),
    )
    monkeypatch.setattr(
        tasks_mod, "REGISTRY", SimpleNamespace(get=lambda _tid: done))
    monkeypatch.setattr(tool_mod, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(tool_mod, "is_allowed_path", lambda _p: True)

    out = tmp_path / "out" / "clip_0_5.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"clip")
    monkeypatch.setattr(tool_mod, "render_clip", lambda *a, **k: out)

    result = asyncio.run(tool_mod.VideoClip().run(
        source_path=str(source), start_s=0, end_s=5, duration_s=10,
        report_path=report_name, task_id="T-vid",
    ))
    assert result.ok is True
    assert result.content["artifact"] == "clip_0_5.mp4"
    assert result.content["format"] == "mp4"


def test_browser_video_request_stays_browser_category():
    from jarvis.agent.tool_selection import select_tool_names

    tools = {
        "browser_media": _fake_tool("browser"),
        "video_analyze": _fake_tool("video_analysis"),
        "task_status": _fake_tool("task_tools"),
        "task_cancel": _fake_tool("task_tools"),
    }
    selected = select_tool_names("pause video youtube di browser", tools)
    assert "browser_media" in selected
    assert "video_analyze" not in selected
