"""Document type resolution + safe extraction (Fase 4).

One parser per format — PDF via PyMuPDF, DOCX via python-docx, plain text via
read_text. Type resolution checks the extension AND the file signature, so a
renamed ``foo.docx`` that is really a legacy ``.doc`` (OLE) or a random binary
is rejected with a specific, user-friendly error instead of a silent "".

Public API:
    extract(path)            → text            (raises DocumentError)
    resolve_type(path)       → "pdf"|"docx"|"text"
    summarize_long(text, generate, max_chunk)  → hierarchical 3–5 sentence summary
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from jarvis.core import config, log

_logger = log.get("nlp.doc_extract")

_TEXT_EXT = {".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml", ".log"}
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"          # legacy .doc/.xls/.ppt


class DocumentError(Exception):
    """Typed extraction failure with a user-facing Indonesian message."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _err(code: str, msg: str) -> DocumentError:
    return DocumentError(code, msg)


def resolve_type(path: str | Path) -> str:
    """Resolve document type from extension + magic bytes. Raises DocumentError."""
    p = Path(path)
    name = p.name
    # reject traversal / weird names defensively (uploads come from the OS
    # file picker, but the path may be attacker-influenced via drag & drop)
    if ".." in name or name.strip() == "":
        raise _err("bad_name", "Nama file tidak valid.")
    if not p.is_file():
        raise _err("not_found", "File tidak ditemukan.")
    if p.stat().st_size == 0:
        raise _err("empty_file", "File kosong — tidak ada yang bisa dibaca.")

    max_mb = float(config.get("docs.max_file_mb", 25))
    if p.stat().st_size > max_mb * 1024 * 1024:
        raise _err("too_large",
                   f"File melebihi batas {max_mb:.0f} MB yang dikonfigurasi.")

    suffix = p.suffix.lower()
    with open(p, "rb") as f:
        head = f.read(8)

    if suffix == ".pdf":
        if not head.startswith(b"%PDF"):
            raise _err("corrupt_file",
                       "File berekstensi .pdf tetapi isinya bukan PDF.")
        return "pdf"

    if suffix == ".doc":
        raise _err("legacy_doc",
                   "Format .doc lama tidak didukung. Simpan ulang sebagai "
                   ".docx dari Word/LibreOffice lalu unggah kembali.")

    if suffix == ".docx":
        if head.startswith(_OLE_MAGIC):
            raise _err("legacy_doc",
                       "File ini sebenarnya dokumen .doc lama yang diganti "
                       "nama. Simpan ulang sebagai .docx.")
        if not zipfile.is_zipfile(p):
            raise _err("corrupt_file",
                       "File .docx rusak atau bukan dokumen Word yang valid.")
        try:
            with zipfile.ZipFile(p) as z:
                names = set(z.namelist())
        except zipfile.BadZipFile:
            raise _err("corrupt_file", "Struktur ZIP dokumen .docx rusak.")
        if "[Content_Types].xml" not in names or \
                not any(n.startswith("word/") for n in names):
            raise _err("corrupt_file",
                       "File berekstensi .docx tetapi bukan dokumen Word "
                       "(struktur Open XML tidak ditemukan).")
        return "docx"

    if suffix in _TEXT_EXT:
        return "text"

    raise _err("unsupported_format",
               f"Format {suffix or '(tanpa ekstensi)'} belum didukung. "
               "Gunakan PDF, DOCX, atau TXT.")


# ── per-format extractors ─────────────────────────────────────────────────────

def extract_pdf(path: str | Path) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise _err("missing_dependency",
                   "Modul PyMuPDF belum terpasang. Jalankan: pip install pymupdf")
    try:
        doc = fitz.open(str(path))
    except Exception as e:
        raise _err("corrupt_file", f"PDF tidak dapat dibuka: {str(e)[:80]}")
    if doc.needs_pass:
        doc.close()
        raise _err("encrypted", "PDF ini terenkripsi/berpassword.")
    pages = []
    for i, page in enumerate(doc, start=1):
        pages.append(f"[hal {i}]\n" + (page.get_text() or ""))
    doc.close()
    return _normalize("\n".join(pages))


