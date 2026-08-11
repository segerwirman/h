"""PROMPT N — notice generik dibatch hanya pada batas giliran."""
from __future__ import annotations

import asyncio
import types

from jarvis.core.action_registry import Action


def _bridge(monkeypatch, tmp_path):
    from jarvis.integrations import voice_notices

    voice_notices._reset_for_tests()
    monkeypatch.setattr(voice_notices, "_enabled", lambda: True)
    monkeypatch.setattr(voice_notices.memory_store, "write", lambda *a, **kw: "mem-1")
    return voice_notices


class _Session:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.sent = []

    async def send_client_content(self, **kwargs):
        if self.fail:
            raise RuntimeError("offline")
        self.sent.append(kwargs)


class _Live:
    def __init__(self, *, speaking=False, session=None):
        self._is_speaking = speaking
        self.session = session or _Session()


def test_missing_speaking_attribute_fails_safe_as_speaking(monkeypatch, tmp_path):
    bridge = _bridge(monkeypatch, tmp_path)
    bridge.enqueue("[AKSI] 12:04 buka aplikasi Spotify (berhasil)")
    live = types.SimpleNamespace(session=_Session())

    assert asyncio.run(bridge.flush_at_turn_boundary(live)) is False
    assert live.session.sent == []
    assert bridge.pending_count() == 1


def test_legacy_live_initializes_speaking_contract():
    import ast
    from pathlib import Path

    source = Path("main.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    live = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                and node.name == "JarvisLive")
    init = next(node for node in live.body if isinstance(node, ast.FunctionDef)
                and node.name == "__init__")
    assert any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Attribute) and target.attr == "_is_speaking"
                for target in node.targets)
        for node in ast.walk(init)
    )


def test_l1_action_is_written_and_queued_once(monkeypatch, tmp_path):
    bridge = _bridge(monkeypatch, tmp_path)
    writes = []
    monkeypatch.setattr(bridge.memory_store, "write", lambda *a, **kw: writes.append((a, kw)) or "mem-1")

    bridge.remember_action(Action("app", "spotify", "open", {"app": "Spotify"}))

    assert len(writes) == 1
    assert writes[0][0][0] == "episodic"
    assert bridge.pending_count() == 1
    assert "buka aplikasi Spotify" in bridge.pending_snapshot()[0]


def test_volume_and_screenshot_do_not_write_or_queue(monkeypatch, tmp_path):
    bridge = _bridge(monkeypatch, tmp_path)
    writes = []
    monkeypatch.setattr(bridge.memory_store, "write", lambda *a, **kw: writes.append(a))

    bridge.remember_action(Action("system", "volume_up", "set", {"action": "volume_up"}))
    bridge.remember_action(Action("system", "screenshot", "set", {"action": "screenshot"}))

    assert writes == []
    assert bridge.pending_count() == 0


def test_flush_batches_notice_without_prompting_model_response(monkeypatch, tmp_path):
    bridge = _bridge(monkeypatch, tmp_path)
    bridge.enqueue("[AKSI] 12:04 buka aplikasi Spotify (berhasil)")
    session = _Session()

    assert asyncio.run(bridge.flush_at_turn_boundary(_Live(session=session))) is True
    assert len(session.sent) == 1
    payload = session.sent[0]
    assert payload["turn_complete"] is False
    assert "[AKSI]" in payload["turns"]["parts"][0]["text"]
    assert bridge.pending_count() == 0


def test_notice_while_speaking_waits_and_does_not_interrupt(monkeypatch, tmp_path):
    bridge = _bridge(monkeypatch, tmp_path)
    bridge.enqueue("[AKSI] 12:04 buka aplikasi Spotify (berhasil)")
    session = _Session()
    live = _Live(speaking=True, session=session)

    assert asyncio.run(bridge.flush_at_turn_boundary(live)) is False
    assert session.sent == []
    assert bridge.pending_count() == 1
    live._is_speaking = False
    assert asyncio.run(bridge.flush_at_turn_boundary(live)) is True
    assert len(session.sent) == 1


def test_send_failure_requeues_batch(monkeypatch, tmp_path):
    bridge = _bridge(monkeypatch, tmp_path)
    bridge.enqueue("[AKSI] 12:04 buka aplikasi Spotify (berhasil)")

    assert asyncio.run(bridge.flush_at_turn_boundary(_Live(session=_Session(fail=True)))) is False
    assert bridge.pending_count() == 1


def test_active_context_is_bounded_to_twenty(monkeypatch, tmp_path):
    bridge = _bridge(monkeypatch, tmp_path)
    for i in range(25):
        bridge.enqueue(f"[AKSI] {i}")

    assert bridge.pending_count() == 20
    assert bridge.pending_snapshot()[0] == "[AKSI] 5"


def test_flag_off_makes_l1_write_and_notice_true_noops(monkeypatch):
    from jarvis.integrations import voice_notices

    voice_notices._reset_for_tests()
    monkeypatch.setattr(voice_notices, "_enabled", lambda: False)
    writes = []
    monkeypatch.setattr(voice_notices.memory_store, "write", lambda *a, **kw: writes.append(a))

    voice_notices.remember_action(Action("app", "spotify", "open", {"app": "Spotify"}))

    assert writes == []
    assert voice_notices.pending_count() == 0


def test_agent_result_uses_same_queue(monkeypatch, tmp_path):
    bridge = _bridge(monkeypatch, tmp_path)

    bridge.remember_agent_result("cek build", "Build hijau", ok=True)

    assert bridge.pending_count() == 1
    assert bridge.pending_snapshot()[0].startswith("[TUGAS]")


def test_notice_delivery_no_longer_requires_legacy_assignment():
    from jarvis.integrations import voice_notices

    assert not hasattr(voice_notices, "install")
