"""Fase 42 — RED: ``speech_end`` harus punya offset terhadap awal ucapan.

Tiga pengukuran terpisah pada 2026-09-01, semuanya menunjukkan cacat yang
sama dari sisi yang berbeda. Ringkasnya:

1. ``latency.mark()`` menyimpan **selang sejak penanda terakhir**
   (``latency.py:93``). Semantik ini disengaja dan terkunci oleh
   ``tests/test_latency_breakdown.py:56-60``, jadi bukan biangnya.

2. ``_voice_intercept`` memanggil ``start`` dan ``mark("speech_end")`` pada
   saat yang sama (``window_voice.py:125-126``) — sesudah transkrip final
   tiba. Selangnya karena itu **selalu nol**. Ini menjelaskan anomali yang
   tercatat sejak 2026-08-19 tanpa penjelasan: lima emisi runtime dengan
   ``speech_end_ms`` tetap ``0.0``.

3. Lebih parah lagi: ``_voice_intercept`` **tidak pernah dipanggil oleh jalur
   Live**. Satu-satunya pemanggilnya adalah ``write_log``
   (``window_voice.py:112``), sedangkan jalur transkrip sesungguhnya hidup di
   ``main.py:1495-1540`` dan tidak pernah menyentuh ``write_log`` maupun
   ``ACTIVITY_LOG``. Jadi penanda ``voice_ack`` berada di cabang yang tidak
   terhubung ke transkrip live.

Titik ``start`` yang benar ada di ``main.py:1506`` (``if not in_buf:`` =
chunk pertama sebuah ucapan). ``main.py`` saat ini tidak menyebut ``latency``
sama sekali.
"""
from __future__ import annotations

import types
from pathlib import Path

from jarvis.core import latency


def test_speech_end_punya_offset_pada_alur_nyata():
    """Alur NYATA: ``begin_request`` membuka turn, intercept menandai.

    Ini ujian yang sesungguhnya. Versi tes ini sebelumnya **menipu**: ia
    memanggil ``_voice_intercept`` tanpa ``begin_request``, sehingga turn
    dibuka oleh ``start`` di dalam intercept — dan cacatnya tetap tersembunyi
    walau tes lolos.

    Alur produksi yang benar: ``main.py`` memanggil ``begin_request()`` pada
    chunk pertama ucapan, lalu ``_voice_intercept`` menandai ``speech_end``
    sesudah transkrip final tiba. Bila intercept masih memanggil ``start``,
    ia menimpa turn itu dan ``speech_end`` kembali nol.
    """
    from jarvis.core.state import PipelineStateMachine
    from jarvis.ui import window_voice as wv

    obj = object.__new__(wv.WindowVoiceMixin)
    obj.reply_flow = types.SimpleNamespace(handle_utterance=lambda _s: False)
    obj._pending_close_decision = None
    obj._pending_voice_proposal_id = None

    latency.reset()
    try:
        base = latency.time.monotonic()
        PipelineStateMachine().begin_request()      # awal ucapan
        # Transkrip final tiba di lain waktu; intercept hanya menandai.
        with __import__("unittest.mock", fromlist=["patch"]).patch.object(
            latency.time, "monotonic", lambda: base + 0.8
        ):
            obj._voice_intercept("tolong riset topik ini")
        report = latency.voice_handoff(now=base + 1.05)
    finally:
        latency.reset()

    stages = dict(report["stages"])
    assert stages["speech_end"] == 800.0, (
        f"speech_end = {stages.get('speech_end')!r} — intercept menimpa turn "
        f"dari begin_request, cacat Fase 42 muncul kembali"
    )
    assert report["total_ms"] == 1050.0, report


def test_intercept_tidak_terhubung_ke_jalur_transkrip_live():
    """BUKTI CACAT kedua: jalur Live tidak pernah mencapai ``_voice_intercept``.

    ``_voice_intercept`` hanya dipanggil dari ``write_log``. Bila ``main.py``
    tidak pernah menulis ke ``ACTIVITY_LOG``, maka penanda ``voice_ack``
    berada di cabang yang tak tersentuh transkrip live — dan ``speech_end``
    tak akan pernah punya offset, di mana pun ``start`` diletakkan di dalam
    ``window_voice.py``.

    Dua tes sumber di sini sengaja ditekan pada **ketiadaan**, bukan pada
    kalimat tertentu, supaya tidak rapuh terhadap ganti nama komentar.
    """
    source = Path("main.py").read_text(encoding="utf-8")
    assert "latency" not in source, (
        "main.py kini menyebut latency — penanda awal-ucapan mungkin sudah "
        "terpasang; ganti assertion ini dengan pengujian perilaku"
    )
    assert "ACTIVITY_LOG" not in source, (
        "main.py kini menulis ke ACTIVITY_LOG — jalur Live mungkin sudah "
        "mencapai _voice_intercept; ganti dengan pengujian perilaku"
    )


