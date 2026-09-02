"""Fase 25 — perintah yang TERBUKTI berhasil dijalankan ulang tanpa LLM.

Fase 26 membuat Jarvis menebak *tool mana*; fase ini menghapus tebakannya
sama sekali untuk perintah yang persis sama: rencana yang sudah terbukti
dijalankan langsung, tanpa satu pun panggilan model.

Kuncinya adalah aliran token ternormalisasi (`local_embed.tokens`), bukan
kemiripan. Itu pilihan yang disengaja dan merupakan batas keras fase ini:
kesopanan dan imbuhan boleh berbeda ("tolong bukakan kameranya" = "buka
kamera"), tetapi setiap kata isi harus sama. "telepon Honbru" bukan "telepon
Honbrew", dan rencana yang tersimpan tidak boleh menjawabnya.
"""
from __future__ import annotations

import pytest

from jarvis.agent import command_plan
from jarvis.agent.base import ToolResult


@pytest.fixture
def plans(tmp_path, monkeypatch):
    monkeypatch.setattr(command_plan, "_db_path",
                        lambda: tmp_path / "plan.sqlite")
    command_plan.reset()
    return command_plan


def _step(tool="open_app", args=None, display="Spotify dibuka."):
    return {"tool": tool, "args": dict(args or {"name": "spotify"}),
            "display": display}


# ── kunci: aliran token, bukan kemiripan ──────────────────────────────────

def test_the_same_command_worded_politely_still_matches(plans):
    plans.remember("buka kamera", [_step("open_camera", {}, "Kamera dibuka.")])

    assert plans.recall("tolong bukakan kameranya dong") is not None


def test_a_near_miss_name_is_never_replayed(plans):
    """Batas keras dari rencananya: "telepon Honbru" bukan "telepon Honbrew".

    Satu huruf memisahkan menelepon orang yang benar dari menelepon orang
    yang salah. Kemiripan tidak boleh menjembataninya.
    """
    plans.remember("telepon Honbrew",
                   [_step("whatsapp_call", {"contact": "Honbrew"},
                          "Panggilan tersambung.")])

    assert plans.recall("telepon Honbru") is None


def test_an_extra_content_word_is_a_different_command(plans):
    plans.remember("buka kamera", [_step("open_camera", {}, "Kamera dibuka.")])

    assert plans.recall("buka kamera depan") is None


def test_recall_returns_the_recorded_tool_and_arguments(plans):
    plans.remember("putar lagu di spotify",
                   [_step("open_app", {"name": "spotify"}, "Dibuka.")])

    steps = plans.recall("putarkan lagunya di spotify")

    assert [step["tool"] for step in steps] == ["open_app"]
    assert steps[0]["args"] == {"name": "spotify"}


def test_the_newest_plan_wins_for_the_same_command(plans):
    plans.remember("buka musik", [_step("open_app", {"name": "spotify"})])
    plans.remember("buka musik", [_step("open_app", {"name": "youtube"})])

    assert plans.recall("buka musik")[0]["args"] == {"name": "youtube"}


# ── apa yang TIDAK boleh disimpan ─────────────────────────────────────────

def test_a_plan_with_redacted_arguments_is_never_stored(plans):
    """Argumen teraudit sudah disamarkan; menjalankannya ulang berarti
    mengeksekusi nilai bertopeng — lebih buruk daripada tidak menyimpan.
    """
    stored = plans.remember("kirim token rahasia",
                            [_step("http_post", {"api_key": "sk-live-123"})])

    assert stored is False
    assert plans.recall("kirim token rahasia") is None


def test_desktop_safe_plans_are_never_stored(plans):
    """Audit desktop_safe sengaja buram; tidak ada argumen untuk diulang."""
    assert plans.remember(
        "klik tombol simpan",
        [_step("desktop_safe_click", {"ref": "e17"}, "Diklik.")]) is False


def test_a_long_plan_is_not_replayable(plans):
    steps = [_step(f"tool_{n}", {"n": n}) for n in range(command_plan.MAX_STEPS + 1)]

    assert plans.remember("tugas panjang", steps) is False


