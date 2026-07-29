"""Verify that MK50 Frozen-zone files still match the approved baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = Path("config/frozen_manifest.json")


def _canonical_bytes(path: Path, mode: str) -> bytes:
    data = path.read_bytes()
    if mode == "binary":
        return data
    if mode == "text-lf":
        return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    raise ValueError(f"mode tidak didukung: {mode}")


def _safe_relative_path(value: str) -> Path:
    posix = PurePosixPath(value)
    if posix.is_absolute() or not posix.parts or ".." in posix.parts:
        raise ValueError("path harus relatif terhadap root dan tanpa '..'")
    return Path(*posix.parts)


def verify_frozen(
    root: Path = REPO_ROOT,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> tuple[list[str], dict[str, Any]]:
    """Return integrity errors and the parsed manifest without changing files."""

    root = root.resolve()
    manifest_file = manifest_path if manifest_path.is_absolute() else root / manifest_path
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"manifest tidak dapat dibaca: {exc}"], {}

    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("schema_version manifest harus 1")
    if manifest.get("algorithm") != "sha256":
        errors.append("algorithm manifest harus sha256")

    entries = manifest.get("files")
    if not isinstance(entries, dict) or not entries:
        errors.append("manifest.files harus berupa object yang tidak kosong")
        return errors, manifest

    for name, entry in entries.items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            errors.append(f"entri manifest tidak valid: {name!r}")
            continue
        try:
            relative = _safe_relative_path(name)
        except ValueError as exc:
            errors.append(f"{name}: {exc}")
            continue

        expected = entry.get("sha256")
        mode = entry.get("mode")
        if not isinstance(expected, str) or len(expected) != 64:
            errors.append(f"{name}: sha256 harus 64 karakter heksadesimal")
            continue
        try:
            int(expected, 16)
        except ValueError:
            errors.append(f"{name}: sha256 bukan heksadesimal")
            continue

        target = root / relative
        if not target.is_file():
            errors.append(f"{name}: file FROZEN hilang")
            continue
        try:
            actual = hashlib.sha256(_canonical_bytes(target, str(mode))).hexdigest()
        except (OSError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
            continue
        if actual != expected.lower():
            errors.append(f"{name}: hash berubah (expected {expected}, actual {actual})")

    return errors, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()

    errors, manifest = verify_frozen(args.root, args.manifest)
    if errors:
        print("FROZEN integrity: FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    count = len(manifest["files"])
    baseline = manifest.get("baseline_commit", "unknown")
    print(f"FROZEN integrity: OK ({count} files, baseline {baseline})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
