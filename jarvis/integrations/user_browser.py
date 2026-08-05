"""Akses ke Chrome milik user, terpisah dari browser agent (Fase 21, S-21).

``jarvis/agent/tools/browser.py`` menggerakkan Chrome milik AGENT, yang sengaja
memakai profil terisolasi. Itu keputusan yang benar untuk pekerjaan agent: tab
user tidak dirusak, dan tidak ada bentrok profile-lock. Tetapi akibatnya Jarvis
buta terhadap browser yang benar-benar dipakai Takeda — "pause youtube" memeriksa
browser agent yang kosong lalu melaporkan tidak ada media, padahal videonya
memutar di Chrome pribadinya.

Modul ini menambah jalur kedua yang eksplisit. Isolasi agent tidak diubah.

**Kendala keras yang membentuk seluruh modul:** Chrome yang sudah berjalan
TIDAK bisa di-attach belakangan. Ia harus dimulai dengan
``--remote-debugging-port``. Karena itu satu-satunya sikap jujur ketika port
tidak ada adalah mengatakannya beserta cara memperbaikinya — bukan melaporkan
"tidak ada video", yang terdengar seperti fakta tentang browser user padahal
Jarvis tidak pernah melihatnya.

Koneksi dibuat per operasi. CDP attach murah (tidak meluncurkan browser), dan
koneksi berumur panjang akan basi begitu user menutup Chrome.
"""
from __future__ import annotations

from jarvis.core import config, log

_logger = log.get("integrations.user_browser")

_MEDIA_ACTIONS = ("status", "play", "pause", "toggle", "mute", "unmute")

# Dijalankan di dalam tab user. Hanya membaca dan mengendalikan elemen media;
# tidak menyentuh DOM lain, tidak membaca isi halaman.
_MEDIA_JS = """
(action) => {
  const vids = Array.from(document.querySelectorAll('video, audio'));
  const el = vids.find(v => v.readyState > 0 && v.duration > 0) || vids[0];
  if (!el) return {found: false};
  if (action === 'play') el.play();
  else if (action === 'pause') el.pause();
  else if (action === 'toggle') { el.paused ? el.play() : el.pause(); }
  else if (action === 'mute') el.muted = true;
  else if (action === 'unmute') el.muted = false;
  return {found: true, paused: el.paused, muted: el.muted,
          currentTime: el.currentTime, duration: el.duration,
          title: document.title};
}
"""


def enabled() -> bool:
    return bool(config.get("user_browser.enabled", True))


def debug_port() -> int:
    try:
        return int(config.get("user_browser.debug_port", 9222))
    except (TypeError, ValueError):
        return 9222


def _unreachable_reason(exc: object) -> str:
    port = debug_port()
    return (
        f"Saya tidak bisa melihat Chrome Anda: tidak ada yang menjawab di "
        f"remote-debugging-port {port}. Chrome yang sudah berjalan tidak bisa "
        f"disambungkan belakangan — ia harus dijalankan dengan "
        f"--remote-debugging-port={port}. Ini BUKAN berarti tidak ada video "
        f"yang sedang diputar; saya memang belum bisa melihatnya."
    )


def _connect(port: int):
    """Sambungkan ke Chrome user lewat CDP. Diganti di tes."""
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{int(port)}", timeout=5_000)
    except Exception:
        playwright.stop()
        raise
    browser._jarvis_playwright = playwright
    return browser


def _release(browser) -> None:
    playwright = getattr(browser, "_jarvis_playwright", None)
    try:
        browser.close()
    except Exception:                                        # noqa: BLE001
        pass
    if playwright is not None:
        try:
            playwright.stop()
        except Exception:                                    # noqa: BLE001
            pass


def _pages(browser) -> list:
    out: list = []
    for context in getattr(browser, "contexts", []) or []:
        out.extend(getattr(context, "pages", []) or [])
    return out


def _tab_info(page, index: int) -> dict:
    try:
        title = page.title()
    except Exception:                                        # noqa: BLE001
        title = ""
    return {"index": index, "title": str(title)[:160],
            "url": str(getattr(page, "url", ""))[:300]}