def test_a_plan_without_a_short_spoken_result_is_not_stored(plans):
    """Hasil panjang berarti modelnya sedang MERANGKAI jawaban, bukan
    sekadar bertindak. Merangkai tidak bisa diulang dari cache.
    """
    assert plans.remember("ringkas berita hari ini",
                          [_step("web_search", {"q": "berita"},
                                 "x" * 400)]) is False


def test_nothing_is_stored_for_an_empty_plan(plans):
    assert plans.remember("apa saja", []) is False
    assert plans.count() == 0


def test_the_table_is_bounded(plans):
    for number in range(command_plan.MAX_ENTRIES + 30):
        plans.remember(f"perintah nomor {number}", [_step("noop", {"n": number})])

    assert plans.count() <= command_plan.MAX_ENTRIES


def test_recall_never_raises_on_junk(plans):
    plans.remember(None, None)
    plans.remember(12, "bukan langkah")
    assert plans.recall(None) is None
    assert plans.recall(object()) is None


def test_a_forgotten_plan_stops_being_replayed(plans):
    plans.remember("buka kamera", [_step("open_camera", {}, "Kamera dibuka.")])
    plans.forget("buka kamera")

    assert plans.recall("buka kamera") is None


def test_the_feature_can_be_switched_off(plans, monkeypatch):
    plans.remember("buka kamera", [_step("open_camera", {}, "Kamera dibuka.")])
    monkeypatch.setattr(command_plan.config, "get",
                        lambda path, default=None:
                        False if "command_plan.enabled" in path else default)

    assert plans.recall("buka kamera") is None


# ── argumen yang benar-benar dijalankan, bukan yang sudah diaudit ─────────

def test_registry_offers_true_arguments_on_a_dedicated_channel():
    """``record_tool`` dan ``record_evidence`` KEDUANYA menerima argumen yang
    sudah diredaksi. Membonceng salah satunya berarti menyimpan rencana yang
    berisi nilai bertopeng dan menjalankannya besok.
    """
    import inspect

    from jarvis.agent import registry

    source = inspect.getsource(registry._log_call)
    assert "record_plan" in source
    # Harus argumen ASLI, bukan yang teraudit.
    line = [ln for ln in source.splitlines() if "record_plan(" in ln][0]
    assert "safe_args" not in line


def test_session_has_a_no_op_plan_channel_by_default():
    from jarvis.agent.session import Session

    session = Session(task="apa saja", adapter_name="null")
    assert session.record_plan("open_app", {"name": "spotify"},
                               ToolResult.success("ok")) is None


# ── dijalankan ulang lewat dispatch ───────────────────────────────────────

@pytest.fixture
def wired(tmp_path, monkeypatch):
    """Dispatch dengan indeks + rencana terisolasi dan agent loop palsu."""
    from jarvis.agent import command_index, dispatch
    from jarvis.agent import loop as agent_loop
    from jarvis.agent import session as session_module

    monkeypatch.setattr(command_plan, "_db_path",
                        lambda: tmp_path / "plan.sqlite")
    monkeypatch.setattr(command_index, "_db_path",
                        lambda: tmp_path / "index.sqlite")
    # Fase 67 — dulu baris ini men-stub ``Session.finish`` menjadi no-op.
    # Stub itu membuat SELURUH jalur sukses kebal terhadap mutasi: terukur
    # ``session.finish(text, ok=True)`` di dispatch.py bisa dihapus tanpa satu
    # test pun berkedip. Alasannya isolasi yang masuk akal -- tanpa stub,
    # ``Session.finish`` menulis ke ``data/agent.sqlite`` milik pemakai
    # (terbukti: db_path tetap menunjuk ke sana bahkan di dalam pytest).
    # Maka stub diganti, bukan dihapus: DB sesi dialihkan ke tmp_path supaya
    # penulisan NYATA tetap terjadi dan teramati, tetapi tidak menyentuh data
    # pemakai. Terukur: baris agent_sessions pemakai tetap 514 sebelum dan
    # sesudah pengalihan.
    monkeypatch.setattr(session_module, "db_path",
                        lambda: tmp_path / "session.sqlite")
    command_plan.reset()
    command_index.reset()
    monkeypatch.setattr(dispatch, "available", lambda: True)
    monkeypatch.setattr(agent_loop, "run", None)      # diisi tiap tes
    return dispatch


