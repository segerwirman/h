"""Fase 6.1 — dependency yang kegagalannya SENYAP harus ada dan terdeklarasi.

Insiden 2026-08-04: `.venv` dibangun dari `[dependencies]` saja, extras
`[voice]`/`[vision]`/`[agent]` tak pernah terpasang. Akibatnya `import
sounddevice` gagal di main.py:35, seluruh pipeline suara mati, dan JARVIS
diam total untuk voice MAUPUN text — tanpa satu pun pesan yang berguna.

Modul di bawah punya sifat yang sama: ketiadaannya tidak menghentikan boot,
hanya mematikan fungsi secara diam-diam karena tertangkap ``except`` di
lapisan atas. Justru itu yang membuatnya mahal untuk didiagnosis.

Dua lapis dijaga di sini:
  1. modul benar-benar dapat diimpor di lingkungan ini;
  2. modul terdeklarasi di pyproject.toml — kalau hanya dipasang manual,
     ``uv sync`` berikutnya akan membuangnya lagi tanpa peringatan.
"""
from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import pytest

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

# modul  →  (nama distribusi di pyproject, kenapa kegagalannya senyap)
SILENT_FAILURE_DEPS = {
    "sounddevice": ("sounddevice",
                    "main.py:35 impor level modul; jarvis/main.py menelan "
                    "kegagalannya jadi satu baris log"),
    "google.genai": ("google-genai",
                     "main.py:36 impor level modul; sesi Gemini Live mati"),
    "openai": ("openai",
               "jarvis/agent/llm_client.py:75 di dalam _client(); provider "
               "openai_compat gagal hanya saat chat pertama"),
    "croniter": ("croniter",
                 "jarvis/agent/cron.py:51 _next_run() mengembalikan None "
                 "diam-diam sehingga jadwal tidak pernah berjalan"),
}


def _declared_names() -> set[str]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    project = data.get("project", {})
    specs = list(project.get("dependencies", []))
    for group in (project.get("optional-dependencies", {}) or {}).values():
        specs.extend(group)
    names = set()
    for spec in specs:
        head = str(spec).split(";")[0].strip()
        for sep in ("[", ">", "<", "=", "!", "~", " "):
            head = head.split(sep)[0]
        if head:
            names.add(head.strip().lower().replace("_", "-"))
    return names


@pytest.mark.parametrize("module", sorted(SILENT_FAILURE_DEPS))
def test_modul_dapat_diimpor(module):
    _, why = SILENT_FAILURE_DEPS[module]
    assert importlib.util.find_spec(module) is not None, (
        f"{module} tidak terpasang — {why}. Perbaiki: "
        f"uv sync --extra voice --extra vision --extra agent")


@pytest.mark.parametrize("module", sorted(SILENT_FAILURE_DEPS))
def test_modul_terdeklarasi_di_pyproject(module):
    dist, why = SILENT_FAILURE_DEPS[module]
    declared = _declared_names()
    assert dist.lower() in declared, (
        f"{dist} tidak terdaftar di pyproject.toml — {why}. Terpasang manual "
        f"akan hilang lagi pada 'uv sync' berikutnya.")
