"""Fase 31 — pakai jawaban deterministik yang sudah ada (S-31).

Ditemukan lewat pengukuran Fase 27, bukan lewat dugaan.
`jarvis/agent/router.py` menyimpulkan `pause youtube` sebagai **T1, single
browser media action**, dalam 0,01 ms. Tetapi jalur perintah UI memakai
`IntentRouter` yang menyimpulkan **CHAT** lalu menyerahkannya ke pipeline
model. Jarvis sudah tahu jawabannya, lalu membuangnya.

Ini "instan tapi tetap pintar" tanpa spekulasi sama sekali — tidak ada yang
perlu ditebak, hanya jawaban yang sudah ada dan tidak dipakai.

**Batas keras fase ini.** Ini jalur SETIAP ucapan. Jembatannya hanya boleh
bekerja di celah yang tepat — ketika perintahnya sudah akan jatuh ke `_chat`
— dan pola yang dipakainya harus regex yang SAMA yang sudah menggerakkan
keputusan tier, bukan salinan kedua yang bisa menyimpang diam-diam.
"""
from __future__ import annotations

import pytest

from jarvis.agent import router


# ── jawaban deterministik yang selama ini dibuang ─────────────────────────

@pytest.mark.parametrize("text,action", [
    ("pause youtube", "pause"),
    ("jeda videonya", "pause"),
    ("tolong pause video", "pause"),
    ("lanjutkan video", "play"),
    ("resume youtube", "play"),
    ("mute youtube", "mute"),
    ("unmute video", "unmute"),
])
def test_a_media_command_resolves_to_the_user_browser_tool(text, action):
    resolved = router.deterministic_tool(text)

    assert resolved is not None, text
    name, args = resolved
    assert name == "user_browser_media"
    assert args["action"] == action


def test_the_bridge_uses_the_same_pattern_that_drives_the_tier():
    """Salinan kedua sebuah regex akan menyimpang diam-diam.

    Bila polanya berbeda, tier bisa bilang T1 sementara jembatannya bilang
    tidak tahu — dan tidak ada yang akan menyadarinya.
    """
    import inspect

    source = inspect.getsource(router.deterministic_tool)
    assert "_BROWSER_MEDIA_RE" in source


@pytest.mark.parametrize("text", [
    "bagaimana cuaca besok",
    "buatkan ringkasan rapat tadi",
    "telepon honbrew lewat whatsapp",
    "kirim pesan ke honbrew",
    "",
])
def test_anything_without_a_deterministic_answer_stays_unresolved(text):
    assert router.deterministic_tool(text) is None


def test_the_bridge_agrees_with_the_tier_router():
    """Kalau tier bilang T1 media, jembatannya tidak boleh bilang tidak tahu."""
    for text in ("pause youtube", "jeda videonya", "mute youtube"):
        assert router.classify(text).tier == router.Tier.SINGLE, text
        assert router.deterministic_tool(text) is not None, text


def test_a_recognised_command_without_a_matching_tool_action_stays_unresolved():
    """`skip iklannya` diakui tier sebagai aksi media, tetapi
    `user_browser_media` hanya punya pause/play/toggle/mute/unmute.

    Mengarangkan aksi "skip" berarti menjalankan sesuatu yang tidak ada.
    Menyerahkannya ke model adalah jawaban yang benar, dan itu disengaja.
    """
    assert router.classify("skip iklannya").tier == router.Tier.SINGLE
    assert router.deterministic_tool("skip iklannya") is None


def test_resolution_never_raises_on_junk():
    for value in (None, 12, object(), b"bytes"):
        assert router.deterministic_tool(value) is None


# ── terpasang tepat di celahnya, bukan di depan segalanya ─────────────────

