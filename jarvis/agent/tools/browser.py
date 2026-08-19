"""Browser automation (§3.1.D) — Playwright Python, browser persisten.

Deviasi sadar dari spec (dicatat di MIGRATION_NOTES): repo sudah punya
Playwright Python, jadi tidak ada bridge TS. Browser hidup di SATU thread
khusus (sync API Playwright tidak boleh berbagi event loop asyncio); tool
async berkomunikasi lewat antrian job + Future.

Pola pemakaian oleh agent: ``browser_snapshot`` → pilih ``ref`` →
``browser_click``/``browser_type`` memakai ref itu.
"""
from __future__ import annotations

import asyncio
import queue
import threading
import time
from concurrent.futures import Future

from pydantic import BaseModel, Field

from jarvis.core import config, log
from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.paths import generated_dir

_logger = log.get("agent.tools.browser")


def _is_target_closed(exc: BaseException) -> bool:
    """Playwright uses several exception classes for the same dead context."""

    name = type(exc).__name__.casefold()
    message = str(exc).casefold()
    return (
        "targetclosed" in name
        or "target page, context or browser has been closed" in message
        or "browser has been closed" in message
        or "context has been closed" in message
    )


def _jarvis_profile_dir() -> str:
    """Direktori profil Chrome khusus JARVIS (terisolasi dari profil user).

    Default: folder khusus milik JARVIS sendiri sehingga tidak pernah bentrok
    profile-lock dengan Chrome user (mis. profil 'Eric'). Bisa dioverride via
    ``agent.browser.user_data_dir``.
    """
    import os
    configured = str(config.get("agent.browser.user_data_dir", "") or "").strip()
    if configured:
        return os.path.expandvars(os.path.expanduser(configured))
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "JARVIS", "ChromeProfile")


def _cdp_enabled() -> bool:
    """Whether the Jarvis-owned browser exposes its loopback CDP endpoint."""
    return bool(config.get("agent.browser.cdp.enabled", True))


def _cdp_address() -> str:
    value = str(config.get(
        "agent.browser.cdp.address", "127.0.0.1") or "127.0.0.1").strip()
    if value != "127.0.0.1":
        raise ValueError("dedicated CDP wajib bind ke 127.0.0.1")
    return value


def _cdp_port() -> int:
    raw = config.get("agent.browser.cdp.port", 9333)
    try:
        port = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("port CDP dedicated tidak valid") from exc
    if not 1024 <= port <= 65535:
        raise ValueError("port CDP dedicated harus berada pada 1024-65535")
    return port


def _cdp_profile_dir() -> str:
    """Resolve and validate the profile owned by Jarvis CDP."""
    import os
    from pathlib import Path

    configured = str(config.get(
        "agent.browser.cdp.user_data_dir", "") or "").strip()
    if configured:
        candidate = Path(os.path.expandvars(os.path.expanduser(configured)))
    else:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        candidate = Path(base) / "JARVIS" / "ChromeCDPProfile"

    resolved = candidate.resolve()
    repo = Path(config.base_dir()).resolve()
    if resolved == repo or repo in resolved.parents:
        raise ValueError("profil CDP dedicated tidak boleh berada di repository")

    resolved_text = str(resolved).replace("\\", "/").casefold()
    local = os.environ.get("LOCALAPPDATA", "")
    chrome_user_data = (
        Path(local) / "Google" / "Chrome" / "User Data"
        if local else None
    )
    if chrome_user_data is not None:
        chrome_root = chrome_user_data.resolve()
        if resolved == chrome_root or chrome_root in resolved.parents:
            raise ValueError(
                "profil CDP dedicated tidak boleh memakai Chrome User Data user"
            )
    # Reject the canonical Chrome User Data shape even when a configured path
    # names another Windows account than the one running this process.
    if "/google/chrome/user data" in resolved_text:
        raise ValueError(
            "profil CDP dedicated tidak boleh memakai Chrome User Data user"
        )
    if "profile 8" in resolved_text:
        raise ValueError("profil CDP dedicated tidak boleh memakai Profile 8")
    return str(resolved)


def _cdp_timeout(name: str, default: float) -> float:
    raw = config.get(f"agent.browser.cdp.{name}", default)
    try:
        return max(0.1, float(raw))
    except (TypeError, ValueError):
        return float(default)


