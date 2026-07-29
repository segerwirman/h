"""Fast, deterministic OS actions that never require an LLM or browser driver."""
from __future__ import annotations

import os
import platform
import webbrowser
from dataclasses import dataclass


@dataclass(frozen=True)
class NativeActionResult:
    ok: bool
    detail: str = ""


def open_external_url(url: str) -> NativeActionResult:
    """Open a pre-validated URL through the OS default-browser association."""

    target = str(url or "").strip()
    if not target:
        return NativeActionResult(False, "URL kosong")
    try:
        startfile = getattr(os, "startfile", None)
        if platform.system() == "Windows" and startfile is not None:
            startfile(target)
            return NativeActionResult(True, "windows-shell")
        if webbrowser.open(target, new=2):
            return NativeActionResult(True, "webbrowser")
        return NativeActionResult(False, "browser default tidak tersedia")
    except (OSError, webbrowser.Error) as exc:
        return NativeActionResult(False, str(exc)[:160])
