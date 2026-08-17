"""Bounded long-video analysis and explicit clip rendering.

The service is deliberately independent from Qt and Gemini Live.  It owns only
local media preparation, bounded multimodal observations, deterministic ranking,
and TaskRegistry lifecycle helpers.  Provider calls are injected in tests and
never run merely because a file was uploaded.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from jarvis.agent.paths import data_dir, generated_dir
from jarvis.core import config, log

_logger = log.get("agent.media.video")

VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".3gp",
})
VIDEO_REASON_CODES = frozenset({
    "video_file_not_found",
    "video_path_not_loaded",
    "video_ambiguous_identity",
    "video_extension_unsupported",
    "video_size_limit",
    "video_duration_limit",
    "video_ffmpeg_unavailable",
    "video_ffprobe_failed",
    "video_no_video_stream",
    "video_no_audio_track",
    "video_transcript_unavailable",
    "video_frame_failed",
    "video_vision_unavailable",
    "video_provider_rejected",
    "video_cancelled",
    "video_report_write_failed",
    "video_clip_interval_invalid",
    "video_clip_failed",
    "video_path_not_allowed",
    "video_task_not_found",
    "video_analysis_not_ready",
    "video_provenance_mismatch",
    "video_report_not_found",
    "video_report_invalid",
})


class VideoAnalysisError(ValueError):
    """Safe, stable error code for a local media failure."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = str(code)
        self.message = str(message or code)
        super().__init__(self.message)


@dataclass(frozen=True)
class VideoAnalysisLimits:
    max_file_size_bytes: int = 512 * 1024 * 1024
    max_duration_s: float = 2 * 60 * 60
    audio_chunk_s: float = 120.0
    frame_interval_s: float = 30.0
    max_frames: int = 120
    max_candidates: int = 20
    max_clip_duration_s: float = 180.0
    max_report_bytes: int = 1_000_000
    max_transcript_chars: int = 12_000
    max_excerpt_chars: int = 1_000

    @classmethod
    def from_config(cls) -> "VideoAnalysisLimits":
        def clamp_int(value: Any, default: int, minimum: int) -> int:
            try:
                return max(minimum, int(value))
            except (TypeError, ValueError):
                return default

        def clamp_float(value: Any, default: float, minimum: float) -> float:
            try:
                return max(minimum, float(value))
            except (TypeError, ValueError):
                return default

        # Setiap key dibaca dengan literal agar scanner kontrak config
        # (jarvis/core/config_contract.py) dapat mencocokkannya ke config.yaml.
        return cls(
            max_file_size_bytes=clamp_int(config.get(
                "media.video.max_file_size_bytes", cls.max_file_size_bytes),
                cls.max_file_size_bytes, 1),
            max_duration_s=clamp_float(config.get(
                "media.video.max_duration_s", cls.max_duration_s),
                cls.max_duration_s, 1.0),
            audio_chunk_s=clamp_float(config.get(
                "media.video.audio_chunk_s", cls.audio_chunk_s),
                cls.audio_chunk_s, 1.0),
            frame_interval_s=clamp_float(config.get(
                "media.video.frame_interval_s", cls.frame_interval_s),
                cls.frame_interval_s, 0.1),
            max_frames=clamp_int(config.get(
                "media.video.max_frames", cls.max_frames), cls.max_frames, 1),
            max_candidates=min(20, clamp_int(config.get(
                "media.video.max_candidates", cls.max_candidates),
                cls.max_candidates, 1)),
            max_clip_duration_s=clamp_float(config.get(
                "media.video.max_clip_duration_s", cls.max_clip_duration_s),
                cls.max_clip_duration_s, 0.1),
            max_report_bytes=clamp_int(config.get(
                "media.video.max_report_bytes", cls.max_report_bytes),
                cls.max_report_bytes, 10_000),
            max_transcript_chars=clamp_int(config.get(
                "media.video.max_transcript_chars", cls.max_transcript_chars),
                cls.max_transcript_chars, 100),
            max_excerpt_chars=clamp_int(config.get(
                "media.video.max_excerpt_chars", cls.max_excerpt_chars),
                cls.max_excerpt_chars, 80),
        )


