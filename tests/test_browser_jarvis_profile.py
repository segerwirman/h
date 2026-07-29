"""JARVIS memakai profil Chrome khusus miliknya, bukan Chrome for Testing."""
from __future__ import annotations

import asyncio
import types

from jarvis.agent.tools import browser as B


class _FakeCtx:
    def __init__(self):
        self.pages = []


class _PersistentPW:
    """Playwright palsu: launch_persistent_context sukses."""
    def __init__(self):
        self.calls = {}

        class _Chromium:
            def __init__(self, outer):
                self._outer = outer

            def launch_persistent_context(self, **kwargs):
                self._outer.calls = dict(kwargs)
                return _FakeCtx()

            def launch(self, **kwargs):
                self._outer.calls = {"FELL_BACK_TO_LAUNCH": True, **kwargs}
                raise AssertionError("tidak boleh fallback saat Chrome tersedia")

        self.chromium = _Chromium(self)


class _NoChromePW:
    """launch_persistent_context gagal → wajib fallback ke launch()."""
    def __init__(self):
        self.fell_back = False

        class _Chromium:
            def __init__(self, outer):
                self._outer = outer

            def launch_persistent_context(self, **kwargs):
                raise RuntimeError("chrome channel tidak ditemukan")

            def launch(self, **kwargs):
                self._outer.fell_back = True

                class _B:
                    def new_context(self, **_):
                        return _FakeCtx()
                return _B()

        self.chromium = _Chromium(self)


def test_default_profile_dir_terisolasi_bukan_chrome_for_testing(monkeypatch):
    monkeypatch.setattr(B.config, "get", lambda k, d=None: d)
    path = B._jarvis_profile_dir()
    assert "JARVIS" in path and "ChromeProfile" in path


def test_launch_memakai_chrome_persisten_dengan_profil_jarvis(monkeypatch):
    cfg = {
        "agent.browser.channel": "chrome",
        "agent.browser.user_data_dir": "",
        "agent.browser.profile_directory": "",
    }
    monkeypatch.setattr(B.config, "get", lambda k, d=None: cfg.get(k, d))
    pw = _PersistentPW()
    ctx, browser = B._launch_browser(pw, headless=True)
    assert browser is None                       # persistent context memiliki dirinya sendiri
    assert pw.calls.get("channel") == "chrome"   # Chrome asli, bukan Chrome for Testing
    assert "JARVIS" in pw.calls.get("user_data_dir", "")


def test_launch_fallback_aman_bila_chrome_tak_ada(monkeypatch):
    monkeypatch.setattr(B.config, "get", lambda k, d=None: d)
    monkeypatch.setattr(B, "_browser_executable_candidates", lambda _c: [])
    pw = _NoChromePW()
    ctx, browser = B._launch_browser(pw, headless=True)
    assert pw.fell_back is True                  # tidak hard-crash
    assert browser is not None                   # browser bundled dipakai sebagai fallback


def test_launch_mencoba_executable_terpasang_sebelum_bundled(monkeypatch):
    monkeypatch.setattr(B.config, "get", lambda k, d=None: d)
    monkeypatch.setattr(
        B, "_browser_executable_candidates", lambda _c: [r"C:\Chrome\chrome.exe"])

    class _PW:
        def __init__(self):
            self.calls = []

            class Chromium:
                def __init__(self, outer):
                    self.outer = outer

                def launch_persistent_context(self, **kwargs):
                    self.outer.calls.append(kwargs)
                    if "executable_path" not in kwargs:
                        raise RuntimeError("channel lookup failed")
                    return _FakeCtx()

                def launch(self, **_):
                    raise AssertionError("bundled browser must not be used")

            self.chromium = Chromium(self)

    pw = _PW()
    _ctx, browser = B._launch_browser(pw, headless=True)
    assert browser is None
    assert pw.calls[-1]["executable_path"] == r"C:\Chrome\chrome.exe"


def test_profile_directory_diteruskan_sebagai_arg(monkeypatch):
    cfg = {
        "agent.browser.channel": "chrome",
        "agent.browser.user_data_dir": "",
        "agent.browser.profile_directory": "Profile 8",
    }
    monkeypatch.setattr(B.config, "get", lambda k, d=None: cfg.get(k, d))
    pw = _PersistentPW()
    B._launch_browser(pw, headless=False)
    args = pw.calls.get("args", [])
    assert any("--profile-directory=Profile 8" == a for a in args)


def test_browser_navigate_mempertahankan_about_blank(monkeypatch):
    seen = []

    class _Page:
        def goto(self, url, **_kwargs):
            seen.append(url)

        @staticmethod
        def title():
            return ""

    class _Host:
        @staticmethod
        def invalidate_snapshot():
            return None

        @staticmethod
        def call(fn, _timeout):
            return fn(_Page())

    monkeypatch.setattr(B, "_claim_host", lambda _session: (_Host(), "x"))
    result = asyncio.run(B.BrowserNavigate().run("about:blank"))
    assert result.ok
    assert seen == ["about:blank"]
