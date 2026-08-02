"""Studio A local project model and bounded prompt intake."""
from __future__ import annotations

import pytest


def test_local_prompt_intake_accepts_bounded_text_and_never_returns_path(tmp_path):
    from jarvis.core.content_project import read_local_prompt

    prompt = tmp_path / "brief.md"
    prompt.write_text("Buat video peluncuran produk.", encoding="utf-8")
    result = read_local_prompt(prompt)
    assert result == {"ok": True, "kind": "markdown", "text": "Buat video peluncuran produk."}
    assert str(prompt) not in str(result)


@pytest.mark.parametrize("name", ["script.py", "archive.zip", "run.exe", "unknown.bin"])
def test_local_prompt_intake_rejects_unsafe_or_unknown_type(tmp_path, name):
    from jarvis.core.content_project import read_local_prompt

    path = tmp_path / name
    path.write_bytes(b"unsafe")
    assert read_local_prompt(path) == {"ok": False, "reason": "content_prompt_type_rejected"}


def test_local_prompt_intake_extracts_local_docx_and_pdf_without_source_path(tmp_path):
    from docx import Document
    import fitz
    from jarvis.core.content_project import read_local_prompt

    docx_path = tmp_path / "brief.docx"
    document = Document()
    document.add_paragraph("Brief dokumen lokal")
    document.save(docx_path)
    pdf_path = tmp_path / "brief.pdf"
    document_pdf = fitz.open()
    page = document_pdf.new_page()
    page.insert_text((72, 72), "Brief PDF lokal")
    document_pdf.save(pdf_path)
    document_pdf.close()

    assert read_local_prompt(docx_path) == {"ok": True, "kind": "document", "text": "Brief dokumen lokal"}
    assert read_local_prompt(pdf_path) == {"ok": True, "kind": "pdf", "text": "Brief PDF lokal"}
    assert str(docx_path) not in str(read_local_prompt(docx_path))
    assert str(pdf_path) not in str(read_local_prompt(pdf_path))


def test_local_prompt_intake_rejects_oversize_without_reading_text(tmp_path):
    from jarvis.core.content_project import read_local_prompt

    path = tmp_path / "large.txt"
    path.write_text("x" * 33, encoding="utf-8")
    assert read_local_prompt(path, max_bytes=32) == {"ok": False, "reason": "content_prompt_too_large"}


def test_project_scene_serializes_only_creative_fields():
    from jarvis.core.content_project import ContentProject, Scene

    project = ContentProject(
        title="Peluncuran", audience="Pengguna kreatif", tone="Cinematic",
        hook="Mulai sekarang", cta="Coba hari ini",
        scenes=(Scene("Pembuka", "Visual kota", "Narasi singkat", "neon city"),),
    )
    assert project.public_dict() == {
        "title": "Peluncuran", "audience": "Pengguna kreatif", "tone": "Cinematic",
        "hook": "Mulai sekarang", "cta": "Coba hari ini",
        "scenes": [{"title": "Pembuka", "visual": "Visual kota", "narration": "Narasi singkat", "visual_prompt": "neon city"}],
    }
    assert "path" not in str(project.public_dict()).lower()


def test_content_project_has_no_upload_browser_or_generation_authority():
    from jarvis.core import content_project

    source = open(content_project.__file__, encoding="utf-8").read()
    for forbidden in ("requests", "webbrowser", "subprocess", "upload", "image_generate", "openai", "telegram"):
        assert forbidden not in source.lower()