@dataclass(frozen=True)
class VideoMetadata:
    source_name: str
    fingerprint: str
    byte_size: int
    duration_s: float
    width: int = 0
    height: int = 0
    frame_rate: float = 0.0
    has_video: bool = True
    has_audio: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VideoMoment:
    start_s: float
    end_s: float
    hook: str
    transcript_excerpt: str = ""
    visual_context: str = ""
    rationale: str = ""
    score: float = 0.0
    confidence: float = 0.0
    suggested_duration_s: float = 0.0

    @property
    def title(self) -> str:
        return self.hook

    def as_dict(self) -> dict[str, Any]:
        return {
            "start_s": round(self.start_s, 3),
            "end_s": round(self.end_s, 3),
            "hook": self.hook,
            "title": self.hook,
            "transcript_excerpt": self.transcript_excerpt,
            "visual_context": self.visual_context,
            "rationale": self.rationale,
            "score": round(self.score, 4),
            "confidence": round(self.confidence, 4),
            "suggested_duration_s": round(self.suggested_duration_s, 3),
        }


@dataclass
class VideoAnalysisReport:
    source_name: str
    duration_s: float = 0.0
    status: str = "done"
    reason_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    candidates: list[VideoMoment] = field(default_factory=list)
    sampled_frames: int = 0
    audio_chunks: int = 0
    omissions: list[str] = field(default_factory=list)
    report_path: str = ""
    schema_version: str = "video-analysis.v1"

    @classmethod
    def failed(cls, reason_code: str, source_name: str, **fields: Any):
        return cls(
            source_name=_safe_name(source_name),
            status="failed",
            reason_code=str(reason_code),
            **fields,
        )

    @classmethod
    def cancelled(cls, source_name: str):
        return cls(
            source_name=_safe_name(source_name),
            status="cancelled",
            reason_code="video_cancelled",
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_name": _safe_name(self.source_name),
            "duration_s": round(float(self.duration_s or 0), 3),
            "status": self.status,
            "reason_code": self.reason_code,
            "metadata": dict(self.metadata or {}),
            "candidates": [item.as_dict() for item in self.candidates],
            "sampled_frames": int(self.sampled_frames),
            "audio_chunks": int(self.audio_chunks),
            "omissions": [str(item)[:80] for item in self.omissions[:100]],
        }


def _safe_name(value: str) -> str:
    return os.path.basename(str(value or ""))[:160] or "video"


def _fingerprint(path: Path) -> str:
    stat = path.stat()
    raw = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def source_fingerprint(path: str | Path) -> str:
    """Return the bounded identity used to bind a report to its source."""
    return _fingerprint(Path(path))


def _normal_path(value: str) -> str:
    try:
        return os.path.normcase(os.path.abspath(os.path.expanduser(str(value))))
    except (TypeError, ValueError, OSError):
        return ""


def resolve_video_source(
    given: str,
    *,
    loaded_paths: list[str] | tuple[str, ...] | None = None,
    allow_unloaded: bool = True,
) -> str:
    """Resolve a loaded identity without guessing through a directory scan."""
    requested = str(given or "").strip()
    candidates = [str(item) for item in (loaded_paths or ()) if str(item).strip()]
    if not requested:
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise VideoAnalysisError("video_ambiguous_identity")
        raise VideoAnalysisError("video_path_not_loaded")

    requested_norm = _normal_path(requested)
    exact = [item for item in candidates if _normal_path(item) == requested_norm]
    if exact:
        return exact[0]
    basename = os.path.basename(requested).casefold()
    matches = [
        item for item in candidates
        if basename and os.path.basename(item).casefold() == basename
    ]
    if len(matches) > 1:
        raise VideoAnalysisError("video_ambiguous_identity")
    if len(matches) == 1:
        return matches[0]
    if not allow_unloaded:
        raise VideoAnalysisError("video_path_not_loaded")
    return requested


def validate_video_path(path: str, limits: VideoAnalysisLimits) -> Path:
    candidate = Path(str(path or "")).expanduser()
    if not candidate.exists() or not candidate.is_file():
        raise VideoAnalysisError("video_file_not_found")
    if candidate.suffix.casefold() not in VIDEO_EXTENSIONS:
        raise VideoAnalysisError("video_extension_unsupported")
    try:
        size = candidate.stat().st_size
    except OSError:
        raise VideoAnalysisError("video_file_not_found") from None
    if size > limits.max_file_size_bytes:
        raise VideoAnalysisError("video_size_limit")
    return candidate


