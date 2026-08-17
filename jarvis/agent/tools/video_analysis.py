"""Background long-video analysis and explicit clip extraction tools."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.media.video_analysis import (
    VideoAnalysisError,
    VideoAnalysisLimits,
    render_clip,
    resolve_video_source,
    source_fingerprint,
    start_video_analysis,
)
from jarvis.agent.paths import data_dir, is_allowed_path


def available() -> bool:
    """Keep the schema visible; the worker reports missing ffmpeg honestly."""
    return True


class _AnalyzeParams(BaseModel):
    source_path: str = Field(description="Path video lokal yang akan dianalisis")
    label: str = Field("", description="Judul singkat tugas")


class VideoAnalyze(Tool):
    name = "video_analyze"
    description = (
        "Antrikan analisis bounded video panjang: audio/transkrip, frame, "
        "dan kandidat momen viral bertimestamp. Kembali segera dengan task id; "
        "tidak membuat clip MP4 otomatis."
    )
    params_schema = _AnalyzeParams
    timeout_s = 15

    async def run(self, source_path: str = "", label: str = "", **kwargs) -> ToolResult:
        path = str(source_path or "").strip()
        if not path:
            return ToolResult.fail("butuh source_path video")
        loaded = kwargs.get("_loaded_paths") or []
        require_loaded = bool(kwargs.get("_require_loaded", False))
        if require_loaded:
            try:
                path = resolve_video_source(
                    path, loaded_paths=loaded, allow_unloaded=False
                )
            except VideoAnalysisError as exc:
                return ToolResult.fail(exc.code)
        elif not is_allowed_path(path):
            return ToolResult.fail("video_path_not_allowed")
        task = start_video_analysis(
            path,
            loaded_paths=loaded,
            title=str(label or "").strip() or None,
            source=str(kwargs.get("_source", "agent") or "agent"),
            require_loaded=require_loaded,
        )
        if task is None:
            return ToolResult.fail("antrean analisis video penuh")
        return ToolResult.success(
            {
                "id": task.id,
                "title": task.title,
                "status": task.status.value,
                "source_name": Path(path).name[:160],
                "clip_rendered": False,
            },
            display=f"analisis video {task.id} dimulai",
        )


class _ClipParams(BaseModel):
    source_path: str = Field(description="Path video sumber yang sudah diunggah")
    start_s: float = Field(description="Detik awal")
    end_s: float = Field(description="Detik akhir")
    duration_s: float = Field(0, description="Durasi video; wajib untuk render langsung")
    report_path: str = Field("", description="Nama report analisis untuk provenance")
    task_id: str = Field("", description="ID task analisis untuk provenance")
    output_format: str = Field("mp4", description="Format output; hanya mp4")


class VideoClip(Tool):
    name = "video_clip"
    description = (
        "Render satu clip secara eksplisit dari video lokal setelah kandidat "
        "dipilih. Validasi interval dan batas durasi; tidak menerima shell args."
    )
    params_schema = _ClipParams
    timeout_s = 360

    async def run(self, source_path: str = "", start_s: float = 0,
                  end_s: float = 0, duration_s: float = 0,
                  report_path: str = "", task_id: str = "",
                  output_format: str = "mp4", **kwargs) -> ToolResult:
        if str(output_format or "mp4").casefold() != "mp4":
            return ToolResult.fail("video_clip_format_unsupported")
        if not str(source_path or "").strip():
            return ToolResult.fail("video_file_not_found")
        if report_path or task_id:
            if not task_id or not report_path:
                return ToolResult.fail("video_provenance_mismatch")
        else:
            # Explicit timestamp rendering is allowed only as a direct action;
            # a report/task pair is required whenever analysis provenance is
            # claimed by the caller.
            source_path = str(source_path).strip()
        loaded = kwargs.get("_loaded_paths") or []
        if loaded:
            try:
                source_path = resolve_video_source(
                    source_path, loaded_paths=loaded, allow_unloaded=False
                )
            except VideoAnalysisError as exc:
                return ToolResult.fail(exc.code)
        elif kwargs.get("_source") == "voice-native":
            return ToolResult.fail("video_path_not_loaded")
        elif not is_allowed_path(source_path):
            return ToolResult.fail("video_path_not_allowed")
        if not duration_s:
            return ToolResult.fail("video_clip_duration_required")
        if report_path or task_id:
            from jarvis.agent.tasks import REGISTRY, TaskStatus
            view = REGISTRY.get(task_id)
            if view is None:
                return ToolResult.fail("video_task_not_found")
            if view.active:
                return ToolResult.fail("video_analysis_not_ready")
            if view.status is not TaskStatus.DONE:
                return ToolResult.fail("video_provenance_mismatch")
            report_root = (data_dir() / "media_reports").resolve()
            report_input = Path(report_path)
            if report_input.name != report_path or report_input.is_absolute():
                return ToolResult.fail("video_report_invalid")
            report = report_root / report_input.name
            try:
                if not report.is_file():
                    return ToolResult.fail("video_report_not_found")
                payload = json.loads(report.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    return ToolResult.fail("video_report_invalid")
                task_payload = json.loads(view.result or "{}")
                if not isinstance(task_payload, dict):
                    return ToolResult.fail("video_provenance_mismatch")
                if task_payload.get("report") != report.name:
                    return ToolResult.fail("video_provenance_mismatch")
                metadata = payload.get("metadata") or {}
                if (Path(str(payload.get("source_name", ""))).name
                        != Path(source_path).name):
                    return ToolResult.fail("video_provenance_mismatch")
                if metadata.get("fingerprint") != source_fingerprint(source_path):
                    return ToolResult.fail("video_provenance_mismatch")
            except FileNotFoundError:
                return ToolResult.fail("video_report_not_found")
            except json.JSONDecodeError:
                return ToolResult.fail("video_report_invalid")
            except (OSError, ValueError, TypeError, KeyError):
                return ToolResult.fail("video_report_invalid")
            except Exception:
                return ToolResult.fail("video_provenance_mismatch")
            report_path = str(report)
        try:
            path = await asyncio.to_thread(
                render_clip,
                source_path,
                start_s,
                end_s,
                duration_s,
                limits=VideoAnalysisLimits.from_config(),
            )
        except VideoAnalysisError as exc:
            return ToolResult.fail(exc.code)
        except Exception as exc:  # no private path/provider body in result
            return ToolResult.fail(f"video_clip_failed:{type(exc).__name__}")
        return ToolResult.success(
            {"artifact": path.name, "format": "mp4"},
            display=f"clip tersimpan: {path.name}",
        )


__all__ = ["VideoAnalyze", "VideoClip"]
