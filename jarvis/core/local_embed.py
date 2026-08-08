"""Embedding teks LOKAL dan instan (Fase 26).

Pengukuran Fase 24 menaruh embedding di jalur kritis setiap giliran: 3250 ms
dingin, 422 ms hangat, seluruhnya round trip jaringan ke Gemini sebelum model
ditanya apa pun. Untuk mencocokkan perintah yang berulang, jaringan adalah
biaya yang tidak perlu dibayar sama sekali.

**Batas jujur.** Ini BUKAN embedding semantik. Tidak ada model teks di repo
(hanya `yolov8n.onnx` untuk visi), dan MiniLM berarti unduhan ~90 MB —
keputusan yang bukan milik kode. Yang ada di sini leksikal: n-gram karakter
plus token kata, di-hash ke bucket tetap. Untuk perintah yang berulang dengan
variasi kecil ("pause youtube" / "tolong pause yt") itu memang cukup, dan
biayanya di bawah satu milidetik.

Antarmukanya sengaja sempit — ``embed`` dan ``similarity`` — supaya model
neural bisa menggantikannya kelak tanpa menyentuh satu pun pemanggil.

Hash memakai ``zlib.crc32``, BUKAN ``hash()`` bawaan: hash string Python
diacak ulang setiap proses, sehingga indeks yang ditulis hari ini tidak akan
cocok dengan yang dibaca setelah restart — bug yang hanya muncul setelah
proses baru, jenis yang paling mahal dilacak.
"""
from __future__ import annotations

import re
import unicodedata
import zlib

DIM = 512
_NGRAM = 3
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Kata sopan/perekat yang tidak pernah menentukan tool. Dibuang lebih dulu
# supaya "tolong bukakan kameranya" dan "buka kamera" tidak dipisahkan oleh
# kata-kata yang tidak membawa informasi apa pun.
_STOPWORDS = frozenset({
    "tolong", "coba", "please", "dong", "ya", "yah", "nih", "deh", "sih",
    "aku", "saya", "kamu", "kau", "gue", "gw", "lu",
    "di", "ke", "dari", "pada", "untuk", "buat", "dengan", "lewat", "via",
    "yang", "itu", "ini", "nya", "the", "a", "an", "to", "for", "with",
    "sekarang", "segera", "cepat", "juga", "aja", "saja", "kan", "lah",
})

# Sinonim/singkatan yang sering dipakai Takeda. Dipetakan ke satu bentuk agar
# "telpon"/"tlp" dan "telepon" bukan dua dunia terpisah.
_SYNONYMS = {
    "tlp": "telepon", "telp": "telepon", "telpon": "telepon",
    "call": "telepon", "panggil": "telepon",
    "wa": "whatsapp", "yt": "youtube", "ig": "instagram",
    "cam": "kamera", "camera": "kamera",
    "open": "buka", "close": "tutup", "play": "putar", "stop": "berhenti",
}

# Imbuhan yang hanya mengubah bentuk, bukan makna: "bukakan" → "buka",
# "kameranya" → "kamera". Diurut dari yang terpanjang.
_SUFFIXES = ("kannya", "annya", "kanlah", "nya", "kan", "lah", "an")
_PREFIXES = ("meng", "meny", "mem", "men", "peng", "pem", "ber", "ter", "di",
             "me", "pe", "se")

# Kata kerja menentukan TOOL; objek hanya menentukan sasaran. Tanpa bobot ini
# "buka kamera" dan "tutup kamera" nyaris kembar karena n-gram "kamera"
# mengalahkan satu-satunya token yang membedakannya.
_WEIGHT_TOKEN = 4.0
_WEIGHT_BIGRAM = 2.0
_WEIGHT_CHAR = 1.0


def _normalize(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(text.split())


def _stem(token: str) -> str:
    """Bentuk dasar kasar. Sengaja konservatif: kata pendek dibiarkan."""
    word = _SYNONYMS.get(token, token)
    if len(word) <= 4:
        return word
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[:-len(suffix)]
            break
    for prefix in _PREFIXES:
        if word.startswith(prefix) and len(word) - len(prefix) >= 3:
            word = word[len(prefix):]
            break
    return _SYNONYMS.get(word, word)


def tokens(text: object) -> list[str]:
    """Token bermakna dari sebuah perintah. Dipakai juga oleh pemanggil lain."""
    normalized = _normalize(text)
    result = []
    for raw in _TOKEN_RE.findall(normalized):
        if raw in _STOPWORDS:
            continue
        word = _stem(raw)
        if word and word not in _STOPWORDS:
            result.append(word)
    return result


def _features(words: list[str]):
    """Token kata (berbobot), bigram kata, dan n-gram karakter.

    Token menangkap kata kunci ("pause", "youtube"); n-gram karakter membuat
    salah ketik dan singkatan tetap berdekatan ("telpon" vs "telepon").
    """
    for token in words:
        yield "w:" + token, _WEIGHT_TOKEN
    for first, second in zip(words, words[1:]):
        yield "b:" + first + "_" + second, _WEIGHT_BIGRAM
    padded = " " + " ".join(words) + " "
    for index in range(len(padded) - _NGRAM + 1):
        yield "c:" + padded[index:index + _NGRAM], _WEIGHT_CHAR


def embed(text: object) -> list[float]:
    """Vektor ternormalisasi berdimensi ``DIM``. Tidak pernah melempar."""
    vector = [0.0] * DIM
    try:
        words = tokens(text)
        if not words:
            return vector
        for feature, weight in _features(words):
            digest = zlib.crc32(feature.encode("utf-8"))
            bucket = digest % DIM
            # Bit teratas dipakai sebagai tanda supaya fitur berbeda yang
            # jatuh di bucket sama tidak selalu saling menguatkan.
            vector[bucket] += weight if (digest >> 31) & 1 else -weight
        norm = sum(value * value for value in vector) ** 0.5
        if norm <= 0.0:
            return [0.0] * DIM
        return [value / norm for value in vector]
    except Exception:                                        # noqa: BLE001
        return [0.0] * DIM


def similarity(first, second) -> float:
    """Cosine 0..1. Vektor kosong selalu 0.0, bukan 1.0."""
    try:
        if not first or not second or len(first) != len(second):
            return 0.0
        total = sum(a * b for a, b in zip(first, second))
        return max(0.0, min(1.0, float(total)))
    except Exception:                                        # noqa: BLE001
        return 0.0


__all__ = ["DIM", "embed", "similarity", "tokens"]