def audio_chunk_boundaries(
    duration_s: float, limits: VideoAnalysisLimits | None = None
) -> list[tuple[float, float]]:
    limits = limits or VideoAnalysisLimits()
    duration = max(0.0, float(duration_s))
    if duration <= 0:
        return []
    step = max(0.1, float(limits.audio_chunk_s))
    out: list[tuple[float, float]] = []
    start = 0.0
    while start < duration - 1e-9:
        end = min(duration, start + step)
        out.append((round(start, 6), round(end, 6)))
        start = end
    return out


def frame_timestamps(
    duration_s: float, limits: VideoAnalysisLimits | None = None
) -> list[float]:
    limits = limits or VideoAnalysisLimits()
    duration = max(0.0, float(duration_s))
    if duration <= 0:
        return []
    interval = max(0.1, float(limits.frame_interval_s))
    values: list[float] = []
    cursor = 0.0
    while cursor < duration - 1e-9 and len(values) < max(1, limits.max_frames):
        values.append(round(cursor, 6))
        cursor += interval
    return values


def _overlap(left: VideoMoment, right: VideoMoment) -> float:
    intersection = max(0.0, min(left.end_s, right.end_s) - max(left.start_s, right.start_s))
    shorter = min(left.end_s - left.start_s, right.end_s - right.start_s)
    return intersection / shorter if shorter > 0 else 0.0


def _moment_from_raw(raw: dict[str, Any], duration_s: float,
                    limits: VideoAnalysisLimits) -> VideoMoment | None:
    try:
        start = float(raw.get("start_s", raw.get("start", -1)))
        end = float(raw.get("end_s", raw.get("end", -1)))
        score = float(raw.get("score", raw.get("virality_score", 0)))
        confidence = float(raw.get("confidence", 0))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (start, end, score, confidence)):
        return None
    if start < 0 or end <= start or end > float(duration_s):
        return None
    if end - start > limits.max_clip_duration_s:
        return None
    hook = " ".join(str(raw.get("hook", raw.get("title", "")) or "").split())
    if not hook:
        return None
    score = max(0.0, min(1.0, score))
    confidence = max(0.0, min(1.0, confidence))
    return VideoMoment(
        start_s=start,
        end_s=end,
        hook=hook[:240],
        transcript_excerpt=str(raw.get("transcript_excerpt", raw.get("transcript", "")) or "")[:limits.max_excerpt_chars],
        visual_context=str(raw.get("visual_context", raw.get("visual", "")) or "")[:600],
        rationale=str(raw.get("rationale", "") or "")[:600],
        score=score,
        confidence=confidence,
        suggested_duration_s=min(
            float(raw.get("suggested_duration_s", end - start) or (end - start)),
            limits.max_clip_duration_s,
        ),
    )


def rank_candidates(
    raw_candidates: list[dict[str, Any]],
    *,
    duration_s: float,
    limits: VideoAnalysisLimits | None = None,
) -> list[VideoMoment]:
    limits = limits or VideoAnalysisLimits()
    parsed = [
        item for item in (
            _moment_from_raw(raw, duration_s, limits)
            for raw in (raw_candidates or ())
            if isinstance(raw, dict)
        ) if item is not None
    ]
    parsed.sort(key=lambda item: (-item.score, -item.confidence,
                                  item.start_s, item.end_s, item.hook.casefold()))
    selected: list[VideoMoment] = []
    for item in parsed:
        if any(_overlap(item, existing) >= 0.5 for existing in selected):
            continue
        selected.append(item)
        if len(selected) >= limits.max_candidates:
            break
    return selected


