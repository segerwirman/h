"""Fase 51 — RED: akhir giliran harus MEMBATALKAN turn voice_ack yang tak pernah dispatch.

Cacat yang diukur pada 2026-09-01, sesudah commit `de0bb51`:

1. Latensi dibuka oleh `PipelineStateMachine.begin_request()` (`state.py:114`)
   pada chunk pertama ucapan.
2. `finish()` (`state.py:166`) hanya menulis log dan memanggil `to()`. Ia
   **tidak menyentuh `latency`**. Terukur: `active_count` tetap 1 sesudah
   `finish()`.
3. `voice_handoff()` (`dispatch.py:1087`) dipanggil untuk **setiap** dispatch,
   termasuk non-voice. Maka turn yatim ditutup oleh dispatch berikutnya —
   berapa pun jaraknya.

Terukur: ucapan dimulai, giliran berakhir tanpa dispatch, lalu dispatch
Telegram tiga jam kemudian menghasilkan

    {'task': 'voice:f29dd7da', 'total_ms': 10800000.0,
     'stages': [('dispatch_start', 10800000.0)]}

berlabel `voice:...` padahal dispatch-nya bukan suara, dan tanpa `speech_end`
yang bisa dikenali sebagai penanda turn yatim.

`latency` juga tidak punya primitif `cancel` — API publiknya hanya `enabled`,
`start`, `mark`, `finish`, `voice_handoff`, `active_count`, `reset`. Tes ini
karena itu menuntut dua hal: primitifnya ada, dan akhir giliran memakainya.
"""
from __future__ import annotations

from jarvis.core import latency
from jarvis.core.state import Outcome, PipelineStateMachine


def _reset():
    latency.reset()


def test_latency_punya_primitif_cancel():
    """`latency.cancel(key)` harus ada, atau turn yatim tak bisa ditutup.

    `voice_handoff()` memanggil `finish()`, dan itu satu-satunya penutup turn
    `voice_ack`. Tanpa `cancel`, tidak ada cara membuang turn yang sah-sah
    saja tidak pernah mencapai dispatch.
    """
    _reset()
    try:
        assert hasattr(latency, "cancel"), (
            "latency tidak punya cancel() — turn voice_ack yang tidak pernah "
            "di-dispatch hanya bisa ditutup oleh dispatch berikutnya, "
            "berapa pun jaraknya"
        )
        latency.start("voice_ack", task="voice:test")
        assert latency.active_count() == 1
        latency.cancel("voice_ack")
        assert latency.active_count() == 0, (
            "cancel('voice_ack') tidak menghapus turn dari _turns"
        )
    finally:
        _reset()


def test_finish_tanpa_dispatch_membatalkan_turn_voice_ack():
    """Giliran yang berakhir tanpa dispatch tidak boleh meninggalkan turn.

    Ini akar penyebabnya, bukan gejalanya. Terukur sebelum perbaikan:
    `active_count()` tetap 1 sesudah `PipelineStateMachine.finish()`.
    """
    _reset()
    try:
        sm = PipelineStateMachine()
        sm.begin_request()
        assert latency.active_count() == 1, "begin_request tidak membuka turn"
        sm.finish(Outcome.NO_SPEECH)          # giliran berakhir tanpa dispatch
        assert latency.active_count() == 0, (
            "finish() meninggalkan turn voice_ack terbuka — ia akan ditutup "
            "oleh dispatch berikutnya, bukan oleh giliran ini"
        )
    finally:
        _reset()


def test_turn_yatim_tidak_lagi_menghasilkan_report_palsu():
    """Report `voice_handoff` sesudah giliran gagal harus kosong, bukan 3 jam.

    Inilah angka yang dulu tercatat seolah pengukuran sah. Sebelum perbaikan:
    `total_ms: 10800000.0` berlabel `voice:...` tanpa `speech_end`.
    """
    _reset()
    try:
        base = latency.time.monotonic()
        sm = PipelineStateMachine()
        sm.begin_request()
        sm.finish(Outcome.NO_SPEECH)           # giliran berakhir tanpa dispatch
        report = latency.voice_handoff(now=base + 3 * 3600)
    finally:
        _reset()

    assert report == {}, (
        f"turn yatim masih menghasilkan report: {report!r} — dispatch non-voice "
        f"menutup sisa giliran suara dan mencatatnya seolah rentang gelap"
    )


def test_setiap_outcome_membatalkan_turn_bukan_hanya_sukses():
    """`main.py:1612` memanggil `_sm.finish()` hanya bila outcome == success.

    Jalur `unrecognized_speech` tidak memanggilnya. Jadi pembatalan tidak
    boleh bergantung pada outcome tertentu — setiap akhir giliran membatalkan.
    """
    _reset()
    try:
        for outcome in Outcome:
            _reset()
            sm = PipelineStateMachine()
            sm.begin_request()
            assert latency.active_count() == 1, f"{outcome}: turn tak terbuka"
            sm.finish(outcome)
            assert latency.active_count() == 0, (
                f"finish({outcome.value}) meninggalkan turn terbuka — "
                f"penumpukan tidak boleh bergantung pada outcome"
            )
    finally:
        _reset()


