"""Fase 14 — seam bukti kontrak harus membawa hasil tool yang sebenarnya.

Temuan S-12. `dispatch._observe_session` mengumpulkan bukti dengan membungkus
`session.record_tool`. Satu-satunya pemanggil produksi metode itu adalah
`registry._log_call`, dan ia sengaja menyerahkan ToolResult yang **sudah
diredaksi**:

    session_result = ToolResult(ok=res.ok, content=None, display=None,
                                error=safe_error, meta={})

Jadi validator kontrak selalu menerima `content=None` dan `meta={}`. Kontrak
YouTube yang sudah ada membaca `_result_mapping(event.result)` — yang dengan
masukan itu selalu `{}` — sehingga di produksi ia **tidak pernah bisa lolos**,
berapa pun benarnya pekerjaan agent.

Test yang ada lolos karena memanggil `session.record_tool(...)` langsung dengan
ToolResult utuh, melewati `registry.execute`. Yang terbukti hijau adalah
validatornya, bukan kabel yang menyuplainya.

Redaksi audit sendiri benar dan harus tetap: transkrip sesi dan telemetry tidak
boleh memuat keluaran tool mentah. Karena itu bukti mendapat kanal sendiri.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from jarvis.agent import dispatch, registry
from jarvis.agent.session import Session


def _observed_session() -> tuple[Session, list]:
    session = Session(task="probe", adapter_name="null")
    evidence: list = []
    dispatch._observe_session(session, evidence)
    return session, evidence


def test_evidence_from_production_path_carries_real_tool_output():
    """Bukti dari `registry.execute` wajib memuat isi hasil tool."""
    session, evidence = _observed_session()

    result = asyncio.run(
        registry.execute("capability_status", {}, adapter=None,
                         session=session)
    )
    assert result.ok is True
    assert result.content, "prasyarat: tool ini memang mengembalikan isi"

    assert len(evidence) == 1
    observed = evidence[0]
    assert observed.tool == "capability_status"
    assert observed.ok is True
    assert getattr(observed.result, "content", None) is not None, (
        "validator kontrak menerima hasil kosong — kontrak apa pun mustahil lolos"
    )
    assert observed.result.content == result.content


def test_audit_transcript_stays_redacted():
    """Kanal bukti tidak boleh membocorkan keluaran tool ke audit sesi."""
    session, _ = _observed_session()

    asyncio.run(
        registry.execute("capability_status", {}, adapter=None,
                         session=session)
    )

    assert session.tool_calls, "audit tetap mencatat pemanggilannya"
    for entry in session.tool_calls:
        assert set(entry) <= {"tool", "ok", "error", "elapsed_ms"}, (
            "audit hanya boleh memuat metadata, bukan isi hasil tool")


def test_registry_accepts_telemetry_only_session_without_record_tool(monkeypatch):
    """Custom-provider session minimal tidak boleh memicu log_call_failed."""
    swallowed = []
    monkeypatch.setattr(
        registry.quiet,
        "swallowed",
        lambda event, exc: swallowed.append((event, exc)),
    )

    result = asyncio.run(registry.execute(
        "capability_status",
        {},
        adapter=None,
        session=SimpleNamespace(id="custom-telemetry-only"),
    ))

    assert result.ok is True
    assert not [
        exc for event, exc in swallowed
        if event == "agent.registry.log_call_failed"
        and isinstance(exc, AttributeError)
        and "record_tool" in str(exc)
    ]


def test_youtube_contract_can_pass_through_the_production_seam(monkeypatch):
    """Kontrak yang benar harus bisa LOLOS, bukan hanya bisa menolak.

    Kalau seam-nya mati, satu-satunya hasil yang mungkin adalah gagal — dan
    gerbang yang tidak pernah bisa dilewati tidak memverifikasi apa pun, ia
    hanya memblokir.
    """
    from jarvis.agent.base import Tool, ToolResult
    from jarvis.agent.task_contracts import detect_youtube_latest_play

    task = "putar video terbaru dari Deddy Corbuzier di youtube"
    contract = detect_youtube_latest_play(task)
    assert contract is not None

    class _Fake(Tool):
        name = "browser_navigate"
        description = "fake"
        read_only = True

        async def run(self, **_):
            return ToolResult.success({"url": contract.search_url},
                                      display="terbuka")

    session, evidence = _observed_session()
    # `all_tools()` mengembalikan SALINAN — menambal hasilnya tidak mengubah
    # apa pun dan tool aslinya tetap jalan (versi pertama tes ini benar-benar
    # meluncurkan Chrome). Cache modulnya yang harus ditambal.
    registry.all_tools()
    monkeypatch.setitem(registry._tools, "browser_navigate", _Fake())

    asyncio.run(registry.execute(
        "browser_navigate", {"url": contract.search_url},
        adapter=None, session=session))

    assert evidence, "tidak ada bukti terkumpul dari jalur produksi"
    assert getattr(evidence[0].result, "content", None) == {
        "url": contract.search_url}


@pytest.mark.parametrize("tool_name", ["capability_status"])
def test_evidence_records_arguments_without_private_keys(tool_name):
    session, evidence = _observed_session()
    asyncio.run(registry.execute(tool_name, {}, adapter=None, session=session))
    assert evidence
    assert all(not str(key).startswith("_") for key in evidence[0].args)
