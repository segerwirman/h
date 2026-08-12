"""``clarify`` untuk sesi Gemini Live — TANPA mengubah main.py atau prompt.txt.

DIAGNOSIS_2 MASALAH 2 membuktikan dua hal:

* ``clarify`` ada (``jarvis/agent/tools/clarify.py:18``) tapi **tidak ada di
  TOOL_DECLARATIONS**, jadi lane suara tidak punya cara bertanya balik;
* ``core/prompt.txt`` justru menyuruh sebaliknya di baris terakhirnya —
  *"CRITICAL: Speak/Take action immediately based on available info. Assume
  and proceed."*

Deklarasi, aturan prompt, dan handler tetap dimiliki modul ini. Komposisi ke
pipeline Live dilakukan oleh ``voice_native_tools`` agar lane suara hanya punya
satu wrapper dispatch. **main.py dan core/prompt.txt tidak disentuh** —
verify_frozen tetap hijau dan persona user tetap byte-identik.

Kenapa tidak memakai schema registry seperti voice_tasks: tool ``clarify``
milik agent memanggil ``adapter.ask()`` dan **menunggu** jawaban
(``clarify.py:37``, timeout 330 dtk). Di sesi Live tidak ada adapter, dan
menunggu di dalam tool akan membekukan giliran suara. Di sini modelnya cukup
diberi tahu "ajukan pertanyaan ini", lalu ia yang mengucapkannya — pertanyaan
disimpan ke ``clarify_state`` supaya jawaban berikutnya bisa dipetakan dan
preferensinya dipelajari.
"""
from __future__ import annotations

from jarvis.core import log

_logger = log.get("voice.clarify")

CLARIFY_TOOL_NAMES = frozenset({"clarify"})

_DECLARATION = {
    "name": "clarify",
    "description": (
        "Tanya balik ke user saat perintahnya ambigu atau kamu tidak yakin. "
        "PAKAI INI daripada menebak. Lebih baik bertanya satu kalimat "
        "singkat daripada melakukan hal yang salah. "
        "Contoh wajib pakai: nama yang bisa berarti aplikasi ATAU situs; "
        "nama berkas yang cocok beberapa; perintah destruktif tanpa target "
        "yang jelas."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "question": {
                "type": "STRING",
                "description": "Pertanyaan singkat, natural, satu kalimat",
            },
            "options": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "2-3 pilihan konkret",
            },
            "topic": {
                "type": "STRING",
                "description": (
                    "Nama yang sedang ditanyakan, mis. 'instagram' — dipakai "
                    "untuk mengingat jawaban user agar tidak bertanya lagi"
                ),
            },
        },
        "required": ["question"],
    },
}

_AMBIGUITY_RULES = """

[SAAT RAGU — BERTANYA, JANGAN MENEBAK]
- Perintah ambigu -> clarify. Satu kalimat, natural, bukan formulir.
  BENAR : "Aplikasi Instagram atau buka di browser?"
  SALAH : "Mohon spesifikasikan target: [1] aplikasi [2] browser"
- Jangan pernah bertanya dua kali untuk hal yang sama dalam satu sesi —
  jawaban user diingat otomatis lewat parameter `topic` pada clarify.
- Perintah destruktif tanpa target jelas (tutup/hapus/matikan sesuatu yang
  tidak disebutkan namanya) -> SELALU clarify dulu.
- Kalau user sudah eksplisit ("app"/"aplikasi" atau "situs"/"website"),
  JANGAN bertanya lagi. Bertanya saat sudah jelas sama menyebalkannya
  dengan menebak salah.
"""

def declarations() -> list[dict]:
    return [dict(_DECLARATION)]


def apply_to_prompt(base: str) -> str:
    """Tambahkan aturan ambiguitas tepat sekali tanpa mengubah persona dasar."""
    return base if "[SAAT RAGU" in base else base + _AMBIGUITY_RULES


def handle(args: dict) -> str:
    """Catat pertanyaan, kembalikan instruksi agar model mengucapkannya.

    Tidak memblokir: jawaban user datang sebagai giliran suara berikutnya dan
    ditafsirkan ``clarify_state`` / ``window._handle_clarify_answer``.
    """
    from jarvis.core import clarify_state

    question = str(args.get("question") or "").strip()
    if not question:
        return "Tidak ada pertanyaan yang diberikan; ajukan pertanyaan singkat."
    options = [str(o) for o in (args.get("options") or []) if str(o).strip()]
    topic = str(args.get("topic") or "").strip()

    clarify_state.set_pending(topic=topic, question=question, options=options)
    _logger.info("voice.clarify.asked", topic=topic[:40])

    hint = f" Pilihan: {', '.join(options)}." if options else ""
    return (f"Ajukan pertanyaan ini ke user sekarang, persis satu kalimat, "
            f"dengan nada natural: \"{question}\".{hint} "
            f"Jangan melakukan tindakan apa pun sampai user menjawab.")


__all__ = ["CLARIFY_TOOL_NAMES", "apply_to_prompt", "declarations", "handle"]
