"""Jawaban konfirmasi lewat suara (Fase 15, temuan S-2).

``UIAdapter.ask`` menunggu event BUS ``confirm``/``cancel``. Satu-satunya
penerbitnya adalah kata yang DIKETIK dan gestur jempol, sehingga perintah suara
yang menyentuh tool berkonfirmasi memaksa user pindah ke keyboard di tengah
percakapan suara.

Modul ini hanya memutuskan **apakah satu ucapan adalah jawaban tegas**. Ia
tidak menerbitkan apa pun, tidak menyentuh audio, dan tidak tahu tentang agent
— pemanggilnya yang memegang gerbang "apakah sedang ada pertanyaan".

Aturan ketat disengaja: hanya ucapan yang SELURUHNYA berupa jawaban yang
dihitung. Menyetujui aksi eksternal dari "ya sudah jangan jadi" jauh lebih
buruk daripada bertanya sekali lagi.
"""
from __future__ import annotations

import re
import unicodedata

from jarvis.core import config

CONFIRM = "confirm"
CANCEL = "cancel"

_DEFAULT_YES: tuple[str, ...] = (
    "ya", "iya", "iyah", "yes", "yep", "ok", "oke", "okay", "baik", "boleh",
    "benar", "betul", "setuju", "lanjut", "lanjutkan", "silakan", "silahkan",
    "gas", "jalan", "kerjakan", "confirm", "konfirmasi",
)
_DEFAULT_NO: tuple[str, ...] = (
    "tidak", "nggak", "enggak", "gak", "ga", "no", "nope", "jangan", "batal",
    "batalkan", "stop", "berhenti", "cancel", "tunda", "nanti",
    # Penolakan dua kata yang lazim diucapkan; dicocokkan sebagai frasa utuh
    # sebelum ucapan dipecah menjadi token.
    "ga usah", "gak usah", "nggak usah", "tidak usah", "batalkan aksi",
    "jangan dulu", "nanti saja", "lain kali",
)

# Sapaan yang boleh menempel pada jawaban tanpa mengubah maknanya.
_VOCATIVES = frozenset({
    "sir", "pak", "bos", "jarvis", "bro", "mas", "bu", "kak",
})
_FILLERS = frozenset({"tolong", "please", "aja", "saja", "dong", "deh", "ya"})
_PUNCT_RE = re.compile(r"[.!?,;:]+$")


def _words(path: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    try:
        raw = config.get(path, None)
    except Exception:                                        # noqa: BLE001
        raw = None
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)) or not raw:
        return fallback
    values = tuple(
        " ".join(str(item or "").split()).casefold()
        for item in raw if str(item or "").strip()
    )
    return values or fallback


def _normalize(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKC", value).casefold().strip()
    text = _PUNCT_RE.sub("", text)
    return " ".join(text.split())


def decide(spoken: object) -> str | None:
    """``"confirm"`` / ``"cancel"`` / ``None`` untuk satu ucapan. Tidak pernah
    melempar — dipanggil dari jalur suara yang tidak boleh mati."""
    try:
        text = _normalize(spoken)
        if not text:
            return None

        yes = _words("agent.confirm.voice_yes", _DEFAULT_YES)
        no = _words("agent.confirm.voice_no", _DEFAULT_NO)

        # Frasa multi-kata yang persis (mis. "batalkan aksi") dinilai lebih
        # dulu, sebelum ucapan dipecah menjadi token.
        if text in no:
            return CANCEL
        if text in yes:
            return CONFIRM

        tokens = [token for token in text.split()
                  if token not in _VOCATIVES]
        if not tokens:
            return None

        head, tail = tokens[0], tokens[1:]
        # Sisa kata hanya boleh berupa pengisi. "ya" boleh diikuti "sir",
        # tetapi "ya sudah jangan jadi" adalah kalimat, bukan jawaban.
        if any(token not in _FILLERS for token in tail):
            return None
        if head in no:
            return CANCEL
        if head in yes:
            return CONFIRM
        return None
    except Exception:                                        # noqa: BLE001
        return None


__all__ = ["CANCEL", "CONFIRM", "decide"]
