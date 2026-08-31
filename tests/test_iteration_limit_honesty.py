"""Fase 17 — batas iterasi: jujur, bisa diatur, bisa dilanjut (S-5).

Pesan lama:

    "Batas iterasi tercapai sebelum tugas tuntas. Progres tersimpan di sesi."

Kalimat kedua adalah klaim palsu yang ditulis oleh kode kita sendiri, bukan
oleh model. Sesi memang tersimpan, tetapi **tidak ada jalur mana pun yang bisa
melanjutkannya** — satu-satunya `resume` di `jarvis/agent/` adalah
`approval_continuations.resume()` untuk persetujuan policy. Menjanjikan
kelanjutan yang tidak ada persis penyakit S-1, kali ini di sisi kita.

Selain itu batasnya jauh lebih ketat dari yang ditampilkan Settings: jalur
suara dan UI memakai `agent.interactive_max_iterations` (12), sementara panel
menampilkan `agent.max_iterations` (20) yang tidak dipakai jalur itu.
"""
from __future__ import annotations

import asyncio

import pytest

from jarvis.agent import loop as agent_loop
from jarvis.agent import registry as _registry
from jarvis.agent.base import ToolResult
from jarvis.agent.session import Session

# Ditangkap sebelum fixture autouse menambalnya: dua test terakhir menguji
# guardrail konfirmasi yang SEBENARNYA, bukan tiruan.
_REAL_EXECUTE = _registry.execute


class _Adapter:
    name = "test"
    interactive = False

    def __init__(self):
        self.sent: list[str] = []
        self.progress_lines: list[str] = []
        self.asked: list[str] = []
        self.answer: str | None = None

    async def send(self, content, **_):
        self.sent.append(str(content))

    async def progress(self, text):
        self.progress_lines.append(str(text))

    async def ask(self, question, options=None):
        self.asked.append(str(question))
        return self.answer

    async def send_image(self, path, caption=""):
        pass


class _Call:
    def __init__(self, name, arguments, cid="c1"):
        self.id = cid
        self.name = name
        self.arguments = arguments


class _Resp:
    ok = True
    error = None

    def __init__(self, content="", tool_calls=()):
        self.content = content
        self.tool_calls = list(tool_calls)


def _never_finishing_client(monkeypatch, tool="web_search"):
    """Model yang selalu meminta tool lagi — pasti menabrak batas."""
    class _Client:
        def available(self):
            return True

        def chat(self, _messages, _tools):
            return _Resp("", [_Call(tool, {"query": "x"})])

        def embed(self, texts):
            """Simulate embed unavailable - returns None like production code expects."""
            return None

    monkeypatch.setattr(agent_loop.model_routing, "light_client",
                        lambda: _Client())
    return _Client()


@pytest.fixture(autouse=True)
def _tool_always_succeeds(monkeypatch):
    async def _execute(name, args, adapter=None, session=None, context=None,
                       **_):
        if session is not None:
            session.record_tool(name, args, ToolResult.success("ok"), 0.01)
        return ToolResult.success(f"hasil {name}")

    monkeypatch.setattr(agent_loop.registry, "execute", _execute)
    monkeypatch.setattr(agent_loop.registry, "schemas", lambda **_k: [])
    monkeypatch.setattr(agent_loop.registry, "all_tools", lambda: {})
    monkeypatch.setattr(agent_loop, "reflect_async", lambda _s: None)
    monkeypatch.setattr(Session, "finish", lambda *a, **k: None)
    monkeypatch.setattr(Session, "record_turn",
                        lambda self, role, content:
                        self.transcript.append({"role": role,
                                                "content": content}))


def _run(adapter, *, max_iterations=3, task="riset sesuatu"):
    session = Session(task=task, adapter_name="test")
    return asyncio.run(agent_loop.run(
        task, adapter=adapter, session=session,
        max_iterations=max_iterations, model_profile="light")), session


# ── klaim palsu ───────────────────────────────────────────────────────────

def test_limit_message_no_longer_promises_a_resume_that_does_not_exist(
        monkeypatch):
    _never_finishing_client(monkeypatch)
    adapter = _Adapter()

    result, _ = _run(adapter)

    assert result.ok is False
    text = " ".join(adapter.sent)
    assert "Progres tersimpan di sesi" not in text
    assert "tersimpan di sesi" not in text.casefold()


def test_limit_message_reports_what_actually_happened(monkeypatch):
    """Ganti janji kosong dengan fakta: berapa iterasi, tool apa yang jalan."""
    _never_finishing_client(monkeypatch)
    adapter = _Adapter()

    result, _ = _run(adapter, max_iterations=3)

    text = " ".join(adapter.sent)
    assert "3" in text                       # jumlah iterasi terpakai
    assert "web_search" in text              # pekerjaan yang benar-benar jalan
    assert result.iterations == 3