def _cdp_probe(address: str, port: int, timeout_s: float) -> dict | None:
    """Read only the local CDP version endpoint; never returns page data."""
    from urllib.error import URLError
    from urllib.request import Request, urlopen

    request = Request(
        f"http://{address}:{int(port)}/json/version",
        headers={"Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=max(0.05, float(timeout_s))) as response:
            raw = response.read(4096)
    except (OSError, URLError, ValueError):
        return None
    try:
        import json
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        # A responding listener is still an ownership conflict, even when it
        # does not speak the expected JSON shape.
        return {"reachable": True}
    return payload if isinstance(payload, dict) else {"reachable": True}


def _wait_for_cdp(timeout_s: float | None = None) -> bool:
    address = _cdp_address()
    port = _cdp_port()
    deadline = time.monotonic() + (
        _cdp_timeout("startup_timeout_s", 20.0)
        if timeout_s is None else max(0.1, float(timeout_s))
    )
    while time.monotonic() < deadline:
        if _cdp_probe(address, port, 0.25) is not None:
            return True
        time.sleep(min(0.1, max(0.01, deadline - time.monotonic())))
    return _cdp_probe(address, port, 0.25) is not None


def _wait_for_cdp_gone(timeout_s: float | None = None) -> bool:
    """Wait for the owned endpoint to disappear without touching other ports."""
    address = _cdp_address()
    port = _cdp_port()
    deadline = time.monotonic() + (
        _cdp_timeout("close_timeout_s", 10.0)
        if timeout_s is None else max(0.1, float(timeout_s))
    )
    while time.monotonic() < deadline:
        if _cdp_probe(address, port, 0.25) is None:
            return True
        time.sleep(min(0.1, max(0.01, deadline - time.monotonic())))
    return _cdp_probe(address, port, 0.25) is None


def _browser_executable_candidates(channel: str) -> list[str]:
    """Installed Chromium executables Playwright channel lookup may miss."""

    import os
    from pathlib import Path

    if os.name != "nt":
        return []
    roots = [
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    relatives = {
        "chrome": (
            r"Google\Chrome\Application\chrome.exe",
            r"Microsoft\Edge\Application\msedge.exe",
        ),
        "msedge": (
            r"Microsoft\Edge\Application\msedge.exe",
            r"Google\Chrome\Application\chrome.exe",
        ),
        "edge": (
            r"Microsoft\Edge\Application\msedge.exe",
            r"Google\Chrome\Application\chrome.exe",
        ),
    }
    ordered = relatives.get(
        str(channel or "").casefold(),
        relatives["chrome"],
    )
    found: list[str] = []
    for relative in ordered:
        for root in roots:
            candidate = Path(root) / relative if root else None
            if candidate is not None and candidate.is_file():
                value = str(candidate)
                if value not in found:
                    found.append(value)
    return found


def _launch_browser(pw, headless: bool, *, dedicated_cdp: bool = False):
    """Launch Chrome with either the ordinary or dedicated CDP profile.

    ``dedicated_cdp`` selects the separate Jarvis-owned CDP profile. The
    ordinary browser lane keeps its historical configuration and behavior.
    """
    if dedicated_cdp:
        if not _cdp_enabled():
            raise RuntimeError("dedicated CDP dimatikan di config")
        user_data_dir = _cdp_profile_dir()
        channel = str(config.get("agent.browser.channel", "chrome") or "chrome").strip()
        args = [
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            f"--remote-debugging-address={_cdp_address()}",
            f"--remote-debugging-port={_cdp_port()}",
        ]
        import os
        address = _cdp_address()
        port = _cdp_port()
        if _cdp_probe(address, port, 0.25) is not None:
            raise RuntimeError(
                f"port CDP dedicated {port} sudah dipakai proses lain")
        try:
            os.makedirs(user_data_dir, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("browser.cdp.profile_dir_failed", error=str(exc)[:120])
        try:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                channel=channel or None,
                headless=headless,
                no_viewport=True,
                args=args,
            )
            _logger.info("browser.cdp.launched", mode="persistent-chrome")
            return ctx, None
        except Exception as exc:
            _logger.warning("browser.cdp.persistent_chrome_unavailable",
                            error=str(exc)[:160], fallback="installed-executable")
            for executable in _browser_executable_candidates(channel):
                try:
                    ctx = pw.chromium.launch_persistent_context(
                        user_data_dir=user_data_dir,
                        executable_path=executable,
                        headless=headless,
                        no_viewport=True,
                        args=args,
                    )
                    _logger.info("browser.cdp.launched",
                                 mode="persistent-executable")
                    return ctx, None
                except Exception as path_exc:  # noqa: BLE001
                    _logger.warning("browser.cdp.installed_executable_failed",
                                    error=str(path_exc)[:160])
            raise RuntimeError(
                f"Chrome CDP dedicated gagal diluncurkan: {str(exc)[:180]}"
            ) from exc

    import os
    channel = str(config.get("agent.browser.channel", "chrome") or "chrome").strip()
    user_data_dir = _jarvis_profile_dir()
    profile_directory = str(
        config.get("agent.browser.profile_directory", "") or "").strip()
    args = [
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
    ]
    if profile_directory:
        args.append(f"--profile-directory={profile_directory}")
    try:
        os.makedirs(user_data_dir, exist_ok=True)
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("browser.profile_dir_failed", error=str(exc)[:120])
    try:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            channel=channel or None,
            headless=headless,
            no_viewport=True,
            args=args,
        )
        _logger.info("browser.launched", mode="persistent-chrome",
                     channel=channel, profile=user_data_dir)
        return ctx, None
    except Exception as exc:                                 # noqa: BLE001
        # Channel lookup can fail on valid per-user/enterprise installations.
        # Try exact installed executable paths before requiring Playwright's
        # separately downloaded bundled Chromium.
        _logger.warning("browser.persistent_chrome_unavailable",
                        error=str(exc)[:160],
                        fallback="installed-executable")
        for executable in _browser_executable_candidates(channel):
            try:
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    executable_path=executable,
                    headless=headless,
                    no_viewport=True,
                    args=args,
                )
                _logger.info(
                    "browser.launched",
                    mode="persistent-executable",
                    executable=executable,
                    profile=user_data_dir,
                )
                return ctx, None
            except Exception as path_exc:                     # noqa: BLE001
                _logger.warning(
                    "browser.installed_executable_failed",
                    executable=executable,
                    error=str(path_exc)[:160],
                )

        _logger.warning("browser.fallback", mode="bundled-chromium")
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        return ctx, browser

_SNAPSHOT_JS = """
(() => {
  const sel = 'a, button, input, select, textarea, summary, ' +
    '[role="button"], [role="link"], [role="menuitem"], [role="tab"], ' +
    '[role="checkbox"], [role="combobox"], [contenteditable="true"]';
  let n = 0;
  const out = [];
  const registered = new Set();

  const register = (el) => {
    if (!el || registered.has(el) || n >= 220) {
      return el ? (el.getAttribute('data-jarvis-ref') || '') : '';
    }
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return '';
    const cs = window.getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') return '';
    n += 1;
    const ref = 'j' + n;
    el.setAttribute('data-jarvis-ref', ref);
    registered.add(el);
    const text = (el.innerText || el.value || el.placeholder ||
                  el.getAttribute('aria-label') || '').trim()
                 .replace(/\\s+/g, ' ').slice(0, 90);
    out.push({ref, tag: el.tagName.toLowerCase(),
              type: el.getAttribute('type') || '',
              text, href: (el.getAttribute('href') || '').slice(0, 120)});
    return ref;
  };

  // Register judul hasil video lebih dahulu. Ini menjamin ref hasil teratas
  // tetap tersedia walau halaman memiliki banyak tombol/anchor lain.
  const youtubeResults = [];
  const cards = location.pathname === '/results'
    ? Array.from(document.querySelectorAll(
      'ytd-video-renderer, ytd-rich-item-renderer, ytd-grid-video-renderer'))
    : [];
  for (const card of cards) {
    const titleEl = card.querySelector(
      'a#video-title, a#video-title-link, a[href^="/watch"]');
    if (!titleEl) continue;
    const href = titleEl.href || titleEl.getAttribute('href') || '';
    if (!href.includes('/watch')) continue;
    const ref = register(titleEl);
    if (!ref) continue;
    const channelEl = card.querySelector(
      '#channel-name a, ytd-channel-name a, #channel-info a');
    const channelHref = channelEl
      ? (channelEl.href || channelEl.getAttribute('href') || '') : '';
    const channelMatch = channelHref.match(/\\/channel\\/([^/?#]+)/);
    const meta = Array.from(card.querySelectorAll('#metadata-line span'))
      .map((node) => (node.textContent || '').trim())
      .filter(Boolean);
    youtubeResults.push({
      rank: youtubeResults.length + 1,
      ref,
      title: (titleEl.textContent || titleEl.getAttribute('aria-label') || '')
        .trim().replace(/\\s+/g, ' ').slice(0, 180),
      channel: channelEl ? (channelEl.textContent || '').trim()
        .replace(/\\s+/g, ' ').slice(0, 120) : '',
      channel_id: (channelMatch ? channelMatch[1] : '').slice(0, 120),
      channel_href: channelHref.slice(0, 240),
      verified: Boolean(card.querySelector(
        'ytd-badge-supported-renderer [aria-label*="Verified"], ' +
        'ytd-badge-supported-renderer .badge-style-type-verified')),
      age: (meta.find((value) => /ago|lalu|streamed|premiered/i.test(value)) ||
            meta[meta.length - 1] || '').slice(0, 80),
      href: href.slice(0, 240),
    });
    if (youtubeResults.length >= 60) break;
  }

  for (const el of Array.from(document.querySelectorAll(sel))) {
    register(el);
    if (n >= 220) break;
  }

  let youtubeWatch = null;
  const watchUrl = new URL(location.href);
  const watchVideoId = watchUrl.hostname.includes('youtu.be')
    ? watchUrl.pathname.split('/').filter(Boolean)[0] || ''
    : watchUrl.searchParams.get('v') || '';
  if (watchVideoId) {
    const playerDetails = (window.ytInitialPlayerResponse &&
      window.ytInitialPlayerResponse.videoDetails) || {};
    const channelEl = document.querySelector(
      'ytd-watch-metadata ytd-channel-name a, #owner ytd-channel-name a, ' +
      '#upload-info #channel-name a');
    const titleEl = document.querySelector(
      'ytd-watch-metadata h1 yt-formatted-string, ' +
      'h1.title yt-formatted-string');
    const channelHref = channelEl
      ? (channelEl.href || channelEl.getAttribute('href') || '') : '';
    const channelMatch = channelHref.match(/\\/channel\\/([^/?#]+)/);
    youtubeWatch = {
      video_id: watchVideoId,
      channel_name: ((channelEl && channelEl.textContent) ||
        playerDetails.author || '').trim().replace(/\\s+/g, ' ').slice(0, 120),
      channel_id: (playerDetails.channelId ||
        (channelMatch ? channelMatch[1] : '')).slice(0, 120),
      channel_href: channelHref.slice(0, 240),
      title: ((titleEl && titleEl.textContent) || playerDetails.title ||
        document.title || '').trim().replace(/\\s+/g, ' ').slice(0, 240),
    };
  }

  const body = (document.body ? document.body.innerText : '')
               .replace(/\\n{3,}/g, '\\n\\n').slice(0, 4000);
  return {title: document.title, url: location.href,
          elements: out, youtube_results: youtubeResults,
          youtube_watch: youtubeWatch, text: body};
})()
"""

_MEDIA_STATE_JS = """
(() => {
  const media = document.querySelector('video.html5-main-video, video');
  const player = document.querySelector('#movie_player');
  const pageUrl = new URL(location.href);
  const pageVideoId = pageUrl.hostname.includes('youtu.be')
    ? pageUrl.pathname.split('/').filter(Boolean)[0] || ''
    : pageUrl.searchParams.get('v') || '';
  let playerData = {};
  try {
    playerData = (player && typeof player.getVideoData === 'function')
      ? (player.getVideoData() || {}) : {};
  } catch (_) {}
  const initialDetails = (window.ytInitialPlayerResponse &&
    window.ytInitialPlayerResponse.videoDetails) || {};
  const playerVideoId = playerData.video_id || initialDetails.videoId || '';
  const activeAdMarker = player ? Array.from(player.querySelectorAll(
    '.ytp-ad-player-overlay, .ytp-ad-text, .ytp-ad-preview-container'))
    .some((node) => {
      const rect = node.getBoundingClientRect();
      const style = window.getComputedStyle(node);
      return rect.width > 1 && rect.height > 1 &&
        style.display !== 'none' && style.visibility !== 'hidden';
    }) : false;
  const isAd = Boolean(player && (
    player.classList.contains('ad-showing') ||
    player.classList.contains('ad-interrupting') ||
    activeAdMarker));
  if (!media) {
    return {found: false, paused: true, ended: false,
            readyState: 0, currentTime: 0, pageVideoId, playerVideoId,
            playerTitle: playerData.title || initialDetails.title || '',
            playerAuthor: playerData.author || initialDetails.author || '',
            isAd};
  }
  const currentTime = Number.isFinite(media.currentTime)
    ? media.currentTime : 0;
    return {found: true, paused: Boolean(media.paused),
          ended: Boolean(media.ended), readyState: Number(media.readyState),
          currentTime,
          duration: Number.isFinite(media.duration) ? media.duration : 0,
          volume: Number.isFinite(media.volume) ? media.volume : 1,
          muted: Boolean(media.muted),
          pageVideoId, playerVideoId,
          playerTitle: playerData.title || initialDetails.title || '',
          playerAuthor: playerData.author || initialDetails.author || '',
          isAd};
})()
"""

_MEDIA_PLAY_JS = """
(async () => {
  const media = document.querySelector('video.html5-main-video, video');
  if (!media) return false;
  await media.play();
  return true;
})()
"""

_MEDIA_CONTROL_JS = """
(async (payload) => {
  const action = String((payload && payload.action) || '').toLowerCase();
  const media = document.querySelector('video.html5-main-video, video');
  const player = document.querySelector('#movie_player');
  const visible = (node) => {
    if (!node) return false;
    const rect = node.getBoundingClientRect();
    const style = window.getComputedStyle(node);
    return rect.width > 1 && rect.height > 1 &&
      style.display !== 'none' && style.visibility !== 'hidden';
  };
  if (action === 'skip_ad') {
    const selectors = [
      '.ytp-skip-ad-button',
      '.ytp-ad-skip-button',
      '.ytp-ad-skip-button-modern',
      'button.ytp-ad-skip-button-modern',
      'button[aria-label*="Skip" i]',
      'button[aria-label*="Lewati" i]'
    ];
    for (const selector of selectors) {
      const button = Array.from(document.querySelectorAll(selector))
        .find(visible);
      if (button) {
        button.click();
        return {changed: true, method: 'button'};
      }
    }
    const isAd = Boolean(player && (
      player.classList.contains('ad-showing') ||
      player.classList.contains('ad-interrupting')));
    if (media && isAd && Number.isFinite(media.duration) && media.duration > 0) {
      media.currentTime = Math.max(0, media.duration - 0.05);
      return {changed: true, method: 'seek'};
    }
    return {changed: false, method: 'no_skippable_ad'};
  }
  if (!media) return {changed: false, method: 'media_not_found'};
  if (action === 'play') {
    await media.play();
  } else if (action === 'pause') {
    media.pause();
  } else if (action === 'toggle') {
    if (media.paused) await media.play(); else media.pause();
  } else if (action === 'mute') {
    media.muted = true;
  } else if (action === 'unmute') {
    media.muted = false;
  } else if (action === 'volume_up') {
    media.muted = false;
    media.volume = Math.min(1, media.volume + 0.1);
  } else if (action === 'volume_down') {
    media.volume = Math.max(0, media.volume - 0.1);
  } else if (action === 'set_volume') {
    const value = Math.max(0, Math.min(1, Number(payload.volume)));
    if (!Number.isFinite(value)) return {changed: false, method: 'bad_volume'};
    media.volume = value;
    media.muted = value === 0;
  } else {
    return {changed: false, method: 'unknown_action'};
  }
  return {changed: true, method: action};
})
"""


class _BrowserHost:
    """Pemilik tunggal instance Playwright — satu thread, satu page."""

    _instance: "_BrowserHost | None" = None
    _lock = threading.Lock()

    @classmethod
    def get(cls, *, dedicated_cdp: bool | None = None) -> "_BrowserHost":
        if dedicated_cdp is None:
            dedicated_cdp = _cdp_enabled()
        with cls._lock:
            if cls._instance is None:
                cls._instance = _BrowserHost(dedicated_cdp=dedicated_cdp)
            elif bool(cls._instance._dedicated_cdp) != bool(dedicated_cdp):
                raise RuntimeError("browser host sudah dimiliki mode lain")
            return cls._instance

    @classmethod
    def peek(cls) -> "_BrowserHost | None":
        with cls._lock:
            return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        with cls._lock:
            cls._instance = None

    def __init__(self, *, dedicated_cdp: bool = False):
        self._jobs: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._state = "stopped"  # stopped | starting | accepting | closing
        self._started = threading.Event()
        self._fail: str | None = None
        self._dedicated_cdp = bool(dedicated_cdp)
        self._cdp_ready = False
        self._cdp_owned = False
        self._console: list[str] = []
        self._dialog_action: tuple[str, str] | None = None
        self._snapshot_ready = False
        self._snapshot_url = ""
        self._snapshot_refs: set[str] = set()
        self._snapshot_owner = ""
        self._lease_lock = threading.Lock()
        self._lease_owner = ""
        self.page = None
        self._context = None

    # ── lifecycle ─────────────────────────────────────────────────────────

    def close(self, timeout: float = 10.0) -> None:
        """Gracefully stop this host within a bounded timeout."""
        bounded = max(0.1, float(timeout))
        with self._lock:
            thread = self._thread
            alive = bool(thread and thread.is_alive())
            if alive and self._state != "closing":
                self._state = "closing"
                self._jobs.put(None)

        # A dead worker is not proof that a dedicated Chrome endpoint is gone.
        # Probe it before clearing ownership so a survivor remains visible and
        # an unknown process is never mistaken for a clean shutdown.
        if not alive:
            if self._dedicated_cdp and not _wait_for_cdp_gone(bounded):
                raise TimeoutError("endpoint CDP dedicated masih reachable")
            with self._lock:
                self._state = "stopped"
                self._thread = None
                self._context = None
                self.page = None
                self._cdp_ready = False
                self._cdp_owned = False
            return

        if threading.current_thread() is thread:
            return
        thread.join(timeout=bounded)
        if thread.is_alive():
            raise TimeoutError("dedicated CDP masih memiliki survivor")
        if self._dedicated_cdp and not _wait_for_cdp_gone(bounded):
            raise TimeoutError("endpoint CDP dedicated masih reachable")
        with self._lock:
            self._state = "stopped"
            self._thread = None
            self._context = None
            self.page = None
            self._cdp_ready = False
            self._cdp_owned = False

    def _ensure(self) -> None:
        while True:
            wait_started = False
            closing_thread = None
            with self._lock:
                thread = self._thread
                alive = bool(thread and thread.is_alive())
                if self._state == "accepting" and alive:
                    return
                if self._state == "starting" and alive:
                    wait_started = True
                elif self._state == "closing" and alive:
                    closing_thread = thread
                else:
                    self._started.clear()
                    self._fail = None
                    self._state = "starting"
                    self._thread = threading.Thread(
                        target=self._main, daemon=True, name="agent-browser")
                    self._thread.start()
                    wait_started = True

            if closing_thread is not None:
                closing_thread.join(timeout=5)
                if closing_thread.is_alive():
                    raise RuntimeError(
                        "browser sedang menutup context lama; coba lagi")
                continue
            if wait_started and not self._started.wait(timeout=60):
                raise RuntimeError("browser tidak kunjung siap (60s)")
            if self._fail:
                raise RuntimeError(self._fail)
            # Confirm accepting state under the lifecycle lock. A very short
            # idle limit may already have moved the host to closing.

    def _main(self) -> None:
        ctx = None
        browser = None
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                headless = bool(config.get("agent.browser.headless", True))
                ctx, browser = _launch_browser(
                    pw, headless, dedicated_cdp=self._dedicated_cdp)
                self._context = ctx
                self._set_page(ctx.pages[0] if ctx.pages else ctx.new_page())
                if self._dedicated_cdp:
                    if not _wait_for_cdp():
                        raise RuntimeError("CDP dedicated tidak siap dalam batas waktu")
                    self._cdp_ready = True
                    self._cdp_owned = True
                with self._lock:
                    self._state = "accepting"
                self._started.set()
                idle_limit = float(config.get(
                    "agent.browser.idle_close_s", 900))
                last = time.monotonic()
                while True:
                    try:
                        job = self._jobs.get(timeout=5)
                    except queue.Empty:
                        if time.monotonic() - last > idle_limit:
                            with self._lock:
                                with self._lease_lock:
                                    can_close = (
                                        self._state == "accepting"
                                        and not self._lease_owner
                                        and self._jobs.empty()
                                    )
                                    if can_close:
                                        self._state = "closing"
                            if can_close:
                                _logger.info("browser.idle_close")
                                break
                        continue
                    if job is None:
                        with self._lock:
                            self._state = "closing"
                        break
                    fn, fut = job
                    last = time.monotonic()
                    try:
                        if self.page is None or self.page.is_closed():
                            pages = [
                                page for page in ctx.pages
                                if not page.is_closed()
                            ]
                            self._set_page(
                                pages[-1] if pages else ctx.new_page()
                            )
                        fut.set_result(fn(self.page))
                    except Exception as e:                   # noqa: BLE001
                        fut.set_exception(e)
                        if _is_target_closed(e):
                            with self._lock:
                                self._state = "closing"
                            _logger.warning(
                                "browser.context_lost",
                                error=type(e).__name__,
                                recovery="restart-once",
                            )
                            break
                try:
                    ctx.close()
                except Exception:                            # noqa: BLE001
                    pass
                if browser is not None:
                    try:
                        browser.close()
                    except Exception:                        # noqa: BLE001
                        pass
        except Exception as e:                               # noqa: BLE001
            # Readiness failures happen before the normal worker loop reaches
            # its close block. Close only the resources this host just opened;
            # never kill or attach to an unrelated process.
            for resource in (ctx, browser):
                if resource is None:
                    continue
                try:
                    resource.close()
                except Exception:                            # noqa: BLE001
                    pass
            self._fail = f"playwright gagal start: {str(e)[:200]}"
            _logger.error("browser.start_failed", error=self._fail)
            self._started.set()
        finally:
            self.page = None
            self._context = None
            self._cdp_ready = False
            self._cdp_owned = False
            with self._lock:
                with self._lease_lock:
                    self.invalidate_snapshot()
                    self._dialog_action = None
                    self._lease_owner = ""
                self._state = "stopped"
                self._thread = None
                pending: list[Future] = []
                while True:
                    try:
                        queued = self._jobs.get_nowait()
                    except queue.Empty:
                        break
                    if queued is not None:
                        pending.append(queued[1])
            for future in pending:
                if not future.done():
                    future.set_exception(RuntimeError(
                        "browser host berhenti sebelum job dijalankan"))

    def _on_console(self, msg) -> None:
        self._console.append(f"[{msg.type}] {msg.text[:300]}")
        del self._console[:-80]

    def _on_dialog(self, dialog) -> None:
        action, text = self._dialog_action or ("dismiss", "")
        self._dialog_action = None
        try:
            if action == "accept":
                dialog.accept(text or None)
            else:
                dialog.dismiss()
        except Exception:                                    # noqa: BLE001
            pass

    def _set_page(self, page) -> None:
        """Select the active page and attach observers exactly once."""

        self.page = page
        try:
            if not getattr(page, "_jarvis_observers_bound", False):
                page.on("console", self._on_console)
                page.on("dialog", self._on_dialog)
                setattr(page, "_jarvis_observers_bound", True)
        except Exception:                                    # noqa: BLE001
            # Some Playwright proxy objects reject custom attributes. Event
            # handlers are idempotent enough for the rare replacement path.
            try:
                page.on("console", self._on_console)
                page.on("dialog", self._on_dialog)
            except Exception:
                pass

    # ── pemanggilan dari tool async ───────────────────────────────────────

    def call(self, fn, timeout: float = 60):
        deadline = time.monotonic() + max(0.1, float(timeout))
        last_error: BaseException | None = None
        for attempt in range(2):
            while True:
                self._ensure()
                future: Future = Future()
                with self._lock:
                    thread = self._thread
                    if (self._state == "accepting" and thread is not None
                            and thread.is_alive()):
                        self._jobs.put((fn, future))
                        break
            try:
                remaining = max(0.1, deadline - time.monotonic())
                return future.result(timeout=remaining)
            except Exception as exc:                         # noqa: BLE001
                last_error = exc
                if attempt or not _is_target_closed(exc):
                    raise
                # The host thread marks itself closing on TargetClosed.  The
                # next _ensure waits for cleanup and starts a fresh context.
                continue
        raise last_error or RuntimeError("browser recovery gagal")

    def console_tail(self) -> list[str]:
        return list(self._console)

    def set_dialog(self, action: str, text: str) -> None:
        self._dialog_action = (action, text)

    # ── session lease ──────────────────────────────────────────────────

    def claim_session(self, owner: str) -> None:
        """Serialize every stateful use of the singleton page by task."""

        owner = str(owner or "").strip()
        if not owner:
            raise RuntimeError("browser lease membutuhkan session owner")
        while True:
            closing_thread = None
            with self._lock:
                if self._state == "closing":
                    closing_thread = self._thread
                else:
                    with self._lease_lock:
                        if self._lease_owner and self._lease_owner != owner:
                            raise RuntimeError(
                                "browser lease milik sesi lain; tunggu tugas "
                                "browser tersebut selesai")
                        self._lease_owner = owner
                    return
            if closing_thread is None:
                continue
            closing_thread.join(timeout=5)
            if closing_thread.is_alive():
                raise RuntimeError(
                    "browser sedang menutup context lama; coba lagi")

    def release_session(self, owner: str) -> None:
        """Release only the matching owner; never steal another task's page."""

        owner = str(owner or "").strip()
        if not owner:
            return
        with self._lease_lock:
            if self._lease_owner == owner:
                # Cleanup must finish before another claimant can observe an
                # empty owner; otherwise release A could erase snapshot B.
                self.invalidate_snapshot()
                self._dialog_action = None
                self._lease_owner = ""

    def release_session_after_pending(
        self, owner: str, timeout: float = 5.0,
    ) -> None:
        """Queue cleanup behind in-flight page jobs, then release atomically."""

        with self._lock:
            thread = self._thread
            accepting = bool(
                self._state == "accepting" and thread and thread.is_alive())
        if not accepting or threading.current_thread() is thread:
            self.release_session(owner)
            return

        future: Future = Future()

        def _release(_page):
            self.release_session(owner)

        # While this barrier waits in the host queue, owner remains claimed,
        # so a second task is rejected before it can enqueue page work.
        with self._lock:
            if (self._state != "accepting" or self._thread is not thread
                    or not thread.is_alive()):
                self.release_session(owner)
                return
            self._jobs.put((_release, future))
        try:
            future.result(timeout=max(0.1, float(timeout)))
        except TimeoutError:
            # The queued barrier remains live and will release safely when a
            # long-running page job eventually returns.
            _logger.warning("browser.lease_release_pending", owner=owner[:32])

    # ── snapshot guard ─────────────────────────────────────────────────

    def invalidate_snapshot(self) -> None:
        """Batalkan semua ref ketika page/DOM mungkin sudah berubah."""
        self._snapshot_ready = False
        self._snapshot_url = ""
        self._snapshot_refs.clear()
        self._snapshot_owner = ""

    def record_snapshot(self, snap: dict, owner: str = "") -> None:
        """Catat hanya ref yang benar-benar berasal dari snapshot terbaru."""
        self._snapshot_url = str(snap.get("url", ""))
        self._snapshot_refs = {
            str(item.get("ref", ""))
            for item in snap.get("elements", [])
            if isinstance(item, dict) and item.get("ref")
        }
        self._snapshot_owner = str(owner or "")
        self._snapshot_ready = True

    def consume_snapshot(self, operation: str, ref: str = "",
                         selector: str = "", owner: str = "") -> None:
        """Wajibkan satu snapshot baru untuk tepat satu click/type."""
        if selector.strip():
            raise ValueError(
                f"{operation}: selector CSS buta dilarang; gunakan ref dari "
                "browser_snapshot")
        ref = ref.strip()
        if not ref:
            raise ValueError(
                f"{operation}: ref dari browser_snapshot wajib diisi")
        if not self._snapshot_ready:
            raise RuntimeError(
                f"{operation}: browser_snapshot baru wajib sebelum aksi")
        if str(owner or "") != self._snapshot_owner:
            raise RuntimeError(
                f"{operation}: ref snapshot milik sesi lain; ambil "
                "browser_snapshot baru")
        if ref not in self._snapshot_refs:
            raise ValueError(
                f"{operation}: ref {ref!r} tidak ada pada snapshot terbaru")
        # Dikonsumsi sebelum aksi: kegagalan klik/type pun tidak boleh membuat
        # model mengulang memakai state yang mungkin sudah berubah.
        self.invalidate_snapshot()

    def consume_snapshot_for_media_play(self, owner: str = "") -> None:
        if not self._snapshot_ready:
            raise RuntimeError(
                "browser_media play: browser_snapshot baru wajib sebelum aksi")
        if str(owner or "") != self._snapshot_owner:
            raise RuntimeError(
                "browser_media play: snapshot milik sesi lain; ambil "
                "browser_snapshot baru")
        self.invalidate_snapshot()


def _owner_id(session) -> str:
    """Owner kosong dipakai hanya oleh direct call/test di luar registry."""
    inherited = getattr(session, "_browser_lease_owner", "")
    return str(inherited or getattr(session, "id", "") or "")


_compat_host = None


def _claim_host(session):
    """Return the singleton after claiming it for a real agent session.

    Owner-less calls are retained only for direct unit tests and legacy local
    callers outside the registry. Runtime tools receive ``_session`` through
    ``wants_context`` and therefore always participate in the lease.
    """

    # ``get()`` resolves the configured default mode. Keeping the call
    # argument-free preserves the contract of small host fakes used by the
    # existing browser lease tests while the default config still selects the
    # dedicated CDP lane.
    host = _BrowserHost.get()
    global _compat_host
    _compat_host = host
    owner = _owner_id(session)
    if owner:
        host.claim_session(owner)
    return host, owner


def release_browser_session(session_id: str) -> None:
    """Release an existing browser lease without starting a browser."""

    global _compat_host
    host = _BrowserHost.peek() or _compat_host
    if host is None:
        return
    release = getattr(host, "release_session_after_pending", None)
    if callable(release):
        release(str(session_id or ""))
    else:  # Contract fakes and compatibility hosts.
        host.release_session(str(session_id or ""))
    if host is _compat_host:
        _compat_host = None


def shutdown_browser_cdp() -> None:
    """Stop the owned host if it exists; never create one during shutdown."""
    host = _BrowserHost.peek()
    if host is None or not host._dedicated_cdp:
        return
    host.close(timeout=_cdp_timeout("close_timeout_s", 10.0))


def browser_cdp_status() -> dict:
    """Aggregate CDP status for lifecycle callers; no page metadata."""
    try:
        port = _cdp_port()
    except ValueError as exc:
        return {
            "owned": False, "state": "stopped", "port": None,
            "ready": False, "tabs": 0, "reason": str(exc),
        }
    host = _BrowserHost.peek()
    if host is None or not host._dedicated_cdp:
        return {
            "owned": False, "state": "stopped", "port": port,
            "ready": False, "tabs": 0,
            "reason": "dedicated CDP belum dimulai",
        }
    ready = bool(host._cdp_ready and host._state == "accepting")
    tabs = 0
    if ready:
        try:
            tabs = len(host._context.pages) if host._context else 0
        except Exception:  # noqa: BLE001
            tabs = 0
    return {
        "owned": bool(host._cdp_owned),
        "state": str(host._state),
        "port": port,
        "ready": ready,
        "tabs": tabs,
        "reason": str(host._fail or "")[:200],
    }


def ensure_browser_cdp() -> dict:
    """Ensure the one dedicated host is accepting, with bounded startup."""
    host = _BrowserHost.get()
    host._ensure()
    return browser_cdp_status()


__all__ = [
    "browser_cdp_status",
    "ensure_browser_cdp",
    "release_browser_session",
    "shutdown_browser_cdp",
]


# Public aliases used by integration facades without a second owner.
status_browser_cdp = browser_cdp_status
ensure_cdp = ensure_browser_cdp
shutdown_cdp = shutdown_browser_cdp


def _target(page, ref: str = "", selector: str = ""):
    if ref:
        return page.locator(f'[data-jarvis-ref="{ref}"]').first
    if selector:
        raise ValueError("selector CSS buta dilarang; gunakan ref snapshot")
    raise ValueError("butuh ref dari browser_snapshot")


def _snapshot(page) -> dict:
    return page.evaluate(_SNAPSHOT_JS)


def _media_state(page) -> dict:
    raw = page.evaluate(_MEDIA_STATE_JS) or {}
    state = {
        "url": str(page.url),
        "title": str(page.title()),
        "found": bool(raw.get("found", False)),
        "paused": bool(raw.get("paused", True)),
        "ended": bool(raw.get("ended", False)),
        "readyState": int(raw.get("readyState", 0) or 0),
        "currentTime": float(raw.get("currentTime", 0.0) or 0.0),
        "duration": float(raw.get("duration", 0.0) or 0.0),
        "volume": float(raw.get("volume", 1.0) or 0.0),
        "muted": bool(raw.get("muted", False)),
        "pageVideoId": str(raw.get("pageVideoId", "") or ""),
        "playerVideoId": str(raw.get("playerVideoId", "") or ""),
        "playerTitle": str(raw.get("playerTitle", "") or ""),
        "playerAuthor": str(raw.get("playerAuthor", "") or ""),
        "isAd": bool(raw.get("isAd", False)),
    }
    state["playing"] = bool(
        state["found"] and not state["paused"] and not state["ended"]
        and state["readyState"] >= 2 and not state["isAd"])
    return state


def _render_snapshot(snap: dict) -> str:
    lines = [f"URL: {snap.get('url')}", f"Judul: {snap.get('title')}", "",
             "Elemen interaktif (pakai ref untuk click/type):"]
    for el in snap.get("elements", []):
        extra = f" type={el['type']}" if el.get("type") else ""
        href = f" → {el['href']}" if el.get("href") else ""
        lines.append(f"  [{el['ref']}] <{el['tag']}{extra}> "
                     f"{el.get('text', '')}{href}")
    results = snap.get("youtube_results", [])
    if results:
        lines += ["", "Hasil video YouTube terurut:"]
        for item in results:
            lines.append(
                f"  #{item.get('rank')} [{item.get('ref')}] "
                f"{item.get('title', '')} | channel={item.get('channel', '')} "
                f"| channel_id={item.get('channel_id', '')} "
                f"| channel_href={item.get('channel_href', '')} "
                f"| age={item.get('age', '')} | {item.get('href', '')}")
    watch = snap.get("youtube_watch")
    if isinstance(watch, dict):
        lines += [
            "",
            "Bukti halaman watch YouTube:",
            f"  video_id={watch.get('video_id', '')}",
            f"  title={watch.get('title', '')}",
            f"  channel_name={watch.get('channel_name', '')}",
            f"  channel_id={watch.get('channel_id', '')}",
            f"  channel_href={watch.get('channel_href', '')}",
        ]
    text = snap.get("text", "")
    if text:
        lines += ["", "Teks halaman (cuplikan):", text]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# Tools
# ═══════════════════════════════════════════════════════════════════════════

class _NavParams(BaseModel):
    url: str = Field(description="URL tujuan")


class BrowserNavigate(Tool):
    name = "browser_navigate"
    description = ("Buka URL di browser agent (Chromium persisten). "
                   "Setelahnya WAJIB browser_snapshot sebelum berinteraksi.")
    params_schema = _NavParams
    wants_context = True
    timeout_s = 90

    async def run(self, url: str, _session=None, **_) -> ToolResult:
        url = str(url or "").strip()
        if url.casefold() == "about:blank":
            url = "about:blank"
        elif not url.lower().startswith(("http://", "https://")):
            url = "https://" + url

        host, _owner = _claim_host(_session)

        def _go(page):
            host.invalidate_snapshot()
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            return page.title()

        title = await asyncio.to_thread(host.call, _go, 80)
        return ToolResult.success(f"terbuka: {title} ({url})",
                                  display=f"→ {url[:60]}")


class BrowserSnapshot(Tool):
    name = "browser_snapshot"
    description = ("Snapshot halaman: URL, judul, daftar elemen interaktif "
                   "ber-ref, dan cuplikan teks. Ini 'mata' utamamu di "
                   "browser — panggil sebelum click/type.")
    read_only = True
    wants_context = True
    timeout_s = 60

    async def run(self, _session=None, **_) -> ToolResult:
        host, owner = _claim_host(_session)

        def _take(page):
            snap = _snapshot(page)
            host.record_snapshot(snap, owner=owner)
            return snap

        snap = await asyncio.to_thread(host.call, _take, 45)
        return ToolResult.success(_render_snapshot(snap),
                                  display=f"{len(snap.get('elements', []))} "
                                          f"elemen",
                                  snapshot=snap)


class _ClickParams(BaseModel):
    ref: str = Field(description="Ref dari browser_snapshot, mis. 'j12'")


class BrowserClick(Tool):
    name = "browser_click"
    description = ("Klik elemen memakai ref dari browser_snapshot terbaru. "
                   "Satu snapshot hanya berlaku untuk satu aksi.")
    params_schema = _ClickParams
    wants_context = True
    timeout_s = 45

    async def run(self, ref: str = "", selector: str = "", _session=None,
                  **_) -> ToolResult:
        host, owner = _claim_host(_session)

        def _click(page):
            host.consume_snapshot("browser_click", ref, selector,
                                  owner=owner)
            _target(page, ref, selector).click(timeout=12_000)
            page.wait_for_load_state("domcontentloaded", timeout=12_000)
            return page.url

        url = await asyncio.to_thread(host.call, _click, 40)
        return ToolResult.success(f"diklik; sekarang di {url}",
                                  display=f"klik {ref}")


class _TypeParams(BaseModel):
    text: str = Field(description="Teks yang diketik")
    ref: str = Field(description="Ref elemen input dari snapshot")
    submit: bool = Field(False, description="Tekan Enter setelah mengetik")


class BrowserType(Tool):
    name = "browser_type"
    description = "Isi field input dengan teks (opsional tekan Enter)."
    params_schema = _TypeParams
    wants_context = True
    timeout_s = 45

    async def run(self, text: str, ref: str = "", selector: str = "",
                  submit: bool = False, _session=None, **_) -> ToolResult:
        host, owner = _claim_host(_session)

        def _type(page):
            host.consume_snapshot("browser_type", ref, selector,
                                  owner=owner)
            el = _target(page, ref, selector)
            el.fill(text, timeout=12_000)
            if submit:
                el.press("Enter")
                page.wait_for_load_state("domcontentloaded", timeout=12_000)
            return page.url

        url = await asyncio.to_thread(host.call, _type, 40)
        return ToolResult.success(
            f"teks diisi{' + Enter' if submit else ''}; di {url}")


class _PressParams(BaseModel):
    key: str = Field(description="Tombol, mis. 'Enter', 'PageDown', 'Tab'")


class BrowserPress(Tool):
    name = "browser_press"
    description = "Tekan satu tombol keyboard pada halaman."
    params_schema = _PressParams
    wants_context = True
    timeout_s = 30

    async def run(self, key: str, _session=None, **_) -> ToolResult:
        host, _owner = _claim_host(_session)

        def _press(page):
            host.invalidate_snapshot()
            page.keyboard.press(key)

        await asyncio.to_thread(host.call, _press, 20)
        return ToolResult.success(f"tekan {key}")


class _ScrollParams(BaseModel):
    direction: str = Field("down", description="up | down")
    amount: int = Field(600, description="Piksel")


class BrowserScroll(Tool):
    name = "browser_scroll"
    description = "Scroll halaman ke atas/bawah."
    params_schema = _ScrollParams
    wants_context = True
    timeout_s = 30

    async def run(self, direction: str = "down", amount: int = 600,
                  _session=None, **_) -> ToolResult:
        dy = abs(int(amount)) * (-1 if direction == "up" else 1)
        host, _owner = _claim_host(_session)

        def _scroll(page):
            host.invalidate_snapshot()
            page.mouse.wheel(0, dy)

        await asyncio.to_thread(host.call, _scroll, 20)
        return ToolResult.success(f"scroll {direction} {abs(dy)}px")


class BrowserBack(Tool):
    name = "browser_back"
    description = "Kembali ke halaman sebelumnya."
    wants_context = True
    timeout_s = 45

    async def run(self, _session=None, **_) -> ToolResult:
        host, _owner = _claim_host(_session)

        def _back(page):
            host.invalidate_snapshot()
            page.go_back(wait_until="domcontentloaded", timeout=20_000)
            return page.url
        url = await asyncio.to_thread(host.call, _back, 40)
        return ToolResult.success(f"kembali ke {url}")


def _tab_inventory(page) -> list[dict]:
    pages = [candidate for candidate in page.context.pages
             if not candidate.is_closed()]
    out = []
    for index, candidate in enumerate(pages):
        try:
            title = candidate.title()
        except Exception:                                    # noqa: BLE001
            title = ""
        out.append({
            "index": index,
            "active": candidate is page,
            "title": title,
            "url": str(candidate.url),
        })
    return out


class BrowserTabs(Tool):
    name = "browser_tabs"
    description = (
        "Daftar semua tab dalam browser agent beserta index, judul, URL, "
        "dan penanda tab aktif."
    )
    read_only = True
    wants_context = True
    timeout_s = 20

    async def run(self, _session=None, **_) -> ToolResult:
        host, _owner = _claim_host(_session)
        tabs = await asyncio.to_thread(host.call, _tab_inventory, 15)
        return ToolResult.success(tabs, display=f"{len(tabs)} tab browser")


class _NewTabParams(BaseModel):
    url: str = Field("about:blank", description="URL tab baru")


class BrowserNewTab(Tool):
    name = "browser_new_tab"
    description = "Buat tab baru di browser agent dan jadikan tab aktif."
    params_schema = _NewTabParams
    wants_context = True
    timeout_s = 45

    async def run(self, url: str = "about:blank", _session=None,
                  **_) -> ToolResult:
        target = str(url or "about:blank").strip()
        if target.casefold() != "about:blank" and not target.lower().startswith(
                ("http://", "https://")):
            target = "https://" + target
        host, _owner = _claim_host(_session)

        def _new(page):
            host.invalidate_snapshot()
            created = page.context.new_page()
            host._set_page(created)
            if target != "about:blank":
                created.goto(
                    target, wait_until="domcontentloaded", timeout=30_000
                )
            return _tab_inventory(created)

        tabs = await asyncio.to_thread(host.call, _new, 40)
        active = next((tab for tab in tabs if tab["active"]), tabs[-1])
        return ToolResult.success(
            active, display=f"tab baru: {active.get('title') or active['url']}"
        )


class _TabIndexParams(BaseModel):
    index: int = Field(description="Index tab dari browser_tabs (0-based)")


class BrowserSwitchTab(Tool):
    name = "browser_switch_tab"
    description = "Pindah ke tab browser agent berdasarkan index browser_tabs."
    params_schema = _TabIndexParams
    wants_context = True
    timeout_s = 20

    async def run(self, index: int, _session=None, **_) -> ToolResult:
        host, _owner = _claim_host(_session)

        def _switch(page):
            pages = [candidate for candidate in page.context.pages
                     if not candidate.is_closed()]
            if not 0 <= int(index) < len(pages):
                raise ValueError(
                    f"index tab {index} di luar rentang 0-{max(0, len(pages)-1)}"
                )
            host.invalidate_snapshot()
            target = pages[int(index)]
            host._set_page(target)
            target.bring_to_front()
            return _tab_inventory(target)

        try:
            tabs = await asyncio.to_thread(host.call, _switch, 15)
        except ValueError as exc:
            return ToolResult.fail(str(exc))
        active = next(tab for tab in tabs if tab["active"])
        return ToolResult.success(active, display=f"tab aktif #{active['index']}")


class _CloseTabParams(BaseModel):
    index: int = Field(
        -1, description="-1 menutup tab aktif; selain itu index browser_tabs"
    )


class BrowserCloseTab(Tool):
    name = "browser_close_tab"
    description = (
        "Tutup tab di browser agent. Default -1 menutup tab aktif, lalu "
        "memilih tab tersisa tanpa mematikan context browser."
    )
    params_schema = _CloseTabParams
    wants_context = True
    timeout_s = 25

    async def run(self, index: int = -1, _session=None, **_) -> ToolResult:
        host, _owner = _claim_host(_session)

        def _close(page):
            pages = [candidate for candidate in page.context.pages
                     if not candidate.is_closed()]
            if not pages:
                replacement = page.context.new_page()
                host._set_page(replacement)
                return {"closed": False, "tabs": _tab_inventory(replacement)}
            active_index = pages.index(page) if page in pages else len(pages) - 1
            chosen = active_index if int(index) < 0 else int(index)
            if not 0 <= chosen < len(pages):
                raise ValueError(
                    f"index tab {index} di luar rentang 0-{len(pages)-1}"
                )
            target = pages[chosen]
            closed = {
                "index": chosen,
                "url": str(target.url),
                "title": target.title(),
            }
            # Closing the last page can tear down some persistent contexts.
            # Create the replacement first so the host always retains a page.
            if len(pages) == 1:
                replacement = page.context.new_page()
            else:
                candidates = [item for item in pages if item is not target]
                replacement = candidates[min(chosen, len(candidates) - 1)]
            host.invalidate_snapshot()
            target.close()
            host._set_page(replacement)
            replacement.bring_to_front()
            return {
                "closed": True,
                "tab": closed,
                "tabs": _tab_inventory(replacement),
            }

        try:
            outcome = await asyncio.to_thread(host.call, _close, 20)
        except ValueError as exc:
            return ToolResult.fail(str(exc))
        title = outcome.get("tab", {}).get("title") or \
            outcome.get("tab", {}).get("url") or "tab"
        return ToolResult.success(
            outcome, display=f"tab ditutup: {str(title)[:80]}"
        )


class _MediaParams(BaseModel):
    action: str = Field(
        "status",
        description=(
            "status | play | pause | toggle | mute | unmute | volume_up | "
            "volume_down | set_volume | skip_ad"
        ),
    )
    expected_video_id: str = Field(
        "",
        description=(
            "Video ID dari youtube_watch. Isi untuk kontrak playback yang "
            "harus memverifikasi target; kosong untuk mengontrol video aktif."
        ),
    )
    volume: float | None = Field(
        None, description="Volume 0.0-1.0 untuk action set_volume"
    )


class BrowserMedia(Tool):
    name = "browser_media"
    description = (
        "Kontrol media pada page Playwright aktif: status/play/pause/toggle, "
        "mute, volume, dan skip iklan YouTube. Jika expected_video_id diisi, "
        "play memakai verifikasi ketat snapshot + ID + currentTime; tanpa ID "
        "tool mengontrol video yang sedang aktif secara langsung.")
    params_schema = _MediaParams
    wants_context = True
    timeout_s = 30

    async def run(self, action: str = "status", expected_video_id: str = "",
                  volume: float | None = None, _session=None, **_) -> ToolResult:
        action = str(action or "status").strip().casefold()
        expected_video_id = str(expected_video_id or "").strip()
        allowed = {
            "status", "play", "pause", "toggle", "mute", "unmute",
            "volume_up", "volume_down", "set_volume", "skip_ad",
        }
        if action not in allowed:
            return ToolResult.fail(
                "action browser_media tidak dikenal")
        if action == "set_volume" and volume is None:
            return ToolResult.fail(
                "volume 0.0-1.0 wajib untuk action set_volume")
        if volume is not None and not 0.0 <= float(volume) <= 1.0:
            return ToolResult.fail("volume harus berada pada rentang 0.0-1.0")

        host, owner = _claim_host(_session)

        def _media(page):
            def _bind_target(state):
                state["targetVideoId"] = expected_video_id
                state["targetMatched"] = bool(
                    expected_video_id
                    and state.get("pageVideoId") == expected_video_id
                    and state.get("playerVideoId") == expected_video_id
                    and not state.get("isAd"))
                return state

            def _target_error(state):
                if state.get("isAd"):
                    return ("player sedang menampilkan iklan/pre-roll; "
                            "playback target belum terverifikasi")
                if state.get("pageVideoId") != expected_video_id:
                    return ("video ID halaman tidak cocok dengan target: "
                            f"{state.get('pageVideoId') or '(kosong)'}")
                if state.get("playerVideoId") != expected_video_id:
                    return ("data player tidak cocok dengan target video: "
                            f"{state.get('playerVideoId') or '(kosong)'}")
                return ""

            if action == "status":
                state = _bind_target(_media_state(page))
                state["action"] = "status"
                return state

            # The strict contract is retained for "play latest video X":
            # snapshot and both video IDs must match. Everyday pause/volume
            # commands are bounded to the current page and need no DOM ref.
            if action == "play" and expected_video_id:
                host.consume_snapshot_for_media_play(owner=owner)
            before = _bind_target(_media_state(page))
            if action == "play" and expected_video_id:
                target_error = _target_error(before)
                if target_error:
                    return {"error": target_error, "media": before}
            if action != "skip_ad" and not before["found"]:
                return {"error": "elemen video tidak ditemukan", "media": before}

            try:
                if action == "play":
                    changed = bool(page.evaluate(_MEDIA_PLAY_JS))
                    method = "play"
                else:
                    raw_change = page.evaluate(
                        _MEDIA_CONTROL_JS,
                        {"action": action, "volume": volume},
                    ) or {}
                    changed = bool(raw_change.get("changed", False))
                    method = str(raw_change.get("method", action))
            except Exception as exc:                         # noqa: BLE001
                after = _bind_target(_media_state(page))
                return {
                    "error": f"perintah media ditolak: {str(exc)[:160]}",
                    "media": after,
                }
            if not changed:
                message = (
                    "tidak ada iklan yang bisa dilewati"
                    if action == "skip_ad"
                    else "elemen media tidak berubah"
                )
                return {"error": message, "media": before}

            page.wait_for_timeout(900 if action == "play" else 250)
            after = _bind_target(_media_state(page))
            after.update({
                "action": action,
                "method": method,
                "previousCurrentTime": before["currentTime"],
            })
            if action == "play":
                if expected_video_id:
                    target_error = _target_error(after)
                    if target_error:
                        return {"error": target_error, "media": after}
                advanced = after["currentTime"] > before["currentTime"] + 0.05
                after["timeAdvanced"] = advanced
                after["playing"] = bool(
                    after["playing"]
                    and (not expected_video_id or after["targetMatched"])
                    and advanced
                )
                if not after["playing"]:
                    return {
                        "error": (
                            "playback tidak terverifikasi: video masih pause/"
                            "ended, belum siap, atau currentTime tidak maju"
                        ),
                        "media": after,
                    }
            elif action == "pause" and not after["paused"]:
                return {"error": "video belum ter-pause", "media": after}
            elif action == "mute" and not after["muted"]:
                return {"error": "media belum mute", "media": after}
            elif action == "unmute" and after["muted"]:
                return {"error": "media masih mute", "media": after}
            return {"media": after}

        outcome = await asyncio.to_thread(host.call, _media, 25)
        if outcome.get("error"):
            state = outcome.get("media", {})
            error = str(outcome["error"])
            # Tetap berikan state konkret ke LLM agar laporan gagalnya tidak
            # mengarang. ``meta`` dipertahankan untuk validator/telemetri.
            return ToolResult(
                ok=False,
                content={"error": error, **state},
                display="media gagal diverifikasi",
                error=error,
                meta={"media": state},
            )

        state = outcome.get("media", outcome)
        if action == "status":
            display = ("media playing" if state.get("playing")
                       else "media tidak playing")
        elif action == "skip_ad":
            display = f"iklan dilewati ({state.get('method', 'unknown')})"
        elif action in {"volume_up", "volume_down", "set_volume"}:
            display = f"volume media {float(state.get('volume', 0)) * 100:.0f}%"
        else:
            display = f"media {action}"
        return ToolResult.success(state, display=display)


class BrowserVision(Tool):
    name = "browser_vision"
    description = ("Screenshot halaman saat ini → simpan PNG, kembalikan "
                   "path (analisis dengan vision_analyze).")
    read_only = True
    wants_context = True
    timeout_s = 60

    async def run(self, _session=None, **_) -> ToolResult:
        path = generated_dir() / f"browser_{int(time.time())}.png"
        host, _owner = _claim_host(_session)

        def _shot(page):
            page.screenshot(path=str(path), full_page=False)
            return str(path)

        p = await asyncio.to_thread(host.call, _shot, 45)
        return ToolResult.success(f"screenshot halaman: {p}", path=p)


class _ImagesParams(BaseModel):
    selector: str = Field("img", description="Selector gambar")


class BrowserGetImages(Tool):
    name = "browser_get_images"
    description = "Daftar URL gambar pada halaman."
    params_schema = _ImagesParams
    read_only = True
    wants_context = True
    timeout_s = 30

    async def run(self, selector: str = "img", _session=None,
                  **_) -> ToolResult:
        host, _owner = _claim_host(_session)

        def _imgs(page):
            return page.eval_on_selector_all(
                selector, "els => els.map(e => e.currentSrc || e.src)"
                          ".filter(Boolean).slice(0, 40)")
        urls = await asyncio.to_thread(host.call, _imgs, 25)
        return ToolResult.success("\n".join(urls) or "(tidak ada gambar)",
                                  display=f"{len(urls)} gambar")


class _ConsoleParams(BaseModel):
    script: str = Field("", description="JS yang dieksekusi (kosong = baca "
                                        "log console saja)")


class BrowserConsole(Tool):
    name = "browser_console"
    description = "Baca log console halaman, atau eksekusi JavaScript."
    params_schema = _ConsoleParams
    wants_context = True
    timeout_s = 45

    async def run(self, script: str = "", _session=None, **_) -> ToolResult:
        host, _owner = _claim_host(_session)
        if not script:
            tail = host.console_tail()
            return ToolResult.success("\n".join(tail) or "(console kosong)",
                                      display=f"{len(tail)} log")

        def _execute(page):
            host.invalidate_snapshot()
            return page.evaluate(script)

        result = await asyncio.to_thread(host.call, _execute, 40)
        import json
        try:
            out = json.dumps(result, ensure_ascii=False, default=str)[:8000]
        except Exception:                                    # noqa: BLE001
            out = str(result)[:8000]
        return ToolResult.success(out, display="JS dieksekusi")


class _DialogParams(BaseModel):
    action: str = Field("accept", description="accept | dismiss")
    text: str = Field("", description="Teks untuk prompt() bila accept")


class BrowserDialog(Tool):
    name = "browser_dialog"
    description = ("Atur respons untuk dialog (alert/confirm/prompt) "
                   "BERIKUTNYA yang muncul.")
    params_schema = _DialogParams
    wants_context = True
    timeout_s = 10

    async def run(self, action: str = "accept", text: str = "",
                  _session=None, **_) -> ToolResult:
        host, _owner = _claim_host(_session)
        host.set_dialog(
            "accept" if action == "accept" else "dismiss", text)
        return ToolResult.success(f"dialog berikutnya akan di-{action}")


class _CdpParams(BaseModel):
    method: str = Field(description="Metode CDP, mis. 'Page.captureSnapshot'")
    params: dict = Field(default_factory=dict)


class BrowserCdp(Tool):
    name = "browser_cdp"
    description = "Panggilan Chrome DevTools Protocol mentah (lanjutan)."
    params_schema = _CdpParams
    wants_context = True
    timeout_s = 45

    async def run(self, method: str, params: dict | None = None,
                  _session=None, **_) -> ToolResult:
        host, _owner = _claim_host(_session)

        def _cdp(page):
            host.invalidate_snapshot()
            session = page.context.new_cdp_session(page)
            try:
                return session.send(method, params or {})
            finally:
                session.detach()

        result = await asyncio.to_thread(host.call, _cdp, 40)
        import json
        return ToolResult.success(
            json.dumps(result, ensure_ascii=False, default=str)[:12_000],
            display=method)
