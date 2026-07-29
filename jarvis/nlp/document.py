"""DocumentAnalysis — ingest PDF/DOCX/TXT/code, chunk, retrieve, answer
grounded in the document with page/line citations (Part 5).

Embeddings use the Gemini embedding endpoint when reachable; otherwise a
keyword-overlap retriever keeps the module functional offline.
"""
from __future__ import annotations

import asyncio
import math
import re
from pathlib import Path

from jarvis.core import config, llm, log
from jarvis.nlp.base import Context, Response

_logger = log.get("nlp.document")

_CODE_EXT = {".py", ".js", ".ts", ".java", ".c", ".cpp", ".cs", ".go", ".rs",
             ".rb", ".php", ".html", ".css", ".sql", ".sh", ".lua", ".kt"}


def read_document_ex(path: str) -> tuple[str, str | None]:
    """Text extraction via doc_extract. Returns (text, error_message).
    Exactly one of the pair is meaningful: error_message is None on success.
    Page markers ``[hal N]`` / line markers survive into chunks for citation."""
    from jarvis.nlp.doc_extract import DocumentError, extract
    p = Path(path)
    suffix = p.suffix.lower()
    try:
        if suffix in _CODE_EXT:
            raw = p.read_text(encoding="utf-8", errors="replace")
            lines = raw.splitlines()
            return "\n".join(f"{i+1:5d}| {l}" for i, l in enumerate(lines)), None
        return extract(path), None
    except DocumentError as e:
        _logger.warning("document.read_rejected", path=str(path)[-80:],
                        code=e.code)
        return "", e.message
    except Exception as e:
        _logger.error("document.read_failed", path=str(path)[-80:],
                      error=str(e)[:120])
        return "", "Terjadi kesalahan internal saat membaca dokumen."


def read_document(path: str) -> str:
    """Backward-compatible wrapper: '' on any failure."""
    text, _ = read_document_ex(path)
    return text


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    chunks = []
    i = 0
    while i < len(text):
        chunks.append(text[i:i + size])
        i += max(1, size - overlap)
    return chunks


_WORD_RE = re.compile(r"[\w']+")


def _keyword_scores(query: str, chunks: list[str]) -> list[float]:
    q = set(w.lower() for w in _WORD_RE.findall(query))
    scores = []
    for c in chunks:
        words = set(w.lower() for w in _WORD_RE.findall(c))
        scores.append(len(q & words) / (math.sqrt(len(q) or 1)))
    return scores


class DocumentAnalysis:
    name = "DocumentAnalysis"

    def __init__(self) -> None:
        d = config.section("nlp.document")
        self._chunk_chars = int(d.get("chunk_chars", 1600))
        self._overlap = int(d.get("chunk_overlap", 200))
        self._top_k = int(d.get("top_k", 5))
        self._cache: dict[str, list[str]] = {}
        self._embed_cache: dict[str, list] = {}

    def can_handle(self, text: str, ctx: Context) -> float:
        if not ctx.uploaded_file:
            return 0.0
        t = text.lower()
        doc_words = ("dokumen", "file", "pdf", "halaman", "document", "berkas",
                     "isi", "baris", "kode ini", "this file", "the doc")
        if any(w in t for w in doc_words):
            return 0.9
        # a question while a doc is loaded is probably about the doc
        if "?" in text or t.startswith(("apa", "siapa", "kapan", "berapa",
                                        "jelaskan", "what", "who", "when",
                                        "how", "explain", "why")):
            return 0.7
        return 0.0

    async def handle(self, text: str, ctx: Context) -> Response:
        path = ctx.uploaded_file or ""
        chunks = self._cache.get(path)
        if chunks is None:
            raw = await asyncio.to_thread(read_document, path)
            if not raw.strip():
                return Response(
                    "Saya tidak dapat membaca dokumen ini — format tidak "
                    "didukung atau modul pembacanya belum terpasang.",
                    source=self.name)
            chunks = chunk_text(raw, self._chunk_chars, self._overlap)
            self._cache[path] = chunks

        top = await asyncio.to_thread(self._retrieve, text, chunks)
        context_block = "\n\n---\n\n".join(top)
        prompt = (
            "Jawab pertanyaan HANYA berdasarkan potongan dokumen berikut. "
            "Kutip nomor halaman ([hal N]) atau nomor baris (NNN|) yang ada "
            "di potongan sebagai sitasi. Jika jawabannya tidak ada di "
            "dokumen, katakan demikian.\n\n"
            f"Potongan dokumen dari {Path(path).name}:\n{context_block}\n\n"
            f"Pertanyaan: {text}"
        )
        out = await asyncio.to_thread(llm.generate, prompt)
        return Response(out or "Analisis dokumen tidak tersedia.",
                        show_on_stage=True, source=self.name,
                        meta={"file": path})

    # ── retrieval: embeddings when possible, keyword overlap otherwise ──────

    def _retrieve(self, query: str, chunks: list[str]) -> list[str]:
        try:
            scores = self._embed_scores(query, chunks)
        except Exception:
            scores = None
        if scores is None:
            scores = _keyword_scores(query, chunks)
        ranked = sorted(zip(scores, range(len(chunks))), reverse=True)
        return [chunks[i] for _, i in ranked[:self._top_k]]

    def _embed_scores(self, query: str, chunks: list[str]) -> list[float] | None:
        from google import genai  # noqa: F401
        client_key = llm.api_key()
        if not client_key:
            return None
        from google import genai as _genai
        client = _genai.Client(api_key=client_key)
        key = str(hash(tuple(chunks)))
        if key not in self._embed_cache:
            res = client.models.embed_content(
                model="text-embedding-004", contents=chunks[:100])
            self._embed_cache = {key: [e.values for e in res.embeddings]}
        chunk_vecs = self._embed_cache[key]
        qres = client.models.embed_content(model="text-embedding-004",
                                           contents=[query])
        qv = qres.embeddings[0].values

        def cos(a, b):
            num = sum(x * y for x, y in zip(a, b))
            da = math.sqrt(sum(x * x for x in a)) or 1e-9
            db = math.sqrt(sum(x * x for x in b)) or 1e-9
            return num / (da * db)

        scores = [cos(qv, cv) for cv in chunk_vecs]
        scores += [0.0] * (len(chunks) - len(scores))
        return scores
