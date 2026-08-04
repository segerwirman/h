"""Fase 14 — kontrak bukti untuk panggilan keluar (S-1 lapis 2).

Fase 13 membuat `whatsapp_call` jujur: ia hanya melapor sukses bila keadaan
panggilan terbukti di halaman. Tetapi yang diucapkan ke Takeda bukan hasil tool
— melainkan kalimat penutup model. Selama `dispatch` hanya memvalidasi bukti
untuk kontrak YouTube, model bisa mengarang "sudah saya telepon" tanpa pernah
memanggil toolnya, dan tidak ada yang menahannya.

Aturan prompt (Fase 13.4) adalah lapisan terluar, bukan penegakan. Ini
penegakannya.
"""
from __future__ import annotations

import threading

import pytest

from jarvis.agent.base import ToolResult
from jarvis.agent.task_contracts import (
    ExternalCallContract,
    ToolEvidence,
    detect_external_call,
    prepare_task,
)


def _call_result(state: str = "ringing", *, proven: bool = True,
                 contact: str = "Honbrew") -> ToolResult:
    return ToolResult.success(
        {"state": state, "contact": contact, "proven": proven,
         "audio_bridge": {"active": False}},
        display=f"Panggilan WhatsApp ke {contact} berdering.")


def _evidence(*items) -> list[ToolEvidence]:
    return list(items)


# ── deteksi ───────────────────────────────────────────────────────────────

@pytest.fixture
def allowlist(tmp_path, monkeypatch):
    """Satu kontak diizinkan — cermin `data/whatsapp_contacts.json` nyata."""
    import json

    from jarvis.integrations import whatsapp_web

    path = tmp_path / "contacts.json"
    path.write_text(json.dumps({"contacts": [
        {"name": "Honbrew", "phone": "628123456789", "allowed": True}
    ]}), encoding="utf-8")
    monkeypatch.setattr(whatsapp_web, "_contacts_path", lambda: path)
    return path


@pytest.mark.parametrize("task", [
    "telepon Honbrew lewat whatsapp",
    "jarvis, tolong panggil Honbrew",
    "hubungi Honbrew via WhatsApp sekarang",
    "call Honbrew on whatsapp",
])
def test_call_requests_are_contracted(task, allowlist):
    assert isinstance(detect_external_call(task), ExternalCallContract)


@pytest.mark.parametrize("task", [
    "panggil taksi online lewat aplikasi Grab",
    "panggil tukang servis AC besok pagi",
    "telepon customer service bank",
])
def test_bare_call_to_a_non_contact_is_not_a_whatsapp_call(task, allowlist):
    """"Panggil X" hanya panggilan WhatsApp bila X memang kontak allowlist.

    Tanpa syarat ini, "panggil taksi online lewat aplikasi Grab" mewarisi
    kontrak panggilan: toolnya dipersempit ke WhatsApp saja dan tugas yang
    sepenuhnya wajar dijamin gagal.
    """
    assert detect_external_call(task) is None


def test_explicit_whatsapp_call_is_contracted_even_for_unknown_names(allowlist):
    """Menyebut WhatsApp sudah menyatakan transportnya.

    Kontaknya mungkin salah dengar; itu urusan resolver dan clarify, bukan
    alasan melepaskan kontrak bukti.
    """
    assert isinstance(detect_external_call("telepon Budi lewat whatsapp"),
                      ExternalCallContract)


@pytest.mark.parametrize("task", [
    "kirim pesan whatsapp ke Honbrew: aku telat",
    "balas whatsapp dari Honbrew",
    "akhiri panggilan whatsapp",
    "jawab panggilan whatsapp",
    "putar video terbaru dari Deddy Corbuzier di youtube",
    "cari berita hari ini",
])
def test_non_call_requests_are_not_contracted(task):
    """Mengirim pesan dan menutup panggilan bukan memulai panggilan.

    Memakai pola WhatsApp yang luas akan memaksa kontrak panggilan pada
    permintaan yang tidak pernah memanggil `whatsapp_call`, sehingga setiap
    pengiriman pesan yang berhasil dilaporkan gagal.
    """
    assert detect_external_call(task) is None


def test_prepare_task_routes_each_request_to_its_own_contract():
    call = prepare_task("telepon Honbrew lewat whatsapp")
    assert isinstance(call.contract, ExternalCallContract)

    youtube = prepare_task("putar video terbaru dari Deddy Corbuzier di youtube")
    assert youtube.contracted
    assert not isinstance(youtube.contract, ExternalCallContract)

    plain = prepare_task("apa ibu kota Indonesia")
    assert plain.contracted is False
    assert plain.execution_prompt == "apa ibu kota Indonesia"


# ── validasi bukti ────────────────────────────────────────────────────────

def test_success_requires_a_real_call_tool_result():
    contract = detect_external_call("telepon Honbrew lewat whatsapp")
    assert contract.validate(
        _evidence(ToolEvidence("whatsapp_call", {"contact": "Honbrew"},
                               _call_result(), True))).ok