def test_the_bridge_sits_on_the_chat_fallback_only():
    """Jalur yang sudah bekerja hari ini tidak boleh disentuh.

    Jembatan yang duduk di depan segalanya akan mendahului aturan yang sudah
    benar — untuk SETIAP ucapan.
    """
    import inspect

    from jarvis.ui import window

    source = inspect.getsource(window.MainWindow._dispatch_command)
    assert "deterministic_tool" in source
    assert "self._chat(" in source, "fallback ke model tidak boleh hilang"
    assert source.index("deterministic_tool") < source.index("self._chat("), (
        "jembatan harus mendahului _chat, bukan menggantikannya")


def test_a_media_command_runs_the_tool_instead_of_the_model(monkeypatch):
    from jarvis.ui import window

    ran: list = []
    ui = window.MainWindow.__new__(window.MainWindow)
    monkeypatch.setattr(window.MainWindow, "_run_deterministic_tool",
                        lambda self, name, args: ran.append((name, args)))
    monkeypatch.setattr(window.MainWindow, "_chat",
                        lambda self, text: ran.append(("CHAT", text)))

    from jarvis.core.router import Classified, Intent
    ui._dispatch_command(Classified(Intent.CHAT, 0.5), "pause youtube")

    assert ran == [("user_browser_media", {"action": "pause"})]


def test_a_plain_question_still_reaches_the_model(monkeypatch):
    from jarvis.ui import window

    ran: list = []
    ui = window.MainWindow.__new__(window.MainWindow)
    monkeypatch.setattr(window.MainWindow, "_run_deterministic_tool",
                        lambda self, name, args: ran.append((name, args)))
    monkeypatch.setattr(window.MainWindow, "_chat",
                        lambda self, text: ran.append(("CHAT", text)))

    from jarvis.core.router import Classified, Intent
    ui._dispatch_command(Classified(Intent.CHAT, 0.5), "bagaimana cuaca besok")

    assert ran == [("CHAT", "bagaimana cuaca besok")]


def test_a_missing_tool_falls_back_to_the_model(monkeypatch):
    """Tool bisa hilang antar versi; jembatan tidak boleh jadi jalan buntu."""
    from jarvis.agent import registry
    from jarvis.ui import window

    ran: list = []
    ui = window.MainWindow.__new__(window.MainWindow)
    monkeypatch.setattr(registry, "get", lambda _name: None)
    monkeypatch.setattr(window.MainWindow, "_chat",
                        lambda self, text: ran.append(("CHAT", text)))

    from jarvis.core.router import Classified, Intent
    ui._dispatch_command(Classified(Intent.CHAT, 0.5), "pause youtube")

    assert ran == [("CHAT", "pause youtube")]


def test_an_unreachable_browser_is_reported_not_hidden(monkeypatch):
    """Fase 23 sudah memisahkan "tidak terjangkau" dari "tidak ada video".

    Jembatan ini tidak boleh mengubur perbedaan itu lagi.
    """
    import asyncio

    from jarvis.agent import registry
    from jarvis.agent.base import ToolResult
    from jarvis.ui import window

    said: list = []
    ui = window.MainWindow.__new__(window.MainWindow)

    async def failing(*_args, **_kwargs):
        return ToolResult.fail("Chrome milik user tidak terjangkau di port 9222")

    monkeypatch.setattr(registry, "get", lambda _name: object())
    monkeypatch.setattr(registry, "execute", failing)
    monkeypatch.setattr(window.MainWindow, "write_log",
                        lambda self, text: said.append(text))
    monkeypatch.setattr(window.MainWindow, "_speak_line",
                        lambda self, text, **kwargs: said.append(text))
    monkeypatch.setattr(window.MainWindow, "orb",
                        property(lambda self: _NullOrb()), raising=False)
    monkeypatch.setattr(window.MainWindow, "_restore_orb",
                        lambda self: None)

    ui._run_deterministic_tool("user_browser_media", {"action": "pause"})
    for _ in range(50):
        if said:
            break
        asyncio.run(asyncio.sleep(0.05))

    assert any("9222" in str(line) for line in said), said


class _NullOrb:
    def set_state(self, *_args, **_kwargs):
        pass
