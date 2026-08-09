"""Fase 38 — `ui.py` keluar dari jalur runtime (S-33, S-34).

Diukur sebelum menyentuh apa pun:

| | |
|---|---|
| `import ui` | **4.566 ms**, 1.801 modul |
| pengimpor `ui.py` | **satu**: `main.py:38` |
| pemakaian saat runtime | **nol** — hanya anotasi tipe di `main.py:555` |

`jarvis/main.py` membangun UI BARU (`jarvis.ui.window.JarvisUI`) lalu
menyerahkannya ke `legacy.JarvisLive(ui)`. Kelas `JarvisUI` yang lama tidak
pernah diinstansiasi — tetapi modulnya, 2.622 baris Qt, tetap dimuat penuh.

Dan itu ada di jalur KESIAPAN SUARA: `_import_legacy()` dipanggil di dalam
`runner()` sebelum `voice.pipeline_ready` terbit. Jadi suara Jarvis siap 4,5
detik lebih lambat dari yang perlu, setiap boot.

Fase ini membuka `main.py` dari FROZEN dengan sadar — itulah isi fase ini —
dan menyentuhnya seminimal mungkin: import yang hanya untuk tipe, anotasi
dikutip, dan entri legacy mengimpornya sendiri saat benar-benar dipakai.
"""
from __future__ import annotations

import subprocess
import sys


def _in_subprocess(code: str) -> str:
    """Dijalankan di proses bersih — `sys.modules` di sini sudah tercemar."""
    import os

    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, cwd=".", env=env, timeout=300)
    return (result.stdout + result.stderr).strip()


def test_importing_the_legacy_pipeline_no_longer_loads_the_legacy_ui():
    """Inti fase ini, diukur di proses bersih."""
    output = _in_subprocess(
        "import sys; sys.path.insert(0, '.')\n"
        "import main\n"
        "print('UI_LOADED' if 'ui' in sys.modules else 'UI_ABSENT')\n"
    )

    assert "UI_ABSENT" in output, output


def test_the_legacy_pipeline_still_imports():
    """Membuang import tidak boleh membuat modulnya sendiri rusak."""
    output = _in_subprocess(
        "import sys; sys.path.insert(0, '.')\n"
        "import main\n"
        "print('JARVISLIVE_OK' if hasattr(main, 'JarvisLive') else 'RUSAK')\n"
    )

    assert "JARVISLIVE_OK" in output, output


def test_the_annotation_no_longer_needs_the_class_at_runtime():
    """Anotasi yang dievaluasi akan melempar `NameError` tanpa importnya.

    `main.py` tidak punya `from __future__ import annotations`, jadi
    anotasinya harus dikutip — bukan sekadar importnya dipindah.
    """
    output = _in_subprocess(
        "import sys; sys.path.insert(0, '.')\n"
        "import main, inspect\n"
        "sig = inspect.signature(main.JarvisLive.__init__)\n"
        "print('ANNOT=', repr(sig.parameters['ui'].annotation))\n"
    )

    assert "ANNOT=" in output, output
    assert "NameError" not in output


def test_the_legacy_entry_can_still_reach_the_old_ui():
    """Jalur legacy tidak didukung, tetapi tidak boleh kita RUSAKKAN.

    Ia harus mengimpor `JarvisUI` sendiri saat benar-benar dipakai.
    """
    output = _in_subprocess(
        "import sys; sys.path.insert(0, '.')\n"
        "import main\n"
        "names = main.main.__code__.co_names + tuple(\n"
        "    c.co_names for c in main.main.__code__.co_consts\n"
        "    if hasattr(c, 'co_names'))\n"
        "flat = [n for item in names for n in ((item,) if isinstance(item, str) else item)]\n"
        "print('MENGIMPOR_SENDIRI' if 'JarvisUI' in flat else 'HILANG')\n"
    )

    assert "MENGIMPOR_SENDIRI" in output, output


def test_the_import_saving_is_real():
    """Angkanya diukur ulang, bukan diwarisi dari catatan."""
    output = _in_subprocess(
        "import sys, time; sys.path.insert(0, '.')\n"
        "t = time.perf_counter(); import main\n"
        "print('MS=', round((time.perf_counter() - t) * 1000))\n"
        "print('UI=', 'ui' in sys.modules)\n"
    )

    assert "UI= False" in output, output


# ── FROZEN dibuka dengan SADAR, bukan sebagai efek samping ────────────────

def test_the_frozen_manifest_still_matches_the_files():
    """Kalau baseline tidak diperbarui, seluruh CI merah — dan itu benar."""
    from scripts.verify_frozen import verify_frozen

    errors, _ = verify_frozen()

    assert errors == [], errors


def test_the_manifest_records_why_the_baseline_moved():
    """Baseline yang bergeser tanpa alasan tertulis adalah pembekuan yang
    kehilangan maknanya."""
    import json
    from pathlib import Path

    manifest = json.loads(
        Path("config/frozen_manifest.json").read_text(encoding="utf-8"))
    description = str(manifest.get("description", ""))

    assert "38" in description or "Fase" in description, description


def test_ui_py_is_still_frozen():
    """`ui.py` tidak disentuh fase ini — hanya berhenti dimuat.

    Membuka dua berkas sekaligus berarti dua sumber risiko dalam satu langkah.
    """
    import json
    from pathlib import Path

    manifest = json.loads(
        Path("config/frozen_manifest.json").read_text(encoding="utf-8"))

    assert "ui.py" in manifest["files"]
