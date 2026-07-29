from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.verify_frozen import DEFAULT_MANIFEST, REPO_ROOT, verify_frozen


EXPECTED_FROZEN = {
    "main.py",
    "ui.py",
    "core/stt.py",
    "core/tts.py",
    "core/voice_listener.py",
    "core/prompt.txt",
    "jarvis/core/wake.py",
    "jarvis/ui/theme.py",
    "jarvis/ui/orb.py",
    "config/jarvis.ico",
}


def test_repository_frozen_manifest_passes() -> None:
    errors, manifest = verify_frozen()

    assert errors == []
    assert set(manifest["files"]) == EXPECTED_FROZEN


def test_verifier_detects_a_modified_frozen_file(tmp_path: Path) -> None:
    frozen = tmp_path / "voice.py"
    frozen.write_bytes(b"baseline\r\n")
    manifest = {
        "schema_version": 1,
        "algorithm": "sha256",
        "files": {
            "voice.py": {
                "mode": "text-lf",
                "sha256": hashlib.sha256(b"baseline\n").hexdigest(),
            }
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    errors, _ = verify_frozen(tmp_path, Path("manifest.json"))
    assert errors == []

    frozen.write_text("changed\n", encoding="utf-8")
    errors, _ = verify_frozen(tmp_path, Path("manifest.json"))
    assert len(errors) == 1
    assert "hash berubah" in errors[0]


def test_verifier_rejects_path_traversal(tmp_path: Path) -> None:
    manifest = {
        "schema_version": 1,
        "algorithm": "sha256",
        "files": {
            "../outside.py": {
                "mode": "text-lf",
                "sha256": "0" * 64,
            }
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    errors, _ = verify_frozen(tmp_path, Path("manifest.json"))
    assert errors == ["../outside.py: path harus relatif terhadap root dan tanpa '..'"]


def test_ci_workflow_runs_the_frozen_verifier() -> None:
    workflow = (REPO_ROOT / ".github/workflows/frozen-integrity.yml").read_text(
        encoding="utf-8"
    )

    assert "actions/checkout@v6" in workflow
    assert "actions/setup-python@v6" in workflow
    assert "python scripts/verify_frozen.py" in workflow
    assert "contents: read" in workflow


def test_docs_name_the_active_entry_and_legacy_blocker() -> None:
    readme = (REPO_ROOT / "readme.md").read_text(encoding="utf-8")
    plan = (REPO_ROOT / "docs/UI_LEGACY_RETIREMENT_PLAN.md").read_text(
        encoding="utf-8"
    )

    assert "python -m jarvis.main" in readme
    assert "python main.py" not in readme
    assert "main.py: from ui import JarvisUI" in plan
    assert "belum dapat dihapus" in plan


def test_default_manifest_location_is_stable() -> None:
    assert DEFAULT_MANIFEST.as_posix() == "config/frozen_manifest.json"
