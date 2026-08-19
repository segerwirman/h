"""Render explicit evidence labels recorded in each phase result.

The parser deliberately reads only ``Hasil Fase`` sections.  In particular,
``live-proven`` is never inferred from tests, source files, or a successful
phase heading; it must occur positively in that phase's result text.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "jarvisfix.md"

_PHASE_RE = re.compile(
    r"^#+\s*(?:Fase|FASE)\s+(\d+)\s*[—-]\s*(.+?)\s*$", re.M
)
_RESULT_RE = re.compile(
    r"^#{3,}\s*Hasil\s+Fase\s+(\d+)\s*[—-]\s*(.+?)\s*$", re.M
)
_HEADING_RE = re.compile(r"^#{1,6}\s+", re.M)
_EVIDENCE_ORDER = (
    "source-present",
    "focused-tested",
    "runtime-wired",
    "endpoint-reachable",
    "measured",
    "live-proven",
    "unproven-live",
    "not-built",
    "blocked",
)
_EVIDENCE_RE = re.compile(
    r"(?<![\w-])(?:"
    + "|".join(re.escape(label) for label in _EVIDENCE_ORDER)
    + r")(?![\w-])",
    re.I,
)
_NEGATION_RE = re.compile(r"(?:belum|bukan|tidak|tanpa|not)$", re.I)
_DATE_SUFFIX_RE = re.compile(r"\s+\d{4}-\d{2}-\d{2}\s*$")


def _read_plan(path: Path = PLAN) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _positive_evidence(section: str) -> tuple[str, ...]:
    found: set[str] = set()
    for match in _EVIDENCE_RE.finditer(section):
        paragraph_start = section.rfind("\n\n", 0, match.start()) + 2
        paragraph_end = section.find("\n\n", match.end())
        paragraph = section[
            paragraph_start:paragraph_end if paragraph_end >= 0 else None
        ]
        if not re.search(r"\b(?:bukti|evidence)\s*:", paragraph, re.I):
            continue
        prefix = section[max(0, match.start() - 32):match.start()]
        prefix = re.sub(r"[\s`*_:'\"()—-]+$", "", prefix)
        if _NEGATION_RE.search(prefix):
            continue
        found.add(match.group(0).casefold())
    return tuple(label for label in _EVIDENCE_ORDER if label in found)


def rows(text: str) -> list[dict[str, object]]:
    """Return deterministic phase rows with only explicit evidence labels."""
    phases: dict[int, str] = {}
    for number, title in _PHASE_RE.findall(text):
        phases.setdefault(int(number), title.strip())

    results: dict[int, tuple[str, str]] = {}
    matches = list(_RESULT_RE.finditer(text))
    for index, match in enumerate(matches):
        number = int(match.group(1))
        status = _DATE_SUFFIX_RE.sub("", match.group(2).strip()).strip()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        next_heading = _HEADING_RE.search(text, match.end(), end)
        section_end = next_heading.start() if next_heading else end
        results[number] = (status, text[match.end():section_end])

    output: list[dict[str, object]] = []
    for number in sorted(phases):
        status, section = results.get(number, ("", ""))
        output.append(
            {
                "phase": number,
                "title": phases[number],
                "result": status,
                "evidence": list(_positive_evidence(section)),
            }
        )
    return output


def render(data: list[dict[str, object]]) -> str:
    lines = [
        "## Status evidence fase (dibangkitkan)",
        "",
        "| Fase | Judul | Hasil | Bukti eksplisit di bagian Hasil |",
        "|---:|---|---|---|",
    ]
    for item in data:
        evidence = ", ".join(item["evidence"]) or "—"
        result = str(item["result"] or "—").replace("|", "\\|")
        title = str(item["title"]).replace("|", "\\|")
        lines.append(
            f"| {item['phase']} | {title} | {result} | {evidence} |"
        )
    return "\n".join(lines)


def _print(text: str) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        _ = exc
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", "") or "ascii"
        print(text.encode(encoding, "replace").decode(encoding, "replace"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    data = rows(_read_plan(args.plan))
    if args.json:
        _print(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        _print(render(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