def test_partial_result_is_returned_not_only_a_failure(monkeypatch):
    """Loop sudah memegang jejak tool; buang itu berarti membuang pekerjaan."""
    _never_finishing_client(monkeypatch)
    adapter = _Adapter()

    result, _ = _run(adapter, max_iterations=3)

    assert result.text
    assert "web_search" in result.text


# ── bisa diatur, dan angkanya jujur ───────────────────────────────────────

def test_interactive_limit_matches_the_number_shown_in_settings():
    """Panel menampilkan satu angka; jalur suara/UI memakai yang lain.

    Satu nilai yang bohong lebih buruk daripada dua nilai yang jujur.
    """
    from jarvis.core import config, settings_service

    interactive = int(config.get("agent.interactive_max_iterations", 12))
    assert interactive == int(config.get("agent.max_iterations", 20))

    keys = {
        field["key"]
        for section in settings_service.sections()
        for field in section.get("fields", [])
    }
    assert "agent.interactive_max_iterations" in keys


# ── eskalasi sebelum menabrak dinding ─────────────────────────────────────

def test_user_is_warned_before_the_limit_is_hit(monkeypatch):
    _never_finishing_client(monkeypatch)
    adapter = _Adapter()

    _run(adapter, max_iterations=5)

    warnings = [line for line in adapter.progress_lines
                if "batas" in line.casefold()]
    assert warnings, adapter.progress_lines


def test_interactive_run_offers_to_stop_before_the_wall(monkeypatch):
    """Eskalasi menyala: run interaktif ditawari berhenti sebelum menabrak dinding.

    Gerbang eskalasi dinyalakan secara eksplisit. Nilanya di `config.yaml`
    saat ini `false` (P8E, "no speech unless commanded"), jadi tanpa timpalan
    ini tes bergantung pada isi berkas konfigurasi dan merah misterius bila
    nilainya berubah — persis yang terjadi sejak 2026-08-22. Keadaan mati
    diuji tersendiri di bawah.
    """
    _never_finishing_client(monkeypatch)
    _with_escalation(monkeypatch, enabled=True)
    adapter = _Adapter()
    adapter.interactive = True
    adapter.answer = "Hentikan"

    result, _ = _run(adapter, max_iterations=5)

    assert adapter.asked, "run interaktif harus menawarkan keputusan"
    assert result.iterations < 5, "berhenti lebih awal atas permintaan user"
    assert "web_search" in result.text


def test_no_answer_keeps_working_instead_of_blocking(monkeypatch):
    """Tidak menjawab bukan 'hentikan' — pekerjaan lanjut sampai batas."""
    _never_finishing_client(monkeypatch)
    _with_escalation(monkeypatch, enabled=True)
    adapter = _Adapter()
    adapter.interactive = True
    adapter.answer = None

    result, _ = _run(adapter, max_iterations=5)

    assert adapter.asked
    assert result.iterations == 5


def test_non_interactive_run_is_never_asked(monkeypatch):
    _never_finishing_client(monkeypatch)
    adapter = _Adapter()          # interactive = False

    _run(adapter, max_iterations=5)

    assert adapter.asked == []


# ── gerbang konfigurasi eskalasi ─────────────────────────────────────────
#
# P8E (commit c57c923, 2026-08-22) mematikan ``agent.iteration_escalation.enabled``
# atas permintaan pengguna — "no speech unless commanded". Fase 17 lahir
# sebelumnya (73adaa0, 2026-08-05) dengan gerbang ini menyala, dan dua tes di
# atas menuntut ``adapter.ask`` dipanggil. Saat P8E membalik nilai defaultnya,
# kedua tes itu menjadi merah dan tidak ada satu pun tes yang mengawasi
# gerbangnya sendiri — jadi perubahan itu lewat tanpa peringatan.
#
# Dua tes di bawah menutup kekosongan itu dari kedua sisi: bila gerbang dihapus
# atau dibalik, salah satunya pasti merah.


def _with_escalation(monkeypatch, enabled: bool):
    """Timpa hanya kunci eskalasi; kunci lain tetap dibaca dari config asli."""
    from jarvis.core import config

    original = config.get
    monkeypatch.setattr(
        config, "get",
        lambda key, default=None: (
            enabled if key == "agent.iteration_escalation.enabled"
            else original(key, default)
        ),
    )


def test_escalation_off_keeps_progress_but_never_asks(monkeypatch):
    """Gerbang mati = peringatan tetap dikirim, prompt tidak pernah muncul.

    Inilah keadaan yang dikonfigurasi P8E. Prompt interaktif akan memotong
    dengan suara, dan itu yang diminta untuk dihilangkan.
    """
    _never_finishing_client(monkeypatch)
    _with_escalation(monkeypatch, enabled=False)
    adapter = _Adapter()
    adapter.interactive = True
    adapter.answer = None

    result, _ = _run(adapter, max_iterations=5)

    # Peringatan progres masih wajib: keheningan total bukan tujuan gerbang ini.
    assert [l for l in adapter.progress_lines if "batas" in l.casefold()]
    assert adapter.asked == []
    assert result.iterations == 5      # pekerjaan jalan terus sampai batas