def extract_docx(path: str | Path) -> str:
    """Paragraphs, headings, lists, and tables — in document order.
    Macros/embedded objects are never executed (python-docx only reads XML)."""
    try:
        import docx
        from docx.document import Document as _Doc
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError:
        raise _err("missing_dependency",
                   "Modul python-docx belum terpasang. "
                   "Jalankan: pip install python-docx")
    try:
        d = docx.Document(str(path))
    except Exception as e:
        raise _err("corrupt_file",
                   f"Dokumen Word tidak dapat dibuka: {str(e)[:80]}")

    def iter_blocks(parent):
        from docx.oxml.ns import qn
        body = parent.element.body if isinstance(parent, _Doc) else parent
        for child in body.iterchildren():
            if child.tag == qn("w:p"):
                yield Paragraph(child, parent)
            elif child.tag == qn("w:tbl"):
                yield Table(child, parent)

    lines: list[str] = []
    for block in iter_blocks(d):
        if block.__class__.__name__ == "Paragraph":
            text = block.text.strip()
            if not text:
                continue
            style = (block.style.name or "").lower() if block.style else ""
            if style.startswith("heading"):
                m = re.search(r"(\d+)", style)
                level = int(m.group(1)) if m else 1
                lines.append("#" * min(level, 6) + " " + text)
            elif "list" in style or block._p.find(
                    ".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr"
            ) is not None:
                lines.append("- " + text)
            else:
                lines.append(text)
        else:  # Table
            for row in block.rows:
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                if any(cells):
                    lines.append(" | ".join(cells))
    return _normalize("\n".join(lines))


def extract_text(path: str | Path) -> str:
    p = Path(path)
    raw = p.read_text(encoding="utf-8", errors="replace")
    return _normalize(raw)


_EXTRACTORS = {"pdf": extract_pdf, "docx": extract_docx, "text": extract_text}


def extract(path: str | Path) -> str:
    """Resolve type + extract. Raises DocumentError with a friendly message."""
    kind = resolve_type(path)
    text = _EXTRACTORS[kind](path)
    if not text.strip():
        raise _err("empty_content",
                   "Dokumen terbaca tetapi tidak berisi teks yang dapat "
                   "diekstrak (mungkin hanya gambar/scan).")
    _logger.info("doc.extracted", kind=kind, chars=len(text),
                 name=Path(path).name[:60])
    return text


def _normalize(text: str) -> str:
    """Collapse trailing spaces and >2 blank lines; keep line structure."""
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── hierarchical summarization ────────────────────────────────────────────────

_FINAL_PROMPT = (
    "Buatkan ringkasan abstraktif (3-5 kalimat) dalam Bahasa Indonesia dari "
    "teks berikut. Langsung tulis ringkasannya tanpa pembuka.\n\nTeks:\n{body}"
)
_CHUNK_PROMPT = (
    "Ringkas bagian dokumen berikut menjadi 2-3 kalimat Bahasa Indonesia, "
    "pertahankan fakta penting.\n\nBagian:\n{body}"
)


def summarize_long(text: str, generate, max_chunk: int = 8000) -> str:
    """3–5 sentence summary; hierarchical map-reduce when text is long.

    ``generate(prompt) -> str`` is injected (jarvis.core.llm.generate in prod,
    a stub in tests). Returns "" when the LLM fails — caller decides feedback.
    """
    text = text.strip()
    if len(text) <= max_chunk:
        return (generate(_FINAL_PROMPT.format(body=text)) or "").strip()

    # split on paragraph boundaries near max_chunk
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for para in text.split("\n\n"):
        if size + len(para) > max_chunk and buf:
            chunks.append("\n\n".join(buf))
            buf, size = [], 0
        buf.append(para)
        size += len(para) + 2
    if buf:
        chunks.append("\n\n".join(buf))

    partials = []
    for i, chunk in enumerate(chunks[:12]):          # hard cap: 12 LLM calls
        part = (generate(_CHUNK_PROMPT.format(body=chunk)) or "").strip()
        if part:
            partials.append(part)
        _logger.info("doc.chunk_summarized", index=i, ok=bool(part))
    if not partials:
        return ""
    return (generate(_FINAL_PROMPT.format(body="\n".join(partials))) or "").strip()