def _run(dispatch, task, timeout=20):
    import threading

    outcome: dict = {}
    done = threading.Event()

    def _ok(text):
        outcome["text"] = text
        done.set()

    def _err(text):
        outcome["error"] = text
        done.set()

    assert dispatch.dispatch_async(task, on_done=_ok, on_error=_err)
    assert done.wait(timeout), "dispatch tidak pernah selesai"
    return outcome


def test_dispatch_learns_a_plan_from_a_verified_success(wired, monkeypatch):
    from jarvis.agent import loop as agent_loop
    from jarvis.agent.loop import RunResult

    async def fake_run(_task, *, adapter, session, **_kwargs):
        session.record_plan("open_app", {"name": "spotify"},
                            ToolResult.success("dibuka", display="Spotify dibuka."))
        await adapter.send("Spotify dibuka.")
        return RunResult(ok=True, text="Spotify dibuka.", session_id=session.id)

    monkeypatch.setattr(agent_loop, "run", fake_run)
    _run(wired, "buka spotify")

    steps = command_plan.recall("buka spotify")
    assert steps is not None
    assert steps[0]["tool"] == "open_app"
    assert steps[0]["args"] == {"name": "spotify"}


def test_sukses_mencatat_perintah_yang_terbukti_berhasil(wired, monkeypatch):
    """Perintah yang terbukti berhasil harus masuk indeks (§26).

    RED untuk Fase 66. Uji mutasi membuktikan ``_learn_command(task, session)``
    pada jalur sukses (``dispatch.py:1215``) bisa dilewati tanpa satu test pun
    berkedip. Akibatnya Jarvis tidak pernah belajar dari keberhasilan, padahal
    ``_learn_plan`` — yang berdiri TEPAT di sebelahnya — sudah terjaga oleh dua
    test. Jadi cacatnya bukan "pembelajaran tidak diuji", melainkan
    "setengah dari pembelajaran tidak diuji".

    Diamati lewat efek yang terlihat pemakai: ``command_index.suggest``
    mengembalikan tool untuk perintah yang serupa. Bukan lewat pencatatan
    pemanggilan internal, agar test tidak mengunci implementasi.
    """
    from jarvis.agent import command_index
    from jarvis.agent import loop as agent_loop
    from jarvis.agent.loop import RunResult

    async def fake_run(_task, *, adapter, session, **_kwargs):
        # ``_learn_command`` membaca ``session.tool_calls`` — kanal yang sama
        # yang dipakai registry sungguhan lewat ``record_tool``. Mengisi
        # ``record_plan`` saja tidak cukup: itu kanal rencana, bukan kanal
        # panggilan tool, sehingga indeks akan tetap kosong.
        session.record_tool("open_app", {"name": "spotify"},
                            ToolResult.success("dibuka", display="Spotify dibuka."),
                            0.01)
        await adapter.send("Spotify dibuka.")
        return RunResult(ok=True, text="Spotify dibuka.", session_id=session.id)

    monkeypatch.setattr(agent_loop, "run", fake_run)

    assert command_index.count() == 0, "indeks harus mulai kosong"
    _run(wired, "buka aplikasi spotify sekarang")

    # Efek yang terukur: indeks bertambah DAN dapat menyarankan kembali.
    assert command_index.count() >= 1, (
        "perintah yang terbukti berhasil tidak pernah dicatat — Jarvis tidak "
        "pernah belajar dari keberhasilan"
    )
    suggested = command_index.suggest("buka aplikasi spotify sekarang")
    assert suggested, "perintah sudah dicatat tetapi tidak dapat disarankan"
    assert "open_app" in suggested, (
        f"saran tidak memuat tool yang benar-benar berhasil: {suggested}"
    )


