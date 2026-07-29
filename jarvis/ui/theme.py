"""Mark XLIX theme — minimal cinematic. All values come from config.yaml.

Presets live under ``ui.themes.presets.<name>`` (cyan_gold / stealth_dark /
alert_red by default); ``ui.themes.active`` selects one. The flat top-level
``theme:`` section remains a fully-supported fallback for any preset key
that is absent, so existing configs keep working unchanged.
"""
from __future__ import annotations

from PyQt6.QtGui import QColor, QFont, QFontDatabase

from jarvis.core import config


class Palette:
    def __init__(self) -> None:
        self._load()

    def _load(self) -> None:
        legacy = config.section("theme")
        active = str(config.get("ui.themes.active", "") or "")
        presets = config.section("ui.themes.presets")
        preset = presets.get(active, {}) if active else {}

        def pick(*keys: str, default: str = "") -> str:
            for k in keys:
                if k in preset:
                    return preset[k]
            for k in keys:
                if k in legacy:
                    return legacy[k]
            return default

        self.name        = active or "legacy"
        self.base       = pick("background", "base", default="#050810")
        self.panel      = pick("panel", default="#0a1018")
        self.accent     = pick("accent", default="#00e5ff")
        self.accent_dim = pick("accent_dim", default="#0891b2")
        self.secondary  = pick("secondary", default="#7dd3fc")
        self.alert      = pick("alert", default="#ff4444")
        self.success    = pick("success", default="#4ade80")
        self.text       = pick("text", default="#c8e6f5")
        self.text_dim   = pick("text_dim", default="#5a7a8a")
        self.orb_core   = pick("orb_core", default=self.text)
        self.glow       = pick("glow", default=self.accent)
        self.halo       = pick("halo", default=self.secondary)
        self.waveform   = pick("waveform", default=self.accent)
        self.log_colors: dict = dict(preset.get("log_colors", {})) or {
            "ERROR": self.alert, "WARNING": "#f5a623", "INFO": self.text_dim,
            "DEBUG": self.text_dim, "USER": self.secondary, "AI": self.accent,
        }

    def set_active(self, name: str) -> None:
        """Runtime theme switch — mutates this singleton in place so every
        module that imported ``theme.PAL`` sees the new values immediately."""
        import jarvis.core.config as _cfg
        data = _cfg._load()
        themes = data.setdefault("ui", {}).setdefault("themes", {})
        if name in themes.get("presets", {}) or not themes.get("presets"):
            themes["active"] = name
        self._load()


PAL = Palette()

_families: list[str] | None = None


def available_themes() -> list[str]:
    return list(config.section("ui.themes.presets").keys())


def set_theme(name: str) -> None:
    PAL.set_active(name)


def _available(name: str) -> bool:
    global _families
    if _families is None:
        _families = QFontDatabase.families()
    return any(name.lower() == f.lower() for f in _families)


def header_font(size: int, weight: QFont.Weight = QFont.Weight.Light) -> QFont:
    name = config.get("theme.header_font", "Rajdhani")
    if not _available(name):
        name = config.get("theme.header_font_fallback", "Segoe UI Light")
    f = QFont(name, size, weight)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
    return f


def mono_font(size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    name = config.get("theme.mono_font", "JetBrains Mono")
    if not _available(name):
        name = config.get("theme.mono_font_fallback", "Consolas")
    return QFont(name, size, weight)


def qcolor(hexstr: str, alpha: int = 255) -> QColor:
    c = QColor(hexstr)
    c.setAlpha(alpha)
    return c


def blend(a: str | QColor, b: str | QColor, t: float) -> QColor:
    """Linear blend a→b, t in [0,1]."""
    ca, cb = QColor(a), QColor(b)
    t = max(0.0, min(1.0, t))
    return QColor(
        int(ca.red()   + (cb.red()   - ca.red())   * t),
        int(ca.green() + (cb.green() - ca.green()) * t),
        int(ca.blue()  + (cb.blue()  - ca.blue())  * t),
    )