def _json_payload(text: str) -> Any:
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value,
                       flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def persist_report(
    report: VideoAnalysisReport,
    report_dir: Path | str,
    limits: VideoAnalysisLimits | None = None,
) -> Path:
    limits = limits or VideoAnalysisLimits()
    directory = Path(report_dir)
    directory.mkdir(parents=True, exist_ok=True)
    identity = str((report.metadata or {}).get("fingerprint") or "")
    if not identity:
        identity = f"{report.source_name}|{report.duration_s}"
    digest = hashlib.sha256(identity.encode()).hexdigest()[:16]
    path = directory / f"video_report_{digest}.json"
    payload = json.dumps(report.as_dict(), ensure_ascii=False, separators=(",", ":"))
    if len(payload.encode("utf-8")) > limits.max_report_bytes:
        trimmed = VideoAnalysisReport(
            source_name=report.source_name,
            duration_s=report.duration_s,
            status=report.status,
            reason_code=report.reason_code,
            metadata=report.metadata,
            candidates=report.candidates[: limits.max_candidates],
            sampled_frames=report.sampled_frames,
            audio_chunks=report.audio_chunks,
            omissions=report.omissions + ["report_bounded"],
        )
        payload = json.dumps(trimmed.as_dict(), ensure_ascii=False, separators=(",", ":"))
    path.write_text(payload + "\n", encoding="utf-8")
    report.report_path = str(path)
    return path


def validate_clip_interval(
    start_s: float, end_s: float, duration_s: float,
    limits: VideoAnalysisLimits | None = None,
) -> tuple[float, float]:
    limits = limits or VideoAnalysisLimits()
    try:
        start = float(start_s)
        end = float(end_s)
        duration = float(duration_s)
    except (TypeError, ValueError):
        raise VideoAnalysisError("video_clip_interval_invalid") from None
    if not all(math.isfinite(value) for value in (start, end, duration)):
        raise VideoAnalysisError("video_clip_interval_invalid")
    if start < 0 or end <= start or duration <= 0 or end > duration:
        raise VideoAnalysisError("video_clip_interval_invalid")
    if end - start > limits.max_clip_duration_s:
        raise VideoAnalysisError("video_clip_interval_invalid")
    return round(start, 3), round(end, 3)


