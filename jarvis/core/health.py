"""Health registry (Fase 6) — one snapshot of every subsystem.

Each check is cheap, bounded, and never raises. Complements the boot-time
checks in ``jarvis.core.boot`` (those speak the greeting; this one serves
diagnostics on demand).

CLI: ``python -m jarvis.core.health`` prints the table.
"""
from __future__ import annotations

from dataclasses import dataclass

from jarvis.core import config, log

_logger = log.get("health")


@dataclass
class Health:
    component: str
    ok: bool
    detail: str = ""


def _wrap(component: str, fn) -> Health:
    try:
        return fn()
    except Exception as e:
        return Health(component, False, str(e)[:100])


def check_microphone() -> Health:
    import sounddevice as sd
    dev = sd.query_devices(kind="input")
    return Health("microphone", True, str(dev.get("name", ""))[:60])


def check_speaker() -> Health:
    import sounddevice as sd
    dev = sd.query_devices(kind="output")
    return Health("speaker", True, str(dev.get("name", ""))[:60])


def check_llm() -> Health:
    from jarvis.core import llm
    if not llm.api_key():
        return Health("llm", False, "API key missing")
    return Health("llm", True, "key configured")


def check_google_creds() -> Health:
    from jarvis.core import secrets_store
    if not secrets_store.get("jarvis/google/oauth_token"):
        return Health("calendar_youtube", False,
                      "OAuth Google belum terhubung")
    return Health("calendar_youtube", True, "token tersimpan aman")


def check_browser_agent() -> Health:
    import shutil
    path = shutil.which("agent-browser")
    if path:
        return Health("browser_agent", True, "CLI in PATH")
    return Health("browser_agent", False, "agent-browser CLI not in PATH")


def check_memory_sqlite() -> Health:
    import sqlite3
    db = config.resolve_path("memory.sqlite")
    with sqlite3.connect(db, timeout=3) as conn:
        n = conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
    return Health("memory_sqlite", True, f"{n} tables")


def check_faiss() -> Health:
    try:
        import faiss  # noqa: F401
        return Health("faiss", True, "installed")
    except ImportError:
        return Health("faiss", False, "faiss-cpu not installed (optional)")


def check_relay() -> Health:
    from jarvis.integrations.relay.service import RelayService
    s = RelayService.get().status()
    if not s["enabled"]:
        return Health("relay", False, "disabled (RELAY_ENABLED=0)")
    ok = s["webhook_running"] or s["client_configured"]
    return Health("relay", ok,
                  f"webhook={'up' if s['webhook_running'] else 'down'} "
                  f"events={s['events_stored']} circuit={s['circuit']}")


def check_clap() -> Health:
    try:
        import pyaudio  # noqa: F401
    except ImportError:
        return Health("clap_detector", False, "pyaudio not installed")
    from jarvis.core.wake import ClapConfig
    c = ClapConfig.load()
    if not c.enabled:
        return Health("clap_detector", False, "disabled by config/env")
    return Health("clap_detector", True,
                  f"mult={c.threshold_multiplier} cooldown={c.cooldown_ms}ms")


def check_docs() -> Health:
    missing = []
    for mod in ("fitz", "docx"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        return Health("documents", False, "missing: " + ", ".join(missing))
    return Health("documents", True, "pdf + docx parsers ready")


_CHECKS = {
    "microphone": check_microphone,
    "speaker": check_speaker,
    "llm": check_llm,
    "calendar_youtube": check_google_creds,
    "browser_agent": check_browser_agent,
    "memory_sqlite": check_memory_sqlite,
    "faiss": check_faiss,
    "relay": check_relay,
    "clap_detector": check_clap,
    "documents": check_docs,
}


def check_all() -> list[Health]:
    results = [_wrap(name, fn) for name, fn in _CHECKS.items()]
    _logger.info("health.snapshot",
                 **{r.component: ("ok" if r.ok else "fail") for r in results})
    return results


if __name__ == "__main__":
    for r in check_all():
        mark = "OK " if r.ok else "ERR"
        print(f" [{mark}] {r.component:<18} {r.detail}")
    issues = config.validate()
    if issues:
        print("\nConfig issues:")
        for i in issues:
            print(f" ! {i}")
