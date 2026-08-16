"""W5 — file_processor transcribe: bentuk contents yang diterima genai 2.x.

Regresi nyata: `actions/file_processor._process_audio` memanggil
`generate_content([prompt, {"mime_type": ..., "data": ...}])` — bentuk list
dengan dict raw ditolak validasi pydantic google-genai 2.14 (runtime:
"Input should be a valid dictionary or object..."), sehingga seluruh
transkripsi audio (termasuk pipeline video analysis) gagal-senyap.
Kontrak baru: `types.Part.from_text(...)` + `types.Part.from_bytes(...)`.
"""
from __future__ import annotations


def test_transcribe_uses_genai_parts(monkeypatch, tmp_path):
    from actions import file_processor as fp

    calls: dict[str, object] = {}

    class FakeClient:
        def generate_content(self, contents):
            calls["contents"] = contents
            return type("R", (), {"text": "hasil transkrip"})()

    monkeypatch.setattr(fp, "_gemini_client", lambda: FakeClient())
    wav = tmp_path / "s.wav"
    wav.write_bytes(b"RIFFfakewavdata")

    out = fp._process_audio(wav, "transcribe", {"save": False}, None)

    assert out == "hasil transkrip"
    parts = calls["contents"]
    assert isinstance(parts, list) and len(parts) == 2
    first, second = parts
    # genai 2.x: Part.from_text → atribut .text; bukan bytes/dict mentah.
    assert getattr(first, "text", None) is not None
    assert not isinstance(second, (bytes, bytearray))
    assert not isinstance(second, dict)
    assert hasattr(second, "inline_data")


def test_transcribe_failure_still_reports_honestly(monkeypatch, tmp_path):
    from actions import file_processor as fp

    class Broken:
        def generate_content(self, contents):
            raise RuntimeError("provider down")

    monkeypatch.setattr(fp, "_gemini_client", lambda: Broken())
    wav = tmp_path / "s2.wav"
    wav.write_bytes(b"RIFFfake")
    out = fp._process_audio(wav, "transcribe", {"save": False}, None)
    assert out.startswith("Transcription failed:")
