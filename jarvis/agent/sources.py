"""Sumber rekomendasi yang bertipe dan bisa dibuka (Fase 23, S-23).

Takeda meminta: saat Jarvis memberi rekomendasi, tawarkan menampilkan
informasinya di Chrome — web, media sosial, atau peta. **Bukan** menampilkan
apa yang ia ucapkan.

Yang terjadi sebelumnya, terbukti dari judul jendela Chrome-nya:

    'kan saya restoran yang - Search - Google Chrome'

``run_search`` jatuh ke transkrip mentah lalu mengirimnya ke browser sistem
sebagai kueri pencarian. Yang muncul di layar adalah kalimat user, bukan
sumber apa pun.

Aturan modul ini: **setiap URL dibangun dari HASIL TOOL, tidak pernah dari
kata-kata user.** Bila tidak ada hasil, tidak ada yang dibuka — diam lebih
jujur daripada memantulkan ucapan kembali ke layar.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote_plus, urlparse

from jarvis.core import log

_logger = log.get("agent.sources")

KINDS = ("map", "social", "web")

_SOCIAL_HOSTS = (
    "instagram.com", "tiktok.com", "facebook.com", "fb.com", "twitter.com",
    "x.com", "youtube.com", "youtu.be", "threads.net", "linkedin.com",
    "pinterest.com",
)
_MAP_HOSTS = ("maps.google.", "google.com/maps", "goo.gl/maps",
              "maps.app.goo.gl", "waze.com", "openstreetmap.org")

# Permintaan yang menyiratkan TEMPAT fisik: di situ peta adalah sumber yang
# benar (lokasi, jam buka, rating) — bukan halaman hasil pencarian.
_PLACE_RE = re.compile(
    r"\b(?:restoran|resto|rumah\s+makan|warung|warteg|kafe|cafe|kedai|"
    r"tempat\s+makan|tempat\s+ngopi|coffee\s+shop|angkringan|depot|"
    r"bakso|soto|sate|nasi\s+goreng|seafood|kuliner|makan(?:an)?\s+"
    r"(?:enak|dekat|terdekat)|tempat\s+(?:nongkrong|wisata)|hotel|"
    r"apotek|rumah\s+sakit|spbu|atm|minimarket)\b"
    r"|\b(?:terdekat|dekat\s+sini|sekitar\s+sini|di\s+sekitar)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourceCandidate:
    kind: str
    title: str
    url: str


def classify(url: str) -> str:
    """``map`` / ``social`` / ``web`` berdasarkan host, bukan tebakan kata."""
    value = str(url or "").strip().casefold()
    if not value:
        return "web"
    if any(marker in value for marker in _MAP_HOSTS):
        return "map"
    host = (urlparse(value).netloc or "").split(":", 1)[0]
    host = host[4:] if host.startswith("www.") else host
    if any(host == h or host.endswith("." + h) for h in _SOCIAL_HOSTS):
        return "social"
    return "web"


# Kata benda yang menggeser maksud dari TEMPAT ke KONTEN. "cari resep warung
# bu tini" memuat "warung", tetapi yang dicari resepnya — peta bukan jawabannya.
_CONTENT_RE = re.compile(
    r"\b(?:resep|harga|menu(?:nya)?|review|ulasan|sejarah|cara\s+(?:buat|"
    r"masak|bikin)|kalori|nutrisi|arti|profil)\b",
    re.IGNORECASE,
)
# Kedekatan selalu berarti tempat, apa pun kata lainnya.
_PROXIMITY_RE = re.compile(
    r"\b(?:terdekat|dekat\s+sini|dekat\s+saya|sekitar\s+sini|di\s+sekitar|"
    r"nearby|near\s+me)\b",
    re.IGNORECASE,
)


def is_place_request(task: str) -> bool:
    """Apakah yang dicari sebuah TEMPAT?

    Kata seperti "warung" muncul juga pada permintaan konten ("cari resep
    warung bu tini"). Membuka peta untuk itu salah sasaran, jadi kata benda
    konten membatalkan pembacaan tempat — kecuali ada penanda kedekatan, yang
    selalu berarti lokasi.
    """
    text = str(task or "")
    if _PROXIMITY_RE.search(text):
        return True
    if _CONTENT_RE.search(text):
        return False
    return bool(_PLACE_RE.search(text))


def from_search_rows(rows) -> list[SourceCandidate]:
    """Kandidat sumber dari baris hasil pencarian. Hanya dari hasil tool."""
    out: list[SourceCandidate] = []
    seen: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("href") or row.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        out.append(SourceCandidate(classify(url),
                                   str(row.get("title") or "")[:160], url))
    return out


def _place_name(rows) -> str:
    """Nama tempat dari JUDUL hasil tool — bukan dari ucapan user."""
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        title = " ".join(str(row.get("title") or "").split())
        if not title:
            continue
        # Buang ekor yang bukan bagian nama ("- Google Maps", "| Instagram").
        title = re.split(r"\s+[-|–—]\s+", title)[0].strip()
        if title:
            return title[:80]
    return ""


def maps_source(place: str) -> SourceCandidate | None:
    name = " ".join(str(place or "").split())
    if not name:
        return None
    return SourceCandidate(
        "map", f"{name} di Maps",
        "https://www.google.com/maps/search/?api=1&query="
        + quote_plus(name))


def rank(rows, task: str = "") -> list[SourceCandidate]:
    """Urutkan kandidat sesuai jenis permintaan.

    Untuk permintaan tempat, peta didahulukan — dan bila hasil tool tidak
    memuat baris Maps sama sekali, satu sumber peta DISINTESIS dari nama
    tempat pada judul hasil. Yang disintesis tetap berasal dari hasil tool;
    kalimat user tidak pernah menjadi kueri.
    """
    candidates = from_search_rows(rows)
    if not candidates:
        return []

    place = is_place_request(task)
    if place and not any(item.kind == "map" for item in candidates):
        synthetic = maps_source(_place_name(rows))
        if synthetic is not None:
            candidates.insert(0, synthetic)

    order = {"map": 0, "web": 1, "social": 2} if place else \
            {"web": 0, "map": 1, "social": 2}
    return sorted(candidates, key=lambda item: order.get(item.kind, 3))


_KIND_LABEL = {"map": "peta lokasinya", "social": "media sosialnya",
               "web": "halaman resminya"}


def offer_text(candidates: list[SourceCandidate]) -> str:
    """Tawaran, bukan aksi. Takeda meminta OPSI, bukan tab yang tiba-tiba."""
    if not candidates:
        return ""
    kinds: list[str] = []
    for item in candidates:
        label = _KIND_LABEL.get(item.kind)
        if label and label not in kinds:
            kinds.append(label)
    if not kinds:
        return ""
    listed = kinds[0] if len(kinds) == 1 else (
        ", ".join(kinds[:-1]) + f", atau {kinds[-1]}")
    return f"Mau saya buka {listed} di Chrome Anda?"


def open_source(candidate: SourceCandidate) -> dict:
    """Buka satu sumber di Chrome USER (Fase 21), bukan di browser agent."""
    from jarvis.integrations import user_browser

    state = user_browser.status()
    if not state.get("attached"):
        return {"ok": False, "where": "user_browser",
                "reason": str(state.get("reason") or
                              "Chrome Anda belum bisa dijangkau.")}
    result = user_browser.open_url(candidate.url)
    if not result.get("ok"):
        return {"ok": False, "where": "user_browser",
                "reason": str(result.get("reason") or "gagal membuka")}
    _logger.info("sources.opened", kind=candidate.kind)
    return {"ok": True, "where": "user_browser", "url": candidate.url,
            "kind": candidate.kind}


__all__ = ["KINDS", "SourceCandidate", "classify", "from_search_rows",
           "is_place_request", "maps_source", "offer_text", "open_source",
           "rank"]