def test_escalation_on_asks_and_can_stop_early(monkeypatch):
    """Gerbang hidup = run interaktif ditawari berhenti sebelum menabrak dinding."""
    _never_finishing_client(monkeypatch)
    _with_escalation(monkeypatch, enabled=True)
    adapter = _Adapter()
    adapter.interactive = True
    adapter.answer = "Hentikan"

    result, _ = _run(adapter, max_iterations=5)

    assert adapter.asked
    assert result.iterations < 5, "berhenti lebih awal atas permintaan user"


# ── konfirmasi ditolak tidak boleh diulang ────────────────────────────────

def test_declined_confirmation_is_not_asked_again_in_the_same_session(
        monkeypatch):
    """Pesan gagal sudah berbunyi 'jangan ulangi tanpa diminta'. Tegakkan di
    kode — jangan menitipkan jaminan pada kepatuhan model.

    Tiap pengulangan memakan satu iterasi, dan itulah cara 12 iterasi habis
    tanpa satu pun pekerjaan nyata.
    """
    from jarvis.agent import registry

    monkeypatch.setattr(registry, "execute", _REAL_EXECUTE)
    asks: list[str] = []

    class _Tool:
        name = "whatsapp_call"
        requires_confirmation = True
        read_only = False
        timeout_s = 5
        wants_context = False
        params_schema = None

        def needs_confirmation(self, **_):
            return True

        def confirmation_text(self, **_):
            return "Telepon Honbrew?"

        async def run(self, **_):
            return ToolResult.success("tersambung")

    class _Adapter2(_Adapter):
        async def ask(self, question, options=None):
            asks.append(question)
            return "Batal"

    monkeypatch.setattr(registry, "all_tools", lambda: {"whatsapp_call": _Tool()})

    class _Descriptor:
        id = "whatsapp.call"
        toolset = "whatsapp"
        risk = "high"
        # Mirrors CapabilityDescriptor's field. Without it, registry.py's
        # _direct_confirmation_granted() raises AttributeError while deciding
        # whether this high-risk tool may run unconfirmed — so the fixture
        # would exercise an exception path instead of the confirmation gate.
        # False is also the correct value: "whatsapp.call" is not in the
        # _DIRECT_GRANT_IDS allowlist, so it must still ask.
        direct_grant = False

    from jarvis.agent import capabilities
    monkeypatch.setattr(capabilities.REGISTRY, "descriptor_for_tool",
                        lambda _n: _Descriptor())

    session = Session(task="telepon", adapter_name="test")
    adapter = _Adapter2()

    first = asyncio.run(registry.execute(
        "whatsapp_call", {"contact": "Honbrew"}, adapter, session))
    second = asyncio.run(registry.execute(
        "whatsapp_call", {"contact": "Honbrew"}, adapter, session))

    assert first.ok is False and second.ok is False
    assert len(asks) == 1, "pertanyaan yang sama tidak boleh diajukan dua kali"
    assert "ditolak" in str(second.error).casefold()


def test_a_different_argument_is_still_asked(monkeypatch):
    """Penolakan mengikat satu permintaan, bukan seluruh tool selamanya."""
    from jarvis.agent import registry

    monkeypatch.setattr(registry, "execute", _REAL_EXECUTE)
    asks: list[str] = []

    class _Tool:
        name = "whatsapp_call"
        requires_confirmation = True
        read_only = False
        timeout_s = 5
        wants_context = False
        params_schema = None

        def needs_confirmation(self, **_):
            return True

        def confirmation_text(self, **kwargs):
            return f"Telepon {kwargs.get('contact')}?"

        async def run(self, **_):
            return ToolResult.success("tersambung")

    class _Adapter2(_Adapter):
        async def ask(self, question, options=None):
            asks.append(question)
            return "Batal"

    monkeypatch.setattr(registry, "all_tools", lambda: {"whatsapp_call": _Tool()})

    class _Descriptor:
        id = "whatsapp.call"
        toolset = "whatsapp"
        risk = "high"
        # See the other _Descriptor in this file: registry.py reads
        # direct_grant before consulting the confirmation gate, and this id is
        # not allowlisted, so it stays False — the tool must still ask.
        direct_grant = False

    from jarvis.agent import capabilities
    monkeypatch.setattr(capabilities.REGISTRY, "descriptor_for_tool",
                        lambda _n: _Descriptor())

    session = Session(task="telepon", adapter_name="test")
    adapter = _Adapter2()

    asyncio.run(registry.execute(
        "whatsapp_call", {"contact": "Honbrew"}, adapter, session))
    asyncio.run(registry.execute(
        "whatsapp_call", {"contact": "Ibu"}, adapter, session))

    assert len(asks) == 2