def test_narration_without_any_call_tool_is_rejected():
    """Kasus yang dilaporkan Takeda: mengaku menelepon, tool tak pernah jalan."""
    contract = detect_external_call("telepon Honbrew lewat whatsapp")
    validation = contract.validate(_evidence(
        ToolEvidence("whatsapp_open", {}, ToolResult.success("siap"), True),
        ToolEvidence("whatsapp_list_contacts", {},
                     ToolResult.success([{"name": "Honbrew"}]), True),
    ))
    assert validation.ok is False
    assert "whatsapp_call" in validation.reason


def test_failed_call_tool_is_not_success():
    contract = detect_external_call("telepon Honbrew lewat whatsapp")
    validation = contract.validate(_evidence(
        ToolEvidence("whatsapp_call", {"contact": "Honbrew"},
                     ToolResult.fail("Panggilan tidak terbukti dimulai"),
                     False)))
    assert validation.ok is False


def test_unproven_state_is_not_success():
    """Bahkan hasil ok harus membawa keadaan panggilan yang terbukti."""
    contract = detect_external_call("telepon Honbrew lewat whatsapp")
    for state, proven in (("calling", False), ("", True), ("ready", True)):
        validation = contract.validate(_evidence(
            ToolEvidence("whatsapp_call", {"contact": "Honbrew"},
                         _call_result(state, proven=proven), True)))
        assert validation.ok is False, f"{state!r}/{proven} tidak boleh lolos"


def test_declined_confirmation_is_reported_as_not_called():
    contract = detect_external_call("telepon Honbrew lewat whatsapp")
    validation = contract.validate(_evidence(
        ToolEvidence("whatsapp_call", {"contact": "Honbrew"},
                     ToolResult.fail("aksi butuh konfirmasi user dan tidak "
                                     "disetujui"), False)))
    assert validation.ok is False


def test_success_text_names_the_contact_and_state():
    contract = detect_external_call("telepon Honbrew lewat whatsapp")
    text = contract.success_text(
        _evidence(ToolEvidence("whatsapp_call", {"contact": "Honbrew"},
                               _call_result("in_call"), True)))
    assert "Honbrew" in text
    assert "tersambung" in text.casefold()


def test_allowed_tools_are_bounded_to_the_call_flow():
    contract = detect_external_call("telepon Honbrew lewat whatsapp")
    tools = set(contract.allowed_tools)
    assert "whatsapp_call" in tools
    assert not ({"terminal", "file_write", "computer_click", "browser_navigate"}
                & tools)


# ── integrasi dispatch ────────────────────────────────────────────────────

def test_dispatch_rejects_a_fabricated_call_report(monkeypatch):
    """Penegakan sesungguhnya: kalimat model tidak pernah terbit tanpa bukti."""
    from jarvis.agent import dispatch
    from jarvis.agent import loop as agent_loop
    from jarvis.agent.loop import RunResult
    from jarvis.agent.session import Session

    monkeypatch.setattr(dispatch, "available", lambda: True)
    monkeypatch.setattr(Session, "finish", lambda *a, **k: None)
    terminal: dict[str, str] = {}
    done = threading.Event()

    async def fake_run(_task, *, adapter, session, **_kwargs):
        await adapter.send("Sudah saya telepon Honbrew, sir.")
        return RunResult(ok=True, text="Sudah saya telepon Honbrew, sir.",
                         session_id=session.id)

    monkeypatch.setattr(agent_loop, "run", fake_run)

    assert dispatch.dispatch_async(
        "telepon Honbrew lewat whatsapp",
        on_done=lambda result: (terminal.__setitem__("done", result),
                                done.set()),
        on_error=lambda error: (terminal.__setitem__("error", error),
                                done.set()),
    )
    assert done.wait(20)
    assert "done" not in terminal, "klaim tanpa bukti tidak boleh terbit"
    error = terminal["error"]
    assert "whatsapp_call" in error
    # Kalimat karangan model tidak boleh bocor lewat jalur gagal.
    assert "sudah saya telepon" not in error.casefold()
    # Dan label kegagalannya milik kontrak panggilan, bukan warisan YouTube.
    assert "youtube" not in error.casefold()


def test_dispatch_reports_success_when_the_call_is_proven(monkeypatch):
    """Gerbang yang tak pernah bisa dilewati tidak memverifikasi apa pun."""
    from jarvis.agent import dispatch
    from jarvis.agent import loop as agent_loop
    from jarvis.agent.loop import RunResult
    from jarvis.agent.session import Session

    monkeypatch.setattr(dispatch, "available", lambda: True)
    monkeypatch.setattr(Session, "finish", lambda *a, **k: None)
    terminal: dict[str, str] = {}
    done = threading.Event()

    async def fake_run(_task, *, adapter, session, **_kwargs):
        session.record_evidence("whatsapp_call", {"contact": "Honbrew"},
                                _call_result("ringing"))
        await adapter.send("Selesai.")
        return RunResult(ok=True, text="Selesai.", session_id=session.id)

    monkeypatch.setattr(agent_loop, "run", fake_run)

    assert dispatch.dispatch_async(
        "telepon Honbrew via whatsapp",
        on_done=lambda result: (terminal.__setitem__("done", result),
                                done.set()),
        on_error=lambda error: (terminal.__setitem__("error", error),
                                done.set()),
    )
    assert done.wait(20)
    assert "error" not in terminal, terminal.get("error")
    assert "Honbrew" in terminal["done"]
