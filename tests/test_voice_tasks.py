"""AUDIT_REPORT §8.4 Fase 3 — tool tugas latar di sesi Gemini Live.

Yang dibuktikan di sini:

* keempat tool terpasang ke sesi Live TANPA menyentuh main.py maupun
  core/prompt.txt (keduanya FROZEN);
* hasil tugas diantre dan hanya dikirim di batas giliran yang aman, sehingga
  tidak pernah memotong Jarvis di tengah kalimat;
* aturan [MULTI-TASKING] masuk ke system prompt tanpa mengubah persona user.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.agent import dispatch, registry
from jarvis.agent.tasks import REGISTRY, TaskStatus
from jarvis.integrations import voice_tasks

ROOT = Path(__file__).resolve().parents[1]
TASK_TOOLS = ("task_start", "task_status", "task_cancel", "task_result")


class _FakeSession:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_client_content(self, turns=None, turn_complete=False):
        parts = (turns or {}).get("parts") or []
        self.sent.append("".join(p.get("text", "") for p in parts))


class _FakeLive:
    """Cukup meniru permukaan JarvisLive yang dibaca flusher."""

    def __init__(self, *, turn_done: bool = True, speaking: bool = False):
        self.session = _FakeSession()
        self._speaking_lock = threading.Lock()
        self._is_speaking = speaking
        self._turn_done_event = threading.Event()
        if turn_done:
            self._turn_done_event.set()


@pytest.fixture(autouse=True)
def _clean():
    voice_tasks.clear_notices()
    REGISTRY.clear()
    with dispatch._active_lock:
        dispatch._active.clear()
    yield
    voice_tasks.clear_notices()
    REGISTRY.clear()
    with dispatch._active_lock:
        dispatch._active.clear()


# ── §8.4c — tool terpasang ───────────────────────────────────────────────

def test_keempat_tool_terdaftar_di_registry() -> None:
    tools = registry.all_tools()
    for name in TASK_TOOLS:
        assert name in tools, f"{name} tidak ditemukan lewat auto-discovery"
    assert tools["task_status"].read_only is True
    assert tools["task_result"].read_only is True


def test_declarations_untuk_live_lengkap_dan_bertipe_gemini() -> None:
    decls = {d["name"]: d for d in voice_tasks.declarations()}
    assert set(decls) == set(TASK_TOOLS)
    params = decls["task_start"]["parameters"]
    assert params["type"] == "OBJECT", "schema belum diubah ke gaya Gemini"
    assert "task" in params["properties"]
    # regresi: parameter bernama "title" akan dimakan _strip_titles (base.py:91)
    assert "label" in params["properties"]
    assert "title" not in params["properties"]


def test_install_menyuntik_declarations_dan_idempoten() -> None:
    legacy = SimpleNamespace(
        TOOL_DECLARATIONS=[{"name": "open_app"}],
        JarvisLive=type("L", (), {
            "_execute_tool": lambda self, fc: None,
            "run": lambda self: None,
        }),
        types=SimpleNamespace(FunctionResponse=dict),
        _load_system_prompt=lambda: "persona asli",
    )
    voice_tasks.install(legacy)
    names = [d["name"] for d in legacy.TOOL_DECLARATIONS]
    assert "open_app" in names, "deklarasi legacy hilang"
    assert set(TASK_TOOLS) <= set(names)

    before = len(legacy.TOOL_DECLARATIONS)
    voice_tasks.install(legacy)
    assert len(legacy.TOOL_DECLARATIONS) == before, "install tidak idempoten"


# ── §8.4d — aturan multi-tasking tanpa menyentuh persona ─────────────────

def test_aturan_multitasking_ditambahkan_tanpa_mengubah_prompt_txt() -> None:
    prompt_path = ROOT / "core" / "prompt.txt"
    before = hashlib.sha256(prompt_path.read_bytes()).hexdigest()

    legacy = SimpleNamespace(
        TOOL_DECLARATIONS=[],
        JarvisLive=type("L", (), {
            "_execute_tool": lambda self, fc: None,
            "run": lambda self: None,
        }),
        types=SimpleNamespace(FunctionResponse=dict),
        _load_system_prompt=lambda: "PERSONA MILIK USER",
    )
    voice_tasks.install(legacy)
    prompt = legacy._load_system_prompt()

    assert prompt.startswith("PERSONA MILIK USER"), "persona ditulis ulang"
    assert "[MULTI-TASKING]" in prompt
    assert "task_start" in prompt
    # dipanggil dua kali tidak menumpuk section
    assert legacy._load_system_prompt().count("[MULTI-TASKING]") == 1

    after = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    assert before == after, "core/prompt.txt (FROZEN) berubah"


def test_zona_frozen_tetap_utuh() -> None:
    """main.py dan core/prompt.txt tidak boleh tersentuh Fase 3."""
    manifest = json.loads(
        (ROOT / "config" / "frozen_manifest.json").read_text(encoding="utf-8"))
    files = manifest["files"]
    for name in ("main.py", "core/prompt.txt"):
        entry = files[name]
        digest = entry["sha256"] if isinstance(entry, dict) else entry
        raw = (ROOT / name).read_bytes()
        mode = entry.get("mode", "text-lf") if isinstance(entry, dict) else "text-lf"
        if mode == "text-lf":
            raw = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        assert hashlib.sha256(raw).hexdigest() == digest, f"{name} berubah"


# ── §8.4b — antrean batas-giliran ────────────────────────────────────────

def _finish_event(status: str = "done", result: str = "lima laptop terbaik"):
    return {"task": {"id": "T-1234", "title": "riset laptop",
                     "status": status, "result": result, "error": ""}}


def test_notice_diantre_bukan_langsung_dikirim() -> None:
    voice_tasks._on_task_finished(_finish_event())
    assert voice_tasks.pending_notices() == 1


def test_notice_tidak_dikirim_saat_jarvis_bicara() -> None:
    voice_tasks._on_task_finished(_finish_event())
    live = _FakeLive(turn_done=True, speaking=True)
    sent = asyncio.run(voice_tasks.flush_notices(live))
    assert sent == 0, "notice memotong Jarvis yang sedang bicara"
    assert voice_tasks.pending_notices() == 1


def test_notice_tidak_dikirim_sebelum_giliran_selesai() -> None:
    voice_tasks._on_task_finished(_finish_event())
    live = _FakeLive(turn_done=False, speaking=False)
    assert asyncio.run(voice_tasks.flush_notices(live)) == 0
    assert voice_tasks.pending_notices() == 1


def test_notice_dikirim_di_batas_giliran_aman() -> None:
    voice_tasks._on_task_finished(_finish_event())
    live = _FakeLive(turn_done=True, speaking=False)
    assert asyncio.run(voice_tasks.flush_notices(live)) == 1
    assert voice_tasks.pending_notices() == 0
    body = live.session.sent[0]
    assert "[TASK_DONE id=T-1234]" in body
    assert "lima laptop terbaik" in body
    assert "SATU kalimat" in body


def test_notice_gagal_ikut_dilaporkan() -> None:
    voice_tasks._on_task_finished(
        {"task": {"id": "T-9", "title": "riset", "status": "failed",
                  "result": "", "error": "provider mati"}})
    live = _FakeLive()
    assert asyncio.run(voice_tasks.flush_notices(live)) == 1
    assert "GAGAL" in live.session.sent[0]


def test_notice_cancelled_tidak_diumumkan() -> None:
    """User yang membatalkan sudah tahu — tidak perlu diberi tahu lagi."""
    voice_tasks._on_task_finished(
        {"task": {"id": "T-8", "title": "x", "status": "cancelled",
                  "result": "", "error": ""}})
    assert voice_tasks.pending_notices() == 0


def test_speak_on_complete_false_mematikan_notice(monkeypatch) -> None:
    from jarvis.core import config
    real_get = config.get
    monkeypatch.setattr(
        config, "get",
        lambda key, default=None: (False
                                   if key == "ui.task_deck.speak_on_complete"
                                   else real_get(key, default)))
    voice_tasks._on_task_finished(_finish_event())
    assert voice_tasks.pending_notices() == 0


# ── tool berperilaku benar ───────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def test_task_start_kembali_seketika_dengan_id(monkeypatch) -> None:
    from jarvis.agent import loop as agent_loop
    monkeypatch.setattr(dispatch, "available", lambda: True)
    release = threading.Event()

    async def fake_run(task, adapter=None, session=None, bg_task=None, **kw):
        while not release.is_set():
            await asyncio.sleep(0.01)
        return agent_loop.RunResult(ok=True, text="hasil riset",
                                    session_id=getattr(session, "id", ""))

    monkeypatch.setattr(agent_loop, "run", fake_run)
    tools = registry.all_tools()

    res = _run(tools["task_start"].run(task="riset lima laptop"))
    assert res.ok
    tid = res.content["id"]

    status = _run(tools["task_status"].run())
    assert tid in status.content

    release.set()
    deadline = threading.Event()
    deadline.wait(0.05)
    for _ in range(200):
        if REGISTRY.get(tid) and not REGISTRY.get(tid).active:
            break
        deadline.wait(0.02)
    assert REGISTRY.get(tid).status is TaskStatus.DONE
    assert "hasil riset" in _run(tools["task_result"].run(id=tid)).content


def test_task_start_menolak_saat_agent_tidak_tersedia(monkeypatch) -> None:
    monkeypatch.setattr(dispatch, "available", lambda: False)
    res = _run(registry.all_tools()["task_start"].run(task="apa saja"))
    assert res.ok is False
    assert res.error


def test_task_status_kosong_jujur() -> None:
    res = _run(registry.all_tools()["task_status"].run())
    assert res.ok
    assert "Tidak ada tugas latar" in res.content


def test_task_cancel_dan_result_pada_id_asing() -> None:
    tools = registry.all_tools()
    assert _run(tools["task_cancel"].run(id="T-xxxx")).ok is False
    assert _run(tools["task_result"].run(id="T-xxxx")).ok is False
    assert _run(tools["task_cancel"].run()).ok is False


def test_task_cancel_membatalkan_task_registry() -> None:
    task = REGISTRY.submit("tugas manual")
    REGISTRY.mark_running(task.id)
    res = _run(registry.all_tools()["task_cancel"].run(id=task.id))
    assert res.ok
    assert task.cancel.is_set()


def test_subagent_tidak_boleh_memulai_tugas_latar() -> None:
    """Rekursi task_start harus ditutup seperti delegate_task."""
    import inspect

    from jarvis.agent import loop as agent_loop
    source = inspect.getsource(agent_loop.run)
    assert '"task_start"' in source
    assert "is_subagent" in source
