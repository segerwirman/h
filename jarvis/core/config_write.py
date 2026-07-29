"""Penulis config.yaml SURGICAL (PARITY v2 Fase 4).

config.yaml Jarvis penuh komentar penjelasan — yaml.dump ulang seluruh file
akan menghancurkannya. Modul ini mengganti HANYA nilai pada baris key yang
dituju, mengikuti path dotted lewat indentasi; komentar inline pada baris
itu dan seluruh sisa file utuh.

    set_scalar("agent.ack_phrase", "Siap.")
    set_scalar("ui.themes.active", "stealth_dark")
    set_scalar("ui.reduced_motion", True)

Path belum ada → blok dibuat di akhir file. Setelah menulis, panggil
``config.reload()`` (dilakukan otomatis di sini).
"""
from __future__ import annotations

import re
import threading

from jarvis.core import config, log

_logger = log.get("core.config_write")
_lock = threading.Lock()


def _fmt(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    # quote bila berpotensi ambigu untuk YAML
    if text == "" or re.search(r"[:#\[\]{}\"']|^\s|\s$", text) \
            or text.lower() in ("true", "false", "null", "yes", "no", "on",
                                "off"):
        return '"' + text.replace('"', '\\"') + '"'
    return text


def set_scalar(dotted_key: str, value) -> bool:
    """Tulis satu nilai scalar. Return False bila gagal (state lama utuh)."""
    parts = [p for p in dotted_key.split(".") if p]
    if not parts:
        return False
    with _lock:
        try:
            path = config.CONFIG_PATH
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines(keepends=True)
            new_lines = _replace(lines, parts, value)
            if new_lines is None:                  # path tidak ada → append
                suffix = "" if text.endswith("\n") else "\n"
                text += suffix + _fresh_block(parts, value)
                path.write_text(text, encoding="utf-8")
            else:
                path.write_text("".join(new_lines), encoding="utf-8")
            config.reload()
            _logger.info("config.set", key=dotted_key)
            return True
        except Exception as e:                     # noqa: BLE001
            _logger.error("config.set_failed", key=dotted_key,
                          error=str(e)[:120])
            return False


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _replace(lines: list[str], parts: list[str], value) -> list[str] | None:
    """Cari baris target lewat path indentasi; ganti nilainya.

    Return None bila path tidak ditemukan.
    """
    depth = 0                       # index part yang sedang dicari
    parent_indent = -1              # indent parent yang sudah dimasuki
    child_indent: int | None = None  # indent level anak blok ini (dari baris
    #                                  non-komentar pertama di dalamnya)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = _indent_of(line)
        if indent <= parent_indent:            # keluar blok tanpa ketemu
            return None
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:             # level lebih dalam — bukan anak
            continue
        m = re.match(rf"(\s*){re.escape(parts[depth])}\s*:(.*)$",
                     line.rstrip("\n"))
        if m is None:
            continue
        if depth == len(parts) - 1:                # baris target
            rest = m.group(2)
            comment = ""
            cm = re.search(r"\s+#.*$", rest)
            if cm:
                comment = cm.group(0)
            eol = "\n" if line.endswith("\n") else ""
            lines[i] = (f"{m.group(1)}{parts[depth]}: "
                        f"{_fmt(value)}{comment}{eol}")
            return lines
        depth += 1
        parent_indent = indent
        child_indent = None
    return None


def _fresh_block(parts: list[str], value) -> str:
    out = []
    for d, part in enumerate(parts[:-1]):
        out.append("  " * d + part + ":")
    out.append("  " * (len(parts) - 1) + f"{parts[-1]}: {_fmt(value)}")
    return "\n" + "\n".join(out) + "\n"
