from pathlib import Path

from scripts import evidence_status


def test_only_positive_labels_inside_result_section_are_reported():
    text = """
## Fase 1 — feature satu

`live-proven` di bagian rencana bukan bukti.

### Hasil Fase 1 — SELESAI 2026-08-11

**Bukti:** focused-tested + runtime-wired. Belum `live-proven`.

## Fase 2 — feature dua

### Hasil Fase 2 — SELESAI 2026-08-11

**Bukti:** live-proven setelah sesi nyata.

## Fase 3 — feature tiga

### Hasil Fase 3 — SEBAGIAN 2026-08-11

**Bukti:** unproven-live; not-built.
"""

    data = evidence_status.rows(text)

    assert data[0]["evidence"] == ["focused-tested", "runtime-wired"]
    assert data[1]["evidence"] == ["live-proven"]
    assert data[2]["evidence"] == ["unproven-live", "not-built"]


def test_phase_without_result_is_visible_without_invented_evidence():
    data = evidence_status.rows("## Fase 7 — belum dikerjakan\n")

    assert data == [
        {
            "phase": 7,
            "title": "belum dikerjakan",
            "result": "",
            "evidence": [],
        }
    ]


def test_render_is_deterministic_and_escapes_table_separators():
    data = [
        {
            "phase": 2,
            "title": "A | B",
            "result": "SELESAI",
            "evidence": ["focused-tested"],
        }
    ]

    assert evidence_status.render(data) == (
        "## Status evidence fase (dibangkitkan)\n\n"
        "| Fase | Judul | Hasil | Bukti eksplisit di bagian Hasil |\n"
        "|---:|---|---|---|\n"
        "| 2 | A \\| B | SELESAI | focused-tested |"
    )


def test_real_plan_has_partial_phases_and_no_inferred_live_proof():
    text = evidence_status._read_plan(Path("jarvisfix.md"))
    data = {int(item["phase"]): item for item in evidence_status.rows(text)}

    assert data[22]["result"] == "SEBAGIAN"
    assert data[35]["result"] == "SEBAGIAN"
    assert data[38]["result"] == "SEBAGIAN"
    assert "live-proven" not in data[39]["evidence"]
    assert "live-proven" not in data[41]["evidence"]