def status() -> dict:
    """``{attached, reason, port, tabs}`` — tidak pernah melempar."""
    port = debug_port()
    if not enabled():
        return {"attached": False, "port": port, "tabs": 0,
                "reason": "Akses browser user dimatikan di config "
                          "(user_browser.enabled)."}
    browser = None
    try:
        browser = _connect(port)
        pages = _pages(browser)
        return {"attached": True, "port": port, "tabs": len(pages),
                "reason": ""}
    except Exception as exc:                                 # noqa: BLE001
        _logger.info("user_browser.unreachable", error=str(exc)[:120])
        return {"attached": False, "port": port, "tabs": 0,
                "reason": _unreachable_reason(exc)}
    finally:
        if browser is not None:
            _release(browser)


def list_tabs() -> dict:
    port = debug_port()
    if not enabled():
        return {"ok": False, "reason": "Akses browser user dimatikan di config."}
    browser = None
    try:
        browser = _connect(port)
        tabs = [_tab_info(page, index)
                for index, page in enumerate(_pages(browser))]
        return {"ok": True, "tabs": tabs}
    except Exception as exc:                                 # noqa: BLE001
        return {"ok": False, "reason": _unreachable_reason(exc)}
    finally:
        if browser is not None:
            _release(browser)


def media(action: str = "status", index: int | None = None) -> dict:
    """Kendalikan media di tab user. Mencari tab yang benar-benar memutar."""
    action = str(action or "status").strip().casefold()
    if action not in _MEDIA_ACTIONS:
        return {"ok": False,
                "reason": f"aksi media tidak dikenal: {action}"}
    if not enabled():
        return {"ok": False, "reason": "Akses browser user dimatikan di config."}

    browser = None
    try:
        browser = _connect(debug_port())
        pages = _pages(browser)
        if index is not None:
            pages = pages[int(index):int(index) + 1]

        # Cari tab yang punya media; periksa dulu tanpa mengubah apa pun
        # supaya tab lain tidak ikut ter-pause.
        for position, page in enumerate(pages):
            try:
                probe = page.evaluate(_MEDIA_JS, "status") or {}
            except Exception:                                # noqa: BLE001
                continue
            if not probe.get("found"):
                continue
            state = probe if action == "status" else (
                page.evaluate(_MEDIA_JS, action) or {})
            return {"ok": True, "action": action, "state": dict(state),
                    "tab": _tab_info(page, position)}

        return {"ok": False,
                "reason": "Tidak ada tab di Chrome Anda yang sedang memutar "
                          "video atau audio."}
    except Exception as exc:                                 # noqa: BLE001
        return {"ok": False, "reason": _unreachable_reason(exc)}
    finally:
        if browser is not None:
            _release(browser)


def open_url(url: str, *, focus: bool = True) -> dict:
    target = str(url or "").strip()
    if not target.lower().startswith(("http://", "https://")):
        return {"ok": False,
                "reason": "Butuh URL lengkap yang diawali http:// atau https://."}
    if not enabled():
        return {"ok": False, "reason": "Akses browser user dimatikan di config."}

    browser = None
    try:
        browser = _connect(debug_port())
        contexts = getattr(browser, "contexts", []) or []
        if not contexts:
            return {"ok": False, "reason": _unreachable_reason(None)}
        page = contexts[0].new_page()
        page.goto(target, wait_until="domcontentloaded", timeout=30_000)
        if focus:
            try:
                page.bring_to_front()
            except Exception:                                # noqa: BLE001
                pass
        _logger.info("user_browser.opened", url=target[:120])
        return {"ok": True, "url": target}
    except Exception as exc:                                 # noqa: BLE001
        return {"ok": False, "reason": _unreachable_reason(exc)}
    finally:
        if browser is not None:
            _release(browser)


__all__ = ["debug_port", "enabled", "list_tabs", "media", "open_url", "status"]
