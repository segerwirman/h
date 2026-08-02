"""Desktop-local Content Studio project model and bounded prompt reader."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile
import re

_ALLOWED_SUFFIXES = {".txt": "text", ".md": "markdown", ".docx": "document", ".pdf": "pdf"}
_MAX_PROMPT_BYTES = 512 * 1024


@dataclass(frozen=True)
class Scene:
    title: str
    visual: str
    narration: str
    visual_prompt: str

    def public_dict(self) -> dict:
        return {
            "title": self.title,
            "visual": self.visual,
            "narration": self.narration,
            "visual_prompt": self.visual_prompt,
        }


@dataclass(frozen=True)
class ContentProject:
    title: str
    audience: str
    tone: str
    hook: str
    cta: str
    scenes: tuple[Scene, ...] = ()

    def public_dict(self) -> dict:
        return {
            "title": self.title,
            "audience": self.audience,
            "tone": self.tone,
            "hook": self.hook,
            "cta": self.cta,
            "scenes": [scene.public_dict() for scene in self.scenes],
        }


def _docx_text(path: Path) -> str:
    with ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", xml)).strip()


def _pdf_text(path: Path) -> str:
    try:
        import fitz
        with fitz.open(path) as document:
            return "\n".join(page.get_text() for page in document).strip()
    except (ImportError, OSError, RuntimeError, ValueError):
        return ""


def read_local_prompt(path: str | Path, *, max_bytes: int = _MAX_PROMPT_BYTES) -> dict:
    """Read a small local creative brief; return text only, never the source location."""
    candidate = Path(path)
    kind = _ALLOWED_SUFFIXES.get(candidate.suffix.lower())
    if kind is None:
        return {"ok": False, "reason": "content_prompt_type_rejected"}
    try:
        if candidate.stat().st_size > max(1, int(max_bytes)):
            return {"ok": False, "reason": "content_prompt_too_large"}
        if kind in {"text", "markdown"}:
            text = candidate.read_text(encoding="utf-8", errors="replace").strip()
        elif kind == "document":
            text = _docx_text(candidate)
        else:
            text = _pdf_text(candidate)
    except (OSError, KeyError, ValueError):
        return {"ok": False, "reason": "content_prompt_unavailable"}
    if not text:
        return {"ok": False, "reason": "content_prompt_unavailable"}
    return {"ok": True, "kind": kind, "text": text}


__all__ = ["ContentProject", "Scene", "read_local_prompt"]
