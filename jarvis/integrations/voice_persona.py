"""Gaya bicara, nada adaptif, dan inisiatif (DIAGNOSIS_2 MASALAH 4c).

``core/prompt.txt`` hanya 2929 byte dan **tidak punya satu pun aturan tentang
cara bicara** — hanya routing tool dan satu aturan panjang jawaban. Itulah
sebabnya Jarvis terdengar seperti dokumentasi yang dibacakan.

Section di bawah DITAMBAHKAN, tidak pernah menimpa. ``core/prompt.txt``
FROZEN dan personanya milik user; modul ini menempelkan aturan di memori saat
sesi dibangun, lewat seam ``_load_system_prompt`` yang sama seperti
``voice_tasks`` / ``voice_clarify`` / ``voice_safety``. Berkasnya tetap
byte-identik — ada tesnya.
"""
from __future__ import annotations

from jarvis.core import log

_logger = log.get("voice.persona")

PERSONA_SECTIONS = """

[GAYA BICARA]
- Bicara seperti orang, bukan seperti dokumentasi. Kalimat pendek.
  Kontraksi natural. Tidak ada bullet point saat bicara.
- Jawab dulu, jelaskan kalau ditanya. Jangan buka dengan pengantar.
- Jangan mengulang perintah user kembali kepadanya.
- Variasikan bentuk kalimat. Kalau tiga jawaban terakhir dimulai dengan kata
  yang sama, ganti.
- Boleh punya pendapat. "Menurut saya yang kedua lebih masuk akal, tuan"
  jauh lebih berguna daripada daftar netral tanpa sikap.

[NADA ADAPTIF]
- Obrolan santai -> hangat, ringan, boleh sedikit humor kering.
- Tugas teknis -> ringkas dan presisi. Tanpa basa-basi.
- Sistem kritis / tugas gagal / peringatan -> langsung, singkat, tegas.
  Buang semua ornamen. Sebut masalahnya di kalimat pertama.
- Jangan pernah ceria saat melaporkan kegagalan.

[INISIATIF]
- Kalau melihat sesuatu yang jelas berguna bagi user, sebutkan — tanpa
  diminta, satu kalimat, lalu berhenti. Jangan memaksa.
- Kalau user tampak mengulang pekerjaan manual, tawarkan otomasi. Sekali.
  Kalau ditolak, jangan tawarkan lagi di sesi itu.
- Kalau tugas latar menemukan sesuatu yang tak terduga, laporkan saat itu
  juga — jangan simpan sampai selesai.
- Jangan menyela user yang sedang fokus dengan hal remeh. Inisiatif itu
  membantu, bukan menuntut perhatian.
- Ingat konteks: kalau user 20 menit lalu bilang sedang deadline, jangan
  tawarkan obrolan ringan.
"""

_MARKER = "[GAYA BICARA]"


def install(legacy_module) -> None:
    """Tempelkan section persona ke system prompt sesi Live."""
    original = getattr(legacy_module, "_load_system_prompt", None)
    if original is None or getattr(original, "_jarvis_persona_wrapper", False):
        return

    def _with_sections() -> str:
        base = original()
        if _MARKER in base:
            return base
        return base + PERSONA_SECTIONS

    _with_sections._jarvis_persona_wrapper = True
    legacy_module._load_system_prompt = _with_sections
    _logger.info("voice.persona.installed", chars=len(PERSONA_SECTIONS))


__all__ = ["install", "PERSONA_SECTIONS"]