def test_a_learned_plan_runs_without_the_model(wired, monkeypatch):
    """Inti fase ini: giliran kedua tidak menyentuh model sama sekali."""
    from jarvis.agent import loop as agent_loop, registry

    calls: list[tuple] = []

    async def never(*_args, **_kwargs):
        raise AssertionError("agent loop dipanggil untuk rencana yang sudah terbukti")

    async def fake_execute(name, args, adapter=None, session=None,
                           context=None, **_kwargs):
        calls.append((name, dict(args)))
        return ToolResult.success("dibuka", display="Spotify dibuka.")

    command_plan.remember("buka spotify", [
        {"tool": "open_app", "args": {"name": "spotify"},
         "display": "Spotify dibuka."}])
    monkeypatch.setattr(agent_loop, "run", never)
    monkeypatch.setattr(registry, "execute", fake_execute)
    monkeypatch.setattr(registry, "get", lambda name: object())

    outcome = _run(wired, "tolong bukakan spotify")

    assert calls == [("open_app", {"name": "spotify"})]
    assert outcome.get("text") == "Spotify dibuka."


def test_replay_falls_back_to_the_model_when_a_step_fails(wired, monkeypatch):
    from jarvis.agent import loop as agent_loop, registry
    from jarvis.agent.loop import RunResult

    used_model = []

    async def fake_run(_task, *, adapter, session, **_kwargs):
        used_model.append(True)
        return RunResult(ok=True, text="Lewat model.", session_id=session.id)

    async def failing(name, args, adapter=None, session=None,
                      context=None, **_kwargs):
        return ToolResult.fail("aplikasi tidak ditemukan")

    command_plan.remember("buka spotify", [
        {"tool": "open_app", "args": {"name": "spotify"},
         "display": "Spotify dibuka."}])
    monkeypatch.setattr(agent_loop, "run", fake_run)
    monkeypatch.setattr(registry, "execute", failing)
    monkeypatch.setattr(registry, "get", lambda name: object())

    outcome = _run(wired, "buka spotify")

    assert used_model, "kegagalan replay harus jatuh ke model, bukan menyerah"
    assert outcome.get("text") == "Lewat model."
    assert command_plan.recall("buka spotify") is None, "rencana basi harus dibuang"


def test_a_plan_naming_a_missing_tool_is_not_replayed(wired, monkeypatch):
    from jarvis.agent import loop as agent_loop, registry
    from jarvis.agent.loop import RunResult

    used_model = []

    async def fake_run(_task, *, adapter, session, **_kwargs):
        used_model.append(True)
        return RunResult(ok=True, text="Lewat model.", session_id=session.id)

    command_plan.remember("buka spotify", [
        {"tool": "tool_yang_sudah_dihapus", "args": {}, "display": "ok"}])
    monkeypatch.setattr(agent_loop, "run", fake_run)
    monkeypatch.setattr(registry, "get", lambda name: None)

    _run(wired, "buka spotify")

    assert used_model


def test_replay_never_speaks_the_sentence_it_stored(wired, monkeypatch):
    """Kalimat kemarin bisa memuat fakta kemarin ("cuacanya 30 derajat").

    Yang diucapkan harus hasil RUN INI, bukan rekaman.
    """
    from jarvis.agent import loop as agent_loop, registry

    async def never(*_args, **_kwargs):
        raise AssertionError("model tidak boleh dipanggil")

    async def fake_execute(name, args, adapter=None, session=None,
                           context=None, **_kwargs):
        return ToolResult.success("ok", display="Kamera belakang dibuka.")

    command_plan.remember("buka kamera", [
        {"tool": "open_camera", "args": {}, "display": "Kamera depan dibuka."}])
    monkeypatch.setattr(agent_loop, "run", never)
    monkeypatch.setattr(registry, "execute", fake_execute)
    monkeypatch.setattr(registry, "get", lambda name: object())

    outcome = _run(wired, "buka kamera")

    assert outcome.get("text") == "Kamera belakang dibuka."


