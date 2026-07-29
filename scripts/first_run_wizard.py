"""J.A.R.V.I.S — wizard instalasi awal.

Sebelumnya bernama ``setup.py`` di root. Nama itu **direservasi setuptools**,
sehingga ``pip install .`` memicu wizard ini alih-alih memasang paket.

Jalankan:  python scripts/first_run_wizard.py
Lalu:      python -m jarvis.main
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# requirements.txt = basis Mark XLVIII; requirements-xlix.txt = tambahan
# Mark XLIX/MK50. Keduanya diperlukan — wizard lama hanya memasang yang
# pertama, sehingga boot MK50 gagal dengan ModuleNotFoundError.
REQUIREMENTS = ("requirements.txt", "requirements-xlix.txt")


def _run(args: list[str], label: str) -> bool:
    print(f"\n> {label}")
    try:
        subprocess.run(args, check=True, cwd=str(ROOT))
        return True
    except subprocess.CalledProcessError as exc:
        print(f"  x gagal (exit {exc.returncode})")
        return False
    except FileNotFoundError:
        print("  x perintah tidak ditemukan")
        return False


def main() -> int:
    print("J.A.R.V.I.S — instalasi awal")

    failed: list[str] = []

    for name in REQUIREMENTS:
        path = ROOT / name
        if not path.exists():
            print(f"\n> {name} — dilewati (tidak ada)")
            continue
        if not _run([sys.executable, "-m", "pip", "install", "-r", str(path)],
                    f"Memasang {name}"):
            failed.append(name)

    # Playwright dipakai otomasi browser agent (jarvis/agent/tools/browser.py).
    # Opsional: kegagalan di sini tidak membatalkan instalasi.
    if not _run([sys.executable, "-m", "playwright", "install"],
                "Memasang browser Playwright (opsional)"):
        print("  -> otomasi browser agent tidak tersedia sampai perintah ini "
              "berhasil dijalankan ulang")

    if failed:
        print("\nInstalasi BELUM tuntas: " + ", ".join(failed))
        print("Perbaiki error di atas lalu jalankan ulang wizard ini.")
        return 1

    print("\nSelesai. Jalankan Jarvis dengan:\n")
    print("    python -m jarvis.main\n")
    print("Diagnostik:  python -m jarvis.core.health")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
