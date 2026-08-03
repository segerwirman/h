"""Phase 17A: bounded public source registry; no auth, login, or browser actions."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

_ALLOWED_MODES = frozenset({"api", "rss", "html"})
_SENSITIVE_TERMS = frozenset({"login", "signin", "auth", "account", "payment", "checkout", "bank", "captcha"})
_MIN_RATE_LIMIT_S = 5
_MAX_RATE_LIMIT_S = 86400


def _canonical_public_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("source harus URL HTTPS publik tanpa credential")
    parts = [part.casefold() for part in parsed.path.split("/") if part]
    if any(part in _SENSITIVE_TERMS for part in parts):
        raise ValueError("source login/account/payment/captcha tidak diizinkan")
    if parsed.query and any(term in parsed.query.casefold() for term in ("token=", "key=", "secret=", "password=")):
        raise ValueError("source query credential tidak diizinkan")
    return urlunparse(("https", parsed.netloc.casefold(), parsed.path or "/", "", parsed.query, ""))


@dataclass(frozen=True)
class MonitorSource:
    name: str
    url: str
    mode: str
    rate_limit_s: int

    @classmethod
    def create(cls, name: str, url: str, mode: str, *, rate_limit_s: int) -> "MonitorSource":
        label = str(name or "").strip()
        if not label or len(label) > 80:
            raise ValueError("nama source wajib dan maksimal 80 karakter")
        selected = str(mode or "").casefold()
        if selected not in _ALLOWED_MODES:
            raise ValueError("mode source harus api, rss, atau html")
        interval = int(rate_limit_s)
        if interval < _MIN_RATE_LIMIT_S or interval > _MAX_RATE_LIMIT_S:
            raise ValueError("rate limit source harus 5..86400 detik")
        return cls(label, _canonical_public_url(url), selected, interval)


class SourceRegistry:
    def __init__(self, *, max_sources: int = 50):
        self._max_sources = max(1, min(int(max_sources), 100))
        self._sources: dict[str, MonitorSource] = {}

    def add(self, name: str, url: str, mode: str, *, rate_limit_s: int) -> MonitorSource:
        source = MonitorSource.create(name, url, mode, rate_limit_s=rate_limit_s)
        if source.url in self._sources:
            raise ValueError("source URL sudah terdaftar")
        if len(self._sources) >= self._max_sources:
            raise ValueError("batas source registry tercapai")
        self._sources[source.url] = source
        return source

    def list(self) -> list[MonitorSource]:
        return sorted(self._sources.values(), key=lambda item: item.name.casefold())

    def public_view(self) -> list[dict]:
        return [{"name": s.name, "url": s.url, "mode": s.mode, "rate_limit_s": s.rate_limit_s}
                for s in self.list()]


__all__ = ["MonitorSource", "SourceRegistry"]
