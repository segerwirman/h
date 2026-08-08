"""Terbitkan prompt lanjutan dari KEADAAN REPO, bukan dari ingatan.

Dijalankan setelah sebuah fase selesai::

    python scripts/next_phase_prompt.py            # prompt lanjutan
    python scripts/next_phase_prompt.py --codex    # varian ringkas untuk Codex

Kenapa sebuah skrip dan bukan template yang disalin tangan: prompt yang ditulis
manual selalu membeku pada saat ia ditulis. Setelah dua fase ia menyebut fase
yang sudah selesai sebagai "berikutnya" dan temuan yang sudah tertutup sebagai
"terbuka" — dan agent berikutnya mempercayainya. Semua yang dicetak di sini
dibaca ulang dari ``jarvisfix.md`` dan dari git setiap kali dijalankan.

**Yang sengaja TIDAK dilakukan skrip ini: mengklaim hasil uji.** Ia mencetak
perintah yang harus dijalankan, bukan angka yang seolah-olah sudah diverifikasi.
Menyalin "2593 lulus" dari kemarin ke prompt hari ini persis jenis klaim palsu
yang dikejar sebelas fase di dokumen ini.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "jarvisfix.md"

#: Judul fase: "## Fase 26 — ..." atau "## FASE 7 — ..."
_PHASE_RE = re.compile(r"^#+\s*(?:Fase|FASE)\s+(\d+)\s*[—-]\s*(.+?)\s*$", re.M)
#: Hasilnya: "### Hasil Fase 26 — SELESAI 2026-08-08". Statusnya boleh memuat
#: koma dan kurung — "DIUKUR, TIDAK DIBANGUN" dan "SELESAI (mengamati)" sama
#: sahnya dengan "SELESAI". Pola yang lebih sempit membuat fase yang sudah
#: DITUTUP ditawarkan lagi sebagai pekerjaan tertunda, yaitu persis kebasian
#: yang keberadaan skrip ini dimaksudkan untuk mencegah.
_RESULT_RE = re.compile(
    r"^#+\s*Hasil\s+Fase\s+(\d+)\s*[—-]\s*([A-Z][^\n]*?)\s*"
    r"(?:\d{4}-\d{2}-\d{2})?\s*$",
    re.M)


def _text() -> str:
    try:
        return PLAN.read_text(encoding="utf-8")
    except OSError:
        return ""


#: Fase-fase awal menandai selesai DI JUDULNYA ("Fase 8 — ... — SELESAI ✅"),
#: bukan lewat bagian "Hasil" tersendiri. Membaca hanya satu bentuk membuat 14
#: fase yang sudah beres ditawarkan lagi sebagai pekerjaan tertunda — ditemukan
#: dengan MENJALANKAN skrip ini, bukan dengan membacanya.
#:
#: Batas kata WAJIB. Tanpa `\\b`, judul "Fase 38 — **Selesai**kan migrasi
#: FROZEN" dibaca sebagai fase yang sudah selesai, dan fase paling berisiko di
#: Siklus 6 hilang dari daftar tanpa suara — persis kegagalan yang keberadaan
#: skrip ini dimaksudkan untuk mencegah. Ditemukan dengan menjalankannya.
_DONE_IN_TITLE_RE = re.compile(
    r"\bSELESAI\b|✅|\bDITUTUP\b|\bTIDAK DIBANGUN\b", re.I)


def phases(text: str) -> list[tuple[int, str, str]]:
    """(nomor, judul, status) untuk setiap fase; status "" bila belum selesai."""
    done = {int(n): status.strip() for n, status in _RESULT_RE.findall(text)}
    seen: dict[int, str] = {}
    for number, title in _PHASE_RE.findall(text):
        # Judul pertama yang menang: bagian "Hasil" tidak menimpa judul fase.
        seen.setdefault(int(number), title.strip())
    out = []
    for number in sorted(seen):
        title = seen[number]
        status = done.get(number, "")
        if not status and _DONE_IN_TITLE_RE.search(title):
            status = "selesai (ditandai di judul)"
        out.append((number, title, status))
    return out


def open_phases(text: str) -> list[tuple[int, str, str]]:
    return [item for item in phases(text) if not item[2]]


def open_findings(text: str) -> list[str]:
    """Temuan yang disebut TERBUKA / belum dikerjakan, apa adanya."""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        # Baris tabel ringkasan memuat nomor temuan DAN kata "menunggu" pada
        # baris yang justru bertanda SELESAI. Disaring di sini, bukan dengan
        # pola temuan yang makin rumit.
        if stripped.startswith("|"):
            continue
        if re.search(r"SELESAI|✅", line):
            continue
        if not re.search(r"\b[ST]-\d+\b|^#+ T\d+ ", line):
            continue
        if re.search(r"TERBUKA|belum dikerjakan|belum diperbaiki|menunggu",
                     line, re.I):
            out.append(" ".join(stripped.strip("# ").split())[:150])
    seen, unique = set(), []
    for item in out:
        if item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _git(*args: str) -> str:
    try:
        return subprocess.run(("git", *args), cwd=ROOT, capture_output=True,
                              text=True, timeout=30).stdout.strip()
    except Exception:                                        # noqa: BLE001
        return ""


def frozen_files() -> list[str]:
    try:
        import json
        manifest = json.loads(
            (ROOT / "config" / "frozen_manifest.json").read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return []
    if isinstance(manifest, dict):
        for key in ("files", "frozen", "entries"):
            value = manifest.get(key)
            if isinstance(value, dict):
                return sorted(value)
            if isinstance(value, list):
                return sorted(str(item) for item in value)
        return sorted(str(k) for k in manifest)
    return []


PROTOCOL = """Metode kerja yang WAJIB diikuti (sudah terbukti lintas 34 fase):