def test_jalur_live_memang_punya_titik_awal_ucapan():
    """BUKTI bahwa hook awal-ucapan ADA — hanya belum disambung ke latency.

    Dua jam sebelum tes ini, saya hampir mencatat "tidak ada hook awal
    ucapan" karena grep saya hanya menjangkau paket ``jarvis/``, padahal
    pemanggilnya hidup di ``main.py``. Tes ini memakukan koreksinya:
    ``main.py:1506`` (``if not in_buf:``) adalah awal ucapan yang
    sesungguhnya, lengkap dengan correlation id dan trace-nya.

    Jadi perbaikan Fase 42 BUKAN menambahkan hook baru, melainkan
    menyambungkan ``latency.start`` ke hook yang sudah ada.
    """
    source = Path("main.py").read_text(encoding="utf-8")
    assert "if not in_buf:" in source
    assert "turn.input_started" in source


def test_begin_request_membuka_turn_voice_ack():
    """RED: awal ucapan harus membuka turn ``voice_ack``.

    Fase 42 mandek karena tidak ada titik di luar ``main.py`` yang membuka
    turn ini, dan ``main.py`` adalah berkas **frozen**. ``begin_request()``
    dipanggil tepat di dalam blok ``if not in_buf:`` (awal ucapan) pada
    ``main.py:1509``, dan hidup di ``jarvis/core/state.py`` yang tidak frozen.

    Bila ia membuka turn, ``speech_end`` yang ditandai ``_voice_intercept``
    memperoleh offset nyata — cacat ``speech_end_ms = 0.0`` tertutup tanpa
    menyentuh satu pun berkas frozen.
    """
    from jarvis.core.state import PipelineStateMachine

    latency.reset()
    try:
        sm = PipelineStateMachine()
        base = latency.time.monotonic()
        sm.begin_request()                       # awal ucapan
        latency.mark("voice_ack", "speech_end", now=base + 0.8)
        report = latency.voice_handoff(now=base + 1.05)
    finally:
        latency.reset()

    stages = dict(report["stages"])
    assert stages.get("speech_end") == 800.0, (
        f"begin_request tidak membuka turn voice_ack — speech_end = "
        f"{stages.get('speech_end')!r}; cacat Fase 42 belum tertutup"
    )


def test_begin_request_tanpa_dispatch_tidak_menghasilkan_report_palsu():
    """Turn yang tak pernah di-dispatch tidak boleh jadi report palsu.

    `begin_request()` kini membuka turn `voice_ack` sebagai efek samping. Bila
    giliran itu tidak pernah mencapai dispatch, turn-nya tetap terbuka, dan
    `voice_handoff()` berikutnya akan menutup turn SISA itu — menghasilkan
    `total_ms: 0.0` tanpa `speech_end` (terukur 2026-09-01). Angka palsu yang
    tercatat seolah pengukuran sah.

    Tes ini menegaskan bentuk reportnya, supaya siapa pun yang kelak melihat
    `total_ms = 0.0` di log tahu itu turn yatim, bukan pengukuran.

    Catatan: `tests/test_state.py` memanggil `begin_request()` dan TIDAK
    memanggil `latency.reset()`. Saat ini tidak ada tes yang tercemar hanya
    karena tes-tes `latency` kebetulan memakai fixture reset. Itu
    perlindungan insidental, bukan rancangan — karenanya dicatat di sini.
    """
    from jarvis.core.state import PipelineStateMachine

    latency.reset()
    try:
        PipelineStateMachine().begin_request()   # tidak pernah di-dispatch
        report = latency.voice_handoff()
    finally:
        latency.reset()

    assert report["total_ms"] == 0.0, report
    assert "speech_end" not in dict(report["stages"]), (
        "turn yatim memuat speech_end — ia bukan lagi sisa, periksa wiring"
    )