def test_jalur_sukses_tetap_menghasilkan_report_asli():
    """Perbaikan tidak boleh mematikan pengukuran yang sah.

    Urutan produksi yang benar: `begin_request` membuka, intercept menandai
    `speech_end`, lalu dispatch menutup lewat `voice_handoff()`. Angka
    1050.0 terkunci oleh `test_speech_end_punya_offset_pada_alur_nyata`, dan
    tes ini menjaga agar pembatalan tidak menghapusnya lebih awal.
    """
    _reset()
    try:
        base = latency.time.monotonic()
        sm = PipelineStateMachine()
        sm.begin_request()
        latency.mark("voice_ack", "speech_end", now=base + 0.8)
        report = latency.voice_handoff(now=base + 1.05)
        assert report["total_ms"] == 1050.0, report
        stages = dict(report["stages"])
        assert stages["speech_end"] == 800.0, report
        assert latency.active_count() == 0
    finally:
        _reset()


def test_finish_sesudah_dispatch_tetap_aman():
    """`finish()` boleh dipanggil SETELAH dispatch sudah menutup turn.

    Di `main.py`, `_sm.finish()` (baris 1612) terjadi sesudah dispatch, jadi
    pembatalan di dalamnya akan menyasar turn yang sudah tiada. Terukur
    sebelum perbaikan bahwa keadaan ini aman; tes ini menguncinya.
    """
    _reset()
    try:
        base = latency.time.monotonic()
        sm = PipelineStateMachine()
        sm.begin_request()
        report = latency.voice_handoff(now=base + 1.05)   # dispatch menutup
        assert report["total_ms"] == 1050.0 or "total_ms" in report
        sm.finish(Outcome.SUCCESS)                        # sesudah turn ditutup
        assert latency.active_count() == 0
    finally:
        _reset()


def test_cancel_tanpa_turn_tidak_melempar():
    """Pengukur tidak pernah boleh menjatuhkan giliran.

    Aturan modul `latency.py:16`: tidak pernah melempar, tidak pernah
    menahan pekerjaan. Membatalkan turn yang tak ada harus no-op.
    """
    _reset()
    try:
        assert hasattr(latency, "cancel")
        latency.cancel("voice_ack")            # tidak ada turn
        latency.cancel("")                     # kunci kosong
        latency.cancel(None)                   # kunci bukan string
        assert latency.active_count() == 0
    finally:
        _reset()


def test_cancel_tidak_menerbitkan_baris_log():
    """`cancel()` membuang turn secara diam-diam — ia bukan `finish()`.

    Mengapa tes ini ada, dan mengapa ia lahir dari mutan yang HIDUP: mutan yang
    membuat `cancel()` memanggil `finish()` lolos dari seluruh tujuh tes di
    atas (terukur 2026-09-01). Semuanya mengukur KEBERADAAN turn lewat
    `active_count()`, bukan keluaran lognya. Padahal `finish()` selalu
    menerbitkan satu baris `latency.turn` — jadi `cancel()` yang memanggilnya
    akan tetap menuliskan angka palsu yang hendak dihapus oleh Fase 51.

    Inti `cancel` adalah "tanpa pernah menerbitkan baris log". Tanpa tes ini,
    sifat yang menjadi alasan primitif ini dibuat tidak dijaga oleh apa pun.
    """
    import logging

    from jarvis.core import log as jarvis_log

    _reset()
    try:
        handler = logging.Handler()
        records: list[logging.LogRecord] = []
        handler.emit = records.append                      # type: ignore[method-assign]
        target = jarvis_log.get("core.latency")
        target.addHandler(handler)
        try:
            latency.start("voice_ack", task="voice:test")
            latency.cancel("voice_ack")
        finally:
            target.removeHandler(handler)

        # structlog merender seluruh fields menjadi SATU string JSON di
        # `record.msg` — atribut `event` tidak pernah ada pada record-nya
        # (terukur 2026-09-01: getattr(r, "event", None) selalu None). Filter
        # pada `event` akan selalu kosong dan membuat tes ini palsu lolos.
        turns = [r for r in records if '"event": "latency.turn"' in str(r.msg)]
        assert turns == [], (
            f"cancel() menerbitkan {len(turns)} baris latency.turn — ia "
            f"memanggil finish(), sehingga turn yang dibuang tetap tercatat "
            f"seolah pengukuran sah: {[r.msg for r in turns]}"
        )
    finally:
        _reset()