1. UKUR DULU, jangan menebak. Angka ambang, biaya, dan penyebab harus datang
   dari perintah yang dijalankan — bukan dari perkiraan yang masuk akal.
   Beberapa kegagalan termahal di proyek ini lahir dari angka yang terdengar
   benar tetapi tidak pernah diukur (S-24, S-25, Fase 26, Fase 30).
2. UJI MERAH LEBIH DULU, lalu implementasi. Uji yang tidak pernah merah tidak
   membuktikan apa pun.
3. Uji PERILAKU, bukan teks sumber. Uji yang memeriksa isi berkas gagal karena
   hal yang benar dan lulus untuk kode yang salah (pelajaran Fase 33).
4. SUNYI BUKAN BUKTI. Ketiadaan di log tidak membuktikan sesuatu tidak terjadi;
   pasang instrumentasi dulu, lalu simpulkan.
5. JANGAN PERNAH mengklaim sukses yang tidak terbukti. Kegagalan palsu sama
   merusaknya dengan sukses palsu (Fase 33).
6. Setelah selesai: suite penuh + `ruff check .` + `scripts/verify_frozen.py`
   harus hijau SEBELUM commit.
7. CATAT di jarvisfix.md: apa yang dikerjakan, apa yang DIUKUR, kesalahan
   rancangan yang ditemukan di tengah jalan, dan batas jujurnya (apa yang
   BELUM terbukti). Bagian "batas jujur" itu wajib, bukan hiasan.
8. Commit dengan pesan yang menjelaskan SEBAB, bukan sekadar perubahan.

Berkas FROZEN tidak boleh diedit sama sekali — hanya dibungkus lewat seam."""

CHECKS = """cd "e:/jarvis agent/h"
.venv/Scripts/python.exe -m pytest -q -p no:randomly
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe scripts/verify_frozen.py"""


def build(codex: bool = False) -> str:
    text = _text()
    pending = open_phases(text)
    findings = open_findings(text)
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "?"
    recent = _git("log", "--oneline", "-5")
    dirty = _git("status", "--short")

    lines: list[str] = []
    lines.append("Lanjutkan pekerjaan pada proyek Jarvis di `e:/jarvis agent/h`.")
    lines.append("")
    lines.append("RENCANA INDUKNYA ADA DI `jarvisfix.md` — baca bagian yang "
                 "relevan sebelum mulai. Dokumen itu berisi seluruh fase, "
                 "temuan bernomor (S-xx/T-x), dan hasil pengukuran sebelumnya.")
    lines.append("")
    lines.append(f"Branch saat ini: {branch}")
    if recent:
        lines.append("Commit terakhir:")
        lines.extend(f"  {line}" for line in recent.splitlines())
    lines.append("")

    lines.append(f"FASE YANG BELUM SELESAI ({len(pending)}):")
    if pending:
        for number, title, _ in pending:
            lines.append(f"  - Fase {number} — {title}")
    else:
        lines.append("  (tidak ada — semua fase di jarvisfix.md sudah punya "
                     "bagian Hasil)")
    lines.append("")

    lines.append(f"TEMUAN YANG MASIH TERBUKA ({len(findings)}):")
    for item in findings[:12] or ["  (tidak ada yang bertanda TERBUKA)"]:
        lines.append(f"  - {item}" if findings else item)
    lines.append("")

    if dirty:
        lines.append(f"PERHATIAN — ada {len(dirty.splitlines())} berkas belum "
                     "bersih di git. Periksa sebelum mulai; jangan menimpa "
                     "pekerjaan yang menggantung.")
        lines.append("")

    if not codex:
        lines.append(PROTOCOL)
        lines.append("")
        frozen = frozen_files()
        if frozen:
            lines.append(f"Berkas FROZEN ({len(frozen)}):")
            lines.append("  " + ", ".join(frozen))
            lines.append("")
    else:
        lines.append("Ikuti metode di bagian PROTOKOL KERJA pada jarvisfix.md: "
                     "ukur dulu, uji merah lebih dulu, uji perilaku bukan teks "
                     "sumber, jangan klaim yang tak terbukti, dan catat batas "
                     "jujurnya. Berkas FROZEN tidak boleh diedit.")
        lines.append("")

    lines.append("Sebelum commit, ketiganya harus hijau:")
    lines.append(CHECKS)
    lines.append("")
    lines.append("Mulailah dengan mengusulkan fase mana yang dikerjakan dan "
                 "mengapa, lalu tunggu persetujuan sebelum menulis kode.")
    return "\n".join(lines)


def _print(text: str) -> None:
    """Cetak apa adanya, apa pun encoding konsolnya.

    Judul fase memuat "✅" dan em dash; konsol Windows default cp1252 dan
    akan MELEMPAR di tengah cetak. Alat yang tujuannya dijalankan rutin tidak
    boleh gagal mencetak keluarannya sendiri.
    """
    try:
        sys.stdout.reconfigure(encoding="utf-8")             # type: ignore[attr-defined]
    except Exception:                                        # noqa: BLE001
        pass
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", "") or "ascii"
        print(text.encode(encoding, "replace").decode(encoding, "replace"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", action="store_true",
                        help="varian ringkas untuk Codex/agent lain")
    parser.add_argument("--out", default="", help="tulis ke berkas")
    args = parser.parse_args(argv)

    prompt = build(codex=args.codex)
    if args.out:
        Path(args.out).write_text(prompt, encoding="utf-8")
        print(f"ditulis ke {args.out} ({len(prompt)} karakter)")
    else:
        _print(prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
