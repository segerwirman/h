"""Local-first immutable version catalog for Jarvis skills."""
from __future__ import annotations

import hashlib
from pathlib import Path


class LocalSkillCatalog:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def publish(self, name: str, content: str, *, version: str) -> dict:
        safe_name = str(name).strip()
        safe_version = str(version).strip()
        if not safe_name or not safe_version or not content:
            raise ValueError("name, version, and content are required")
        path = self.root / safe_name / safe_version / "SKILL.md"
        if path.exists():
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"name": safe_name, "version": safe_version,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}

    def browse(self, name: str = "") -> list[dict]:
        roots = [self.root / name] if name else sorted(self.root.iterdir())
        out = []
        for skill_root in roots:
            if not skill_root.is_dir():
                continue
            for version_dir in sorted(skill_root.iterdir(), reverse=True):
                path = version_dir / "SKILL.md"
                if path.is_file():
                    content = path.read_text(encoding="utf-8")
                    out.append({"name": skill_root.name, "version": version_dir.name,
                                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()})
        return out

    def rollback(self, name: str, version: str) -> str:
        path = self.root / str(name) / str(version) / "SKILL.md"
        return path.read_text(encoding="utf-8")