class VideoAnalyzer:
    """Synchronous worker service; callers must place it off the UI thread."""

    def __init__(
        self,
        *,
        limits: VideoAnalysisLimits | None = None,
        report_dir: Path | str | None = None,
        probe_runner: Callable[[str], Any] | None = None,
        audio_runner: Callable[[str, float, float], str] | None = None,
        frame_runner: Callable[[str, float], bytes] | None = None,
        vision: Any = None,
    ) -> None:
        self.limits = limits or VideoAnalysisLimits.from_config()
        self.report_dir = Path(report_dir) if report_dir is not None else data_dir() / "media_reports"
        self.probe_runner = probe_runner
        self.audio_runner = audio_runner
        self.frame_runner = frame_runner
        self.vision = vision

    def parse_observation(self, text: str, *, timestamp_s: float,
                          duration_s: float) -> list[VideoMoment]:
        payload = _json_payload(text)
        if isinstance(payload, dict):
            payload = payload.get("candidates", payload.get("moments", [payload]))
        if not isinstance(payload, list):
            return []
        return rank_candidates(payload, duration_s=duration_s, limits=self.limits)

    def _probe(self, path: Path) -> VideoMetadata:
        if self.probe_runner is not None:
            try:
                payload = self.probe_runner(str(path))
            except VideoAnalysisError:
                raise
            except FileNotFoundError:
                raise VideoAnalysisError("video_ffmpeg_unavailable") from None
            except Exception:
                raise VideoAnalysisError("video_ffprobe_failed") from None
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, json.JSONDecodeError):
                    raise VideoAnalysisError("video_ffprobe_failed") from None
        else:
            try:
                run = subprocess.run(
                    ["ffprobe", "-v", "error", "-print_format", "json",
                     "-show_format", "-show_streams", str(path)],
                    capture_output=True, text=True, timeout=60,
                )
            except FileNotFoundError:
                raise VideoAnalysisError("video_ffmpeg_unavailable") from None
            except Exception:
                raise VideoAnalysisError("video_ffprobe_failed") from None
            if run.returncode != 0:
                raise VideoAnalysisError("video_ffprobe_failed")
            try:
                payload = json.loads(run.stdout or "")
            except (TypeError, json.JSONDecodeError):
                raise VideoAnalysisError("video_ffprobe_failed") from None
        if not isinstance(payload, dict):
            raise VideoAnalysisError("video_ffprobe_failed")
        streams = payload.get("streams") or []
        video = next((item for item in streams if item.get("codec_type") == "video"), None)
        audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
        if not isinstance(video, dict):
            raise VideoAnalysisError("video_no_video_stream")
        format_info = payload.get("format") or {}
        try:
            duration = float(format_info.get("duration") or video.get("duration") or 0)
        except (TypeError, ValueError):
            raise VideoAnalysisError("video_ffprobe_failed") from None
        if duration <= 0 or not math.isfinite(duration):
            raise VideoAnalysisError("video_ffprobe_failed")
        if duration > self.limits.max_duration_s:
            raise VideoAnalysisError("video_duration_limit")
        try:
            rate = str(video.get("r_frame_rate", "0/1"))
            numerator, denominator = rate.split("/", 1)
            frame_rate = float(numerator) / float(denominator or 1)
        except (TypeError, ValueError, ZeroDivisionError):
            frame_rate = 0.0
        return VideoMetadata(
            source_name=_safe_name(path.name), fingerprint=_fingerprint(path),
            byte_size=path.stat().st_size, duration_s=duration,
            width=int(video.get("width") or 0), height=int(video.get("height") or 0),
            frame_rate=frame_rate, has_video=True, has_audio=audio is not None,
        )

    def _default_audio(self, path: Path, start: float, end: float) -> str:
        temp_name = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
                temp_name = handle.name
            run = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", str(start), "-t",
                 str(end - start), "-i", str(path), "-map", "a:0", "-ac", "1",
                 "-ar", "16000", temp_name, "-y"],
                capture_output=True, timeout=300,
            )
            if run.returncode != 0 or not Path(temp_name).exists():
                return ""
            from actions.file_processor import _process_audio
            result = _process_audio(Path(temp_name), "transcribe", {"save": False}, None)
            text = str(result or "").strip()
            if text.lower().startswith("transcription failed"):
                return ""
            return text[: self.limits.max_transcript_chars]
        except FileNotFoundError:
            return ""
        except Exception:
            return ""
        finally:
            if temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass

    def _default_frame(self, path: Path, timestamp: float) -> bytes:
        temp_name = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
                temp_name = handle.name
            run = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", str(timestamp), "-i",
                 str(path), "-frames:v", "1", "-q:v", "4", temp_name, "-y"],
                capture_output=True, timeout=120,
            )
            if run.returncode != 0:
                return b""
            return Path(temp_name).read_bytes()
        except Exception:
            return b""
        finally:
            if temp_name:
                try:
                    Path(temp_name).unlink(missing_ok=True)
                except OSError:
                    pass

    def _vision_text(self, frame: bytes, transcript: str, timestamp: float) -> str:
        prompt = (
            "Analisis frame video dan cuplikan transkrip berikut. Jawab hanya JSON "
            "berisi candidates array. Setiap candidate WAJIB punya start_s, end_s, "
            "hook, score 0..1, confidence 0..1, transcript_excerpt, visual_context, "
            "dan rationale. Jangan membuat timestamp yang tidak didukung.\n"
            f"timestamp frame: {timestamp:.3f}\ntranskrip: {transcript[:self.limits.max_excerpt_chars]}"
        )
        target = self.vision
        try:
            if target is None:
                from jarvis.agent.llm_client import vision_client
                target = vision_client()
            if callable(target):
                return str(target(frame, "image/jpeg", prompt) or "")
            method = getattr(target, "vision", None)
            if callable(method):
                return str(method(frame, "image/jpeg", prompt, json_mode=True) or "")
        except Exception as exc:  # provider failure becomes omission, not a claim
            _logger.info("video.vision_failed", error=type(exc).__name__)
        return ""

    def analyze(
        self,
        path: str,
        *,
        cancel_event: threading.Event | None = None,
        progress: Callable[[str, int, int], None] | None = None,
        resolve_loaded: list[str] | tuple[str, ...] | None = None,
        require_loaded: bool = False,
    ) -> VideoAnalysisReport:
        cancel_event = cancel_event or threading.Event()
        source_name = _safe_name(path)
        if cancel_event.is_set():
            return VideoAnalysisReport.cancelled(source_name)
        try:
            resolved = resolve_video_source(
                path, loaded_paths=resolve_loaded,
                allow_unloaded=not require_loaded,
            )
            source = validate_video_path(resolved, self.limits)
            metadata = self._probe(source)
        except VideoAnalysisError as exc:
            return VideoAnalysisReport.failed(exc.code, source_name)
        if cancel_event.is_set():
            return VideoAnalysisReport.cancelled(source.name)

        report = VideoAnalysisReport(
            source_name=metadata.source_name,
            duration_s=metadata.duration_s,
            metadata=metadata.as_dict(),
        )
        omissions: list[str] = []
        chunks = audio_chunk_boundaries(metadata.duration_s, self.limits)
        transcripts: list[tuple[float, float, str]] = []
        total = len(chunks) + len(frame_timestamps(metadata.duration_s, self.limits)) + 1
        step = 0
        if not metadata.has_audio:
            omissions.append("video_no_audio_track")
        else:
            audio_fn = self.audio_runner or self._default_audio
            for start, end in chunks:
                if cancel_event.is_set():
                    return VideoAnalysisReport.cancelled(source.name)
                step += 1
                if progress:
                    progress("audio", step, total)
                try:
                    text = str(audio_fn(str(source), start, end) or "")[:self.limits.max_transcript_chars]
                except Exception:
                    text = ""
                if text:
                    transcripts.append((start, end, text))
            report.audio_chunks = len(transcripts)
            if chunks and not transcripts:
                omissions.append("video_transcript_unavailable")

        candidates: list[VideoMoment] = []
        timestamps = frame_timestamps(metadata.duration_s, self.limits)
        frame_fn = self.frame_runner or (lambda value, timestamp: self._default_frame(Path(value), timestamp))
        for timestamp in timestamps:
            if cancel_event.is_set():
                return VideoAnalysisReport.cancelled(source.name)
            step += 1
            if progress:
                progress("frames", step, total)
            try:
                frame = frame_fn(str(source), timestamp)
            except Exception:
                frame = b""
            if not frame:
                omissions.append("video_frame_failed")
                continue
            report.sampled_frames += 1
            transcript = next((text for start, end, text in transcripts
                               if start <= timestamp < end), "")
            if progress:
                progress("vision", step, total)
            observation = self._vision_text(frame, transcript, timestamp)
            parsed = self.parse_observation(
                observation, timestamp_s=timestamp, duration_s=metadata.duration_s
            )
            candidates.extend(item.as_dict() for item in parsed)
        if timestamps and not report.sampled_frames:
            omissions.append("video_frame_failed")
        if report.sampled_frames and not candidates:
            omissions.append("video_vision_unavailable")
        report.candidates = rank_candidates(
            candidates, duration_s=metadata.duration_s, limits=self.limits
        )
        report.omissions = sorted(set(omissions))
        report.status = "partial" if report.omissions else "done"
        report.reason_code = report.omissions[0] if report.omissions else ""
        if progress:
            progress("ranking", total, total)
        try:
            persist_report(report, self.report_dir, self.limits)
        except Exception:
            report.status = "failed"
            report.reason_code = "video_report_write_failed"
        return report


