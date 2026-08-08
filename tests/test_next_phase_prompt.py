"""Prompt lanjutan harus lahir dari KEADAAN REPO, bukan dari ingatan.

Prompt yang ditulis tangan membeku pada saat ia ditulis: setelah dua fase ia
menyebut fase yang sudah selesai sebagai "berikutnya" dan temuan yang sudah
tertutup sebagai "terbuka" — dan agent berikutnya mempercayainya. Uji-uji di
sini menjaga satu hal: apa pun yang dicetak harus bisa ditelusuri ke
`jarvisfix.md` atau ke git, dan tidak ada hasil uji yang diklaim.
"""
from __future__ import annotations

from scripts import next_phase_prompt as generator


PLAN = """
| 18 | Baris tabel yang menyebut S-3 dan menunggu | ✅ **SELESAI** |
| 22 | Baris tabel lain yang menyebut S-22 dan menunggu sesi nyata |

## Fase 39 — Fase lama yang ditandai selesai di judulnya — SELESAI ✅

## Fase 40 — Fase yang sudah selesai

### Hasil Fase 40 — SELESAI 2026-08-08

Sudah dikerjakan.

## Fase 41 — Fase yang belum dikerjakan

Rencana saja.

## Fase 42 — Fase yang diukur lalu ditutup

### Hasil Fase 42 — DIUKUR, TIDAK DIBANGUN 2026-08-08

## T9 — sesuatu yang rusak — TERBUKA

## T10 — sesuatu yang beres — SELESAI

S-99 masih TERBUKA dan belum diperbaiki.
"""


def test_a_phase_with_a_result_is_not_offered_again():
    numbers = [number for number, _, _ in generator.open_phases(PLAN)]

    assert 40 not in numbers, "fase yang sudah selesai ditawarkan lagi"
    assert 41 in numbers


def test_a_phase_closed_without_being_built_is_also_done():
    """"DIUKUR, TIDAK DIBANGUN" adalah keputusan, bukan pekerjaan tertunda."""
    numbers = [number for number, _, _ in generator.open_phases(PLAN)]

    assert 42 not in numbers


def test_phase_titles_survive_into_the_prompt():
    titles = {number: title for number, title, _ in generator.phases(PLAN)}

    assert titles[41] == "Fase yang belum dikerjakan"


def test_only_findings_marked_open_are_listed():
    findings = " | ".join(generator.open_findings(PLAN))

    assert "T9" in findings
    assert "S-99" in findings
    assert "T10" not in findings, "temuan yang sudah selesai ikut terbawa"


def test_summary_table_rows_are_not_mistaken_for_open_findings():
    """Baris tabel memuat nomor temuan DAN kata "menunggu" pada baris yang
    justru bertanda SELESAI. Ditemukan dengan MENJALANKAN skripnya.
    """
    findings = generator.open_findings(PLAN)

    assert not any(item.startswith("|") for item in findings), findings
    assert not any("SELESAI" in item for item in findings), findings


def test_a_phase_marked_done_in_its_own_title_is_not_offered_again():
    """Fase 0-13 menandai selesai di judul, bukan lewat bagian "Hasil".

    Membaca hanya satu bentuk membuat 14 fase yang sudah beres ditawarkan lagi.
    """
    numbers = [number for number, _, _ in generator.open_phases(PLAN)]

    assert 39 not in numbers


def test_the_real_plan_has_almost_nothing_left_open():
    """Penjaga terhadap parser yang terlalu longgar ATAU terlalu ketat.

    Setelah Siklus 5, hampir semua fase punya penanda selesai. Kalau angka ini
    melonjak, parsernya yang rusak — bukan pekerjaannya yang bertambah.
    """
    pending = generator.open_phases(generator._text())

    assert len(pending) <= 3, [f"Fase {n}" for n, _, _ in pending]


def test_the_prompt_never_claims_a_test_result():
    """Menyalin "2593 lulus" dari kemarin ke prompt hari ini adalah klaim palsu.

    Prompt hanya boleh mencetak PERINTAH yang harus dijalankan.
    """
    prompt = generator.build()

    assert "pytest" in prompt, "perintah verifikasinya harus ada"
    for claim in ("lulus", "passed", "hijau semua", "sudah diverifikasi"):
        assert f"{claim} in" not in prompt
    assert not any(token in prompt for token in ("2593 lulus", "passed in"))


def test_the_prompt_points_at_the_plan_document():
    prompt = generator.build()

    assert "jarvisfix.md" in prompt


def test_the_prompt_names_the_verification_commands():
    prompt = generator.build()

    assert "ruff check" in prompt
    assert "verify_frozen" in prompt


def test_the_full_variant_spells_out_the_method():
    prompt = generator.build(codex=False)

    assert "UKUR DULU" in prompt
    assert "MERAH" in prompt
    assert "FROZEN" in prompt


def test_the_codex_variant_is_shorter_but_keeps_the_hard_rules():
    """Agent lain tetap harus tahu batasnya, sependek apa pun promptnya."""
    full = generator.build(codex=False)
    codex = generator.build(codex=True)

    assert len(codex) < len(full)
    assert "FROZEN" in codex
    assert "jarvisfix.md" in codex


def test_the_prompt_warns_about_uncommitted_work(monkeypatch):
    monkeypatch.setattr(generator, "_git",
                        lambda *args: "M berkas.py" if args[0] == "status" else "")

    assert "belum bersih" in generator.build()


def test_it_survives_a_missing_plan_file(monkeypatch, tmp_path):
    """Tidak boleh meledak di mesin yang belum punya dokumennya."""
    monkeypatch.setattr(generator, "PLAN", tmp_path / "tidak_ada.md")

    prompt = generator.build()

    assert "jarvisfix.md" in prompt


def test_it_reports_when_no_phase_is_left():
    assert generator.open_phases("## Fase 1 — x\n\n### Hasil Fase 1 — SELESAI\n") == []


def test_the_real_plan_parses():
    """Dijalankan terhadap jarvisfix.md yang sungguhan, bukan contoh."""
    text = generator._text()

    assert text, "jarvisfix.md tidak terbaca"
    assert len(generator.phases(text)) >= 29


def test_printing_survives_a_narrow_console(capsys, monkeypatch):
    """Judul fase memuat "✅"; konsol Windows default cp1252 dan melempar.

    Alat yang dijalankan setiap selesai fase tidak boleh gagal mencetak
    keluarannya sendiri.
    """
    attempts: list[str] = []

    def narrow_print(text):
        attempts.append(text)
        if len(attempts) == 1:
            raise UnicodeEncodeError("charmap", "✅", 0, 1, "tidak bisa")

    monkeypatch.setattr("builtins.print", narrow_print)

    generator._print("selesai ✅ dan seterusnya")

    assert len(attempts) == 2, "tidak ada percobaan kedua setelah gagal"
    assert "selesai" in attempts[1], "isinya harus tetap terbaca"
    assert "dan seterusnya" in attempts[1], "cetakan kedua tidak boleh terpotong"


def test_the_command_line_runs_end_to_end():
    """Dijalankan sungguhan, karena inilah satu-satunya cara ia dipakai."""
    assert generator.main([]) == 0
    assert generator.main(["--codex"]) == 0
