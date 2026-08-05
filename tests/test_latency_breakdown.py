"""Fase 24 — ukur latensi per tahap sebelum mengoptimalkan apa pun.

Siklus ini sudah dua kali membuktikan tebakan arsitektur bisa meleset total:
S-13 dikira pustaka native, ternyata thread `SetupQueue` yang bocor; S-22
dikira ambang atau mikrofon, ternyata echo guard buatan sendiri. Keduanya
terselesaikan hanya setelah ada angka.

Karena itu Fase 24 mendahului 25-29: tanpa rincian per tahap, optimasi
berikutnya menyasar bagian yang belum tentu lambat.

Yang diukur adalah SATU giliran kerja, dari ACK sampai jawaban akhir, dengan
penanda di titik yang bisa ditindaklanjuti: penyiapan kontrak, panggilan LLM
pertama, tool pertama, dan selesai.
"""
from __future__ import annotations

import pytest

from jarvis.core import latency


@pytest.fixture(autouse=True)
def _clean():
    latency.reset()
    yield
    latency.reset()


def test_marks_are_recorded_in_order():
    latency.start("t1", task="telepon Honbrew")
    latency.mark("t1", "prepared")
    latency.mark("t1", "first_llm")
    latency.mark("t1", "first_tool")

    report = latency.finish("t1")

    assert [stage for stage, _ in report["stages"]] == [
        "prepared", "first_llm", "first_tool"]
    assert report["total_ms"] >= 0


def test_each_stage_reports_its_own_share():
    """Yang berguna adalah DELTA per tahap, bukan hanya total.

    Total 7 detik tidak memberi tahu apa pun; "LLM pertama 3,4 detik"
    memberi tahu ke mana harus melihat.
    """
    clock = iter([0.0, 0.10, 0.60, 2.10, 2.60])
    latency.start("t2", now=next(clock))
    latency.mark("t2", "prepared", now=next(clock))
    latency.mark("t2", "first_llm", now=next(clock))
    latency.mark("t2", "first_tool", now=next(clock))

    report = latency.finish("t2", now=next(clock))

    stages = dict(report["stages"])
    assert stages["prepared"] == pytest.approx(100, abs=1)
    assert stages["first_llm"] == pytest.approx(500, abs=1)
    assert stages["first_tool"] == pytest.approx(1500, abs=1)
    assert report["total_ms"] == pytest.approx(2600, abs=1)


def test_finish_emits_one_line_per_turn():
    logged: list[dict] = []
    latency._logger.info = lambda event, **kw: logged.append(
        {"event": event, **kw})

    latency.start("t3", task="cari harga gpu")
    latency.mark("t3", "first_llm")
    latency.finish("t3")

    assert len(logged) == 1
    assert logged[0]["event"] == "latency.turn"
    assert "total_ms" in logged[0]
    assert "first_llm_ms" in logged[0]


def test_a_stage_marked_twice_keeps_the_first():
    """"LLM pertama" berarti yang PERTAMA; iterasi kedua tidak menimpanya."""
    clock = iter([0.0, 0.5, 1.9, 2.0])
    latency.start("t4", now=next(clock))
    latency.mark("t4", "first_llm", now=next(clock))
    latency.mark("t4", "first_llm", now=next(clock))

    report = latency.finish("t4", now=next(clock))

    assert dict(report["stages"])["first_llm"] == pytest.approx(500, abs=1)


# ── tidak boleh pernah mengganggu pekerjaan ───────────────────────────────

def test_marking_an_unknown_turn_never_raises():
    latency.mark("tidak-ada", "first_llm")
    assert latency.finish("tidak-ada") == {}


@pytest.mark.parametrize("key", [None, 0, "", object()])
def test_junk_keys_never_raise(key):
    latency.start(key)
    latency.mark(key, "x")
    latency.finish(key)


def test_turns_are_bounded_so_a_leak_cannot_grow_forever():
    """Pengukur tidak boleh menjadi kebocoran seperti S-14."""
    for index in range(latency.MAX_TURNS + 40):
        latency.start(f"turn-{index}")

    assert latency.active_count() <= latency.MAX_TURNS


def test_disabled_measurement_costs_nothing(monkeypatch):
    monkeypatch.setattr(latency, "enabled", lambda: False)
    latency.start("t5")
    latency.mark("t5", "first_llm")

    assert latency.finish("t5") == {}
    assert latency.active_count() == 0


# ── terpasang di jalur yang benar-benar lambat ────────────────────────────

def test_agent_loop_marks_first_llm_and_first_tool():
    """7 detik itu ada di loop; di situlah penanda harus berada."""
    import inspect

    from jarvis.agent import loop

    source = inspect.getsource(loop)
    assert "latency.mark" in source
    # "setup" dan "first_llm" harus TERPISAH: yang pertama adalah persiapan
    # (persona, memory search + embedding, schema), yang kedua durasi panggilan
    # model. Satu penanda saja mencampur keduanya dan tidak bisa ditindaklanjuti.
    assert "\"setup\"" in source
    assert "first_llm" in source
    assert "first_tool" in source


def test_dispatch_opens_and_closes_the_measurement():
    import inspect

    from jarvis.agent import dispatch

    source = inspect.getsource(dispatch)
    assert "latency.start" in source
    assert "latency.finish" in source


# ── temuan Fase 24: recall memori mendominasi latensi ─────────────────────

def test_memory_recall_has_a_deadline_so_it_cannot_stall_a_turn():
    """Temuan terukur: `memory_store.search` 3250 ms dingin, 422 ms hangat.

    Sebabnya embedding — round trip jaringan ke Gemini SEBELUM model ditanya
    sama sekali. Roadmap Siklus 4 mengasumsikan panggilan LLM yang dominan;
    pengukuran membantahnya. Itulah gunanya Fase 24 didahulukan.

    Pencarian keyword (FTS5) sepenuhnya lokal dan sudah ada sebagai fallback.
    Jadi recall semantik diberi tenggat: lewat dari itu, giliran ini memakai
    keyword saja. Jawaban yang sedikit kurang kaya jauh lebih baik daripada
    user menunggu tiga detik sebelum Jarvis mulai berpikir.
    """
    import jarvis.agent.memory_store as ms

    slept: dict = {}

    def _slow_embed(_texts):
        slept["called"] = True
        import time as _t
        _t.sleep(1.0)
        return [[0.1, 0.2, 0.3]]

    original = ms._embed
    ms._embed = _slow_embed
    try:
        import time as _t
        started = _t.monotonic()
        ms.search("apa pun", limit=4, embed_deadline_s=0.15)
        elapsed = _t.monotonic() - started
    finally:
        ms._embed = original

    assert slept.get("called") is True
    assert elapsed < 0.8, f"recall menahan giliran selama {elapsed:.2f}s"


def test_memory_recall_still_uses_embeddings_when_they_are_fast():
    """Tenggat tidak boleh berarti membuang recall semantik."""
    import jarvis.agent.memory_store as ms

    calls: list = []
    original = ms._embed
    ms._embed = lambda texts: (calls.append(texts), [[0.1, 0.2, 0.3]])[1]
    try:
        ms.search("apa pun", limit=4, embed_deadline_s=5.0)
    finally:
        ms._embed = original

    assert calls, "embedding cepat tetap harus dipakai"