def _task_summary(report: VideoAnalysisReport) -> str:
    payload = {
        "status": report.status,
        "reason_code": report.reason_code,
        "source_name": report.source_name,
        "report": Path(report.report_path).name if report.report_path else "",
        "candidates": [item.as_dict() for item in report.candidates],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))[:24_000]


def start_video_analysis(
    source_path: str,
    *,
    loaded_paths: list[str] | tuple[str, ...] | None = None,
    analyzer: VideoAnalyzer | None = None,
    title: str | None = None,
    source: str = "media",
    require_loaded: bool = False,
):
    """Submit and immediately return a TaskRegistry task view owner."""
    # Identity validation is cheap and happens before queueing; the expensive
    # probe/transcription/frame work remains in the background worker.
    if require_loaded:
        try:
            source_path = resolve_video_source(
                source_path,
                loaded_paths=loaded_paths,
                allow_unloaded=False,
            )
        except VideoAnalysisError:
            return None

    from jarvis.agent.tasks import REGISTRY, TaskStatus

    if not str(source_path or "").strip():
        return None
    analyzer = analyzer or VideoAnalyzer()
    task = REGISTRY.submit(
        f"Analisis video {_safe_name(source_path)}",
        title=title or f"Analisis video {_safe_name(source_path)}",
        resources=frozenset({"media"}),
        max_iterations=max(1, analyzer.limits.max_frames + 10),
        source=source,
    )
    if task is None:
        return None

    def worker() -> None:
        if not REGISTRY.acquire_slot(task):
            return
        REGISTRY.mark_running(task.id)
        try:
            def update(stage: str, iteration: int, total: int) -> None:
                REGISTRY.update(task.id, step=stage, iteration=min(total, iteration))

            report = analyzer.analyze(
                source_path, cancel_event=task.cancel, progress=update,
                resolve_loaded=loaded_paths, require_loaded=require_loaded,
            )
            if report.status == "cancelled":
                REGISTRY.finish(task.id, result=_task_summary(report),
                                status=TaskStatus.CANCELLED)
            elif report.status == "failed":
                REGISTRY.finish(task.id, result=_task_summary(report),
                                error=report.reason_code)
            else:
                REGISTRY.finish(task.id, result=_task_summary(report))
        except Exception as exc:  # no raw provider/path details in task result
            REGISTRY.finish(task.id, error=f"video_analysis_failed:{type(exc).__name__}")
        finally:
            REGISTRY.release_slot(task)

    threading.Thread(
        target=worker, daemon=True, name=f"video-analysis-{task.id}"
    ).start()
    return task