def test_replay_goes_through_the_registry_so_gates_still_apply():
    """Tujuh fase dihabiskan membuat klaim Jarvis jujur; kecepatan tidak
    boleh dibeli dengan melewati konfirmasi, policy, atau audit.
    """
    import inspect

    from jarvis.agent import dispatch

    source = inspect.getsource(dispatch._replay_plan)
    assert "registry.execute" in source
    assert "_approved" not in source, "replay tidak boleh mengaku sudah disetujui"


def test_a_mid_plan_failure_is_reported_not_silently_redone(wired, monkeypatch):
    """Langkah 1 sudah berjalan; mengulang lewat model berarti dua kali.

    Ini kebalikan dari kegagalan di langkah PERTAMA, yang aman diserahkan ke
    model karena belum ada apa pun yang terjadi.
    """
    from jarvis.agent import loop as agent_loop, registry

    async def never(*_args, **_kwargs):
        raise AssertionError("model tidak boleh mengulang aksi yang sudah jalan")

    ran: list[str] = []

    async def half_working(name, args, adapter=None, session=None,
                           context=None, **_kwargs):
        ran.append(name)
        if name == "open_app":
            return ToolResult.success("ok", display="Spotify dibuka.")
        return ToolResult.fail("playlist tidak ditemukan")

    command_plan.remember("putar playlist pagi", [
        {"tool": "open_app", "args": {"name": "spotify"},
         "display": "Spotify dibuka."},
        {"tool": "play_playlist", "args": {"name": "pagi"},
         "display": "Diputar."}])
    monkeypatch.setattr(agent_loop, "run", never)
    monkeypatch.setattr(registry, "execute", half_working)
    monkeypatch.setattr(registry, "get", lambda name: object())

    outcome = _run(wired, "putar playlist pagi")

    assert ran == ["open_app", "play_playlist"]
    error = outcome.get("error", "")
    assert "play_playlist" in error
    assert "playlist tidak ditemukan" in error
    assert "tidak saya ulang" in error
    assert command_plan.recall("putar playlist pagi") is None


def test_only_successful_steps_enter_a_learned_plan(wired, monkeypatch):
    """Rencananya adalah apa yang BERHASIL, bukan catatan percobaan model."""
    from jarvis.agent import loop as agent_loop
    from jarvis.agent.loop import RunResult

    async def fake_run(_task, *, adapter, session, **_kwargs):
        session.record_plan("open_app", {"name": "spotifi"},
                            ToolResult.fail("aplikasi tidak ditemukan"))
        session.record_plan("open_app", {"name": "spotify"},
                            ToolResult.success("ok", display="Spotify dibuka."))
        return RunResult(ok=True, text="Spotify dibuka.", session_id=session.id)

    monkeypatch.setattr(agent_loop, "run", fake_run)
    _run(wired, "buka spotify")

    steps = command_plan.recall("buka spotify")
    assert [step["args"] for step in steps] == [{"name": "spotify"}]


def test_a_session_without_the_plan_channel_still_runs(wired, monkeypatch):
    """Belajar itu kenyamanan; ia tidak boleh menjatuhkan tugasnya.

    ``registry`` sudah memakai kanal ini secara defensif — dispatch harus
    sama, kalau tidak satu sesi pihak ketiga cukup untuk mematahkan semuanya.
    """
    from jarvis.agent import loop as agent_loop
    from jarvis.agent import session as session_module
    from jarvis.agent.loop import RunResult

    class _PlainSession:
        def __init__(self, task, adapter_name):
            self.id = "sesi-tanpa-kanal"
            self.task = task
            self.tool_calls = []
            self.execution_context = None

        def cancel(self):
            pass

        def finish(self, *_args, **_kwargs):
            pass

    async def fake_run(_task, *, adapter, session, **_kwargs):
        return RunResult(ok=True, text="Selesai.", session_id=session.id)

    monkeypatch.setattr(session_module, "Session", _PlainSession)
    monkeypatch.setattr(agent_loop, "run", fake_run)

    assert _run(wired, "kerjakan sesuatu").get("text") == "Selesai."
