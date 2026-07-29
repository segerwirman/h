"""doc_extract tests — DOCX/PDF/TXT resolution, extraction, summarization."""
import zipfile
from pathlib import Path

import pytest

from jarvis.nlp.doc_extract import (DocumentError, extract, resolve_type,
                                    summarize_long)

docx = pytest.importorskip("docx")


# ── fixtures ──────────────────────────────────────────────────────────────────

def make_docx(path: Path, *, tables=False, headings=False, lists=False,
              empty=False) -> Path:
    d = docx.Document()
    if not empty:
        if headings:
            d.add_heading("Judul Utama", level=1)
            d.add_heading("Sub Bab", level=2)
        d.add_paragraph("Paragraf pertama tentang JARVIS.")
        d.add_paragraph("Paragraf kedua berisi detail teknis.")
        if lists:
            d.add_paragraph("Item satu", style="List Bullet")
            d.add_paragraph("Item dua", style="List Number")
        if tables:
            t = d.add_table(rows=2, cols=2)
            t.cell(0, 0).text = "Nama"
            t.cell(0, 1).text = "Nilai"
            t.cell(1, 0).text = "CPU"
            t.cell(1, 1).text = "42%"
    d.save(str(path))
    return path


# ── DOCX ──────────────────────────────────────────────────────────────────────

def test_docx_normal(tmp_path):
    p = make_docx(tmp_path / "doc.docx")
    text = extract(p)
    assert "Paragraf pertama tentang JARVIS." in text
    assert "Paragraf kedua" in text


def test_docx_with_table(tmp_path):
    p = make_docx(tmp_path / "t.docx", tables=True)
    text = extract(p)
    assert "CPU | 42%" in text


def test_docx_headings_and_lists(tmp_path):
    p = make_docx(tmp_path / "h.docx", headings=True, lists=True)
    text = extract(p)
    assert "# Judul Utama" in text
    assert "## Sub Bab" in text
    assert "- Item satu" in text


def test_docx_empty(tmp_path):
    p = make_docx(tmp_path / "e.docx", empty=True)
    with pytest.raises(DocumentError) as ei:
        extract(p)
    assert ei.value.code == "empty_content"


def test_docx_corrupt(tmp_path):
    p = tmp_path / "bad.docx"
    p.write_bytes(b"PK\x03\x04 this is not a real zip content at all")
    with pytest.raises(DocumentError) as ei:
        extract(p)
    assert ei.value.code == "corrupt_file"


def test_legacy_doc_rejected(tmp_path):
    p = tmp_path / "old.doc"
    p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)
    with pytest.raises(DocumentError) as ei:
        extract(p)
    assert ei.value.code == "legacy_doc"


def test_doc_renamed_to_docx_rejected(tmp_path):
    p = tmp_path / "fake.docx"
    p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100)
    with pytest.raises(DocumentError) as ei:
        extract(p)
    assert ei.value.code == "legacy_doc"


def test_zip_but_not_docx_rejected(tmp_path):
    p = tmp_path / "notword.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("hello.txt", "hi")
    with pytest.raises(DocumentError) as ei:
        extract(p)
    assert ei.value.code == "corrupt_file"


def test_uppercase_extension(tmp_path):
    p = make_docx(tmp_path / "UPPER.DOCX")
    assert resolve_type(p) == "docx"
    assert "Paragraf pertama" in extract(p)


def test_unicode_and_space_filename(tmp_path):
    p = make_docx(tmp_path / "laporan akhir — versi ‘final’ 完成.docx")
    assert "Paragraf pertama" in extract(p)


# ── other formats ─────────────────────────────────────────────────────────────

def test_txt(tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("baris satu\n\n\n\nbaris dua   \n", encoding="utf-8")
    text = extract(p)
    assert "baris satu" in text and "baris dua" in text
    assert "\n\n\n" not in text                      # normalized


def test_pdf_roundtrip(tmp_path):
    fitz = pytest.importorskip("fitz")
    p = tmp_path / "doc.pdf"
    d = fitz.open()
    page = d.new_page()
    page.insert_text((72, 72), "Halaman uji PDF JARVIS")
    d.save(str(p))
    d.close()
    text = extract(p)
    assert "[hal 1]" in text
    assert "Halaman uji PDF JARVIS" in text


def test_pdf_wrong_signature(tmp_path):
    p = tmp_path / "fake.pdf"
    p.write_bytes(b"not a pdf at all")
    with pytest.raises(DocumentError) as ei:
        extract(p)
    assert ei.value.code == "corrupt_file"


def test_empty_file(tmp_path):
    p = tmp_path / "zero.docx"
    p.write_bytes(b"")
    with pytest.raises(DocumentError) as ei:
        extract(p)
    assert ei.value.code == "empty_file"


def test_unsupported_format(tmp_path):
    p = tmp_path / "x.exe"
    p.write_bytes(b"MZ....")
    with pytest.raises(DocumentError) as ei:
        extract(p)
    assert ei.value.code == "unsupported_format"


def test_too_large(tmp_path, monkeypatch):
    from jarvis.core import config
    monkeypatch.setattr(config, "get",
                        lambda k, d=None: 0.0001 if k == "docs.max_file_mb" else d)
    p = tmp_path / "big.txt"
    p.write_text("x" * 10000, encoding="utf-8")
    with pytest.raises(DocumentError) as ei:
        extract(p)
    assert ei.value.code == "too_large"


# ── summarization ─────────────────────────────────────────────────────────────

def test_summarize_short_single_call():
    calls = []
    def gen(prompt):
        calls.append(prompt)
        return "Ringkasan singkat."
    assert summarize_long("teks pendek", gen) == "Ringkasan singkat."
    assert len(calls) == 1


def test_summarize_long_hierarchical():
    calls = []
    def gen(prompt):
        calls.append(prompt)
        return "Ringkasan bagian." if "Bagian:" in prompt else "Ringkasan akhir."
    text = "\n\n".join(f"Paragraf {i} " + "kata " * 200 for i in range(30))
    out = summarize_long(text, gen, max_chunk=2000)
    assert out == "Ringkasan akhir."
    assert len(calls) > 2                            # chunks + final


def test_summarize_llm_failure_returns_empty():
    assert summarize_long("teks pendek", lambda p: "") == ""
    long_text = "kata " * 5000
    assert summarize_long(long_text, lambda p: "", max_chunk=2000) == ""


def test_read_document_ex_wrapper(tmp_path):
    from jarvis.nlp.document import read_document, read_document_ex
    p = make_docx(tmp_path / "w.docx")
    text, err = read_document_ex(str(p))
    assert err is None and "Paragraf pertama" in text
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"garbage")
    text, err = read_document_ex(str(bad))
    assert text == "" and err
    assert read_document(str(bad)) == ""