# Clip rendering is intentionally a separate explicit operation.


def render_clip(
    source_path: str,
    start_s: float,
    end_s: float,
    duration_s: float,
    *,
    limits: VideoAnalysisLimits | None = None,
    output_dir: Path | str | None = None,
    command_runner: Callable[..., Any] | None = None,
    probe_runner: Callable[[str], Any] | None = None,
) -> Path:
    limits = limits or VideoAnalysisLimits.from_config()
    source = validate_video_path(source_path, limits)
    # Re-probe the source at render time; caller-supplied metadata is only a
    # bound and cannot authorize an interval beyond the actual media duration.
    try:
        if probe_runner is None:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-print_format", "json",
                 "-show_format", "-show_streams", str(source)],
                capture_output=True, text=True, timeout=60,
            )
            if probe.returncode != 0:
                raise ValueError
            payload = json.loads(probe.stdout or "")
        else:
            payload = probe_runner(str(source))
            if isinstance(payload, str):
                payload = json.loads(payload)
        actual_duration = float(
            (payload.get("format") or {}).get("duration") or 0
        )
        if not isinstance(payload, dict) or actual_duration <= 0 \
                or not math.isfinite(actual_duration):
            raise ValueError
    except FileNotFoundError:
        raise VideoAnalysisError("video_ffmpeg_unavailable") from None
    except Exception:
        raise VideoAnalysisError("video_ffprobe_failed") from None
    duration_s = min(float(duration_s), actual_duration)
    # A stale report may carry an end beyond the current media duration. Clamp
    # that upper bound to the probed source, while still rejecting invalid or
    # out-of-range starts through the interval validator.
    try:
        bounded_end = min(float(end_s), actual_duration)
    except (TypeError, ValueError):
        bounded_end = end_s
    start, end = validate_clip_interval(start_s, bounded_end, duration_s, limits)
    directory = Path(output_dir) if output_dir is not None else generated_dir()
    directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(
        f"{source.resolve()}|{start}|{end}".encode()
    ).hexdigest()[:12]
    output = directory / f"clip_{digest}_{int(start)}_{int(end)}.mp4"
    args = ["ffmpeg", "-v", "error", "-ss", str(start), "-to", str(end),
            "-i", str(source), "-c", "copy", str(output), "-y"]
    try:
        if command_runner is None:
            run = subprocess.run(args, capture_output=True, timeout=300)
        else:
            run = command_runner(args)
    except FileNotFoundError:
        raise VideoAnalysisError("video_ffmpeg_unavailable") from None
    except Exception:
        raise VideoAnalysisError("video_clip_failed") from None
    if getattr(run, "returncode", 1) != 0 or not output.exists() or output.stat().st_size <= 0:
        raise VideoAnalysisError("video_clip_failed")
    return output


__all__ = [
    "VIDEO_EXTENSIONS", "VIDEO_REASON_CODES", "VideoAnalysisError",
    "VideoAnalysisLimits", "VideoMetadata", "VideoMoment", "VideoAnalysisReport",
    "VideoAnalyzer", "audio_chunk_boundaries", "frame_timestamps", "rank_candidates",
    "resolve_video_source", "source_fingerprint", "validate_video_path",
    "persist_report", "validate_clip_interval", "start_video_analysis",
    "render_clip",
]
