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


def test_speech_end_offset_masih_nol_cacat_yang_tercatat():
    """BUKTI CACAT: ``speech_end_ms`` bernilai nol pada jalur intercept UI.

    Menjalankan ``_voice_intercept`` produksi yang sesungguhnya, bukan salinan
    logikanya, supaya tes tidak bisa hijau dengan meniru kesalahan yang sama.
    """
    from jarvis.ui import window_voice as wv

    obj = object.__new__(wv.WindowVoiceMixin)
    obj.reply_flow = types.SimpleNamespace(handle_utterance=lambda _s: False)
    obj._pending_close_decision = None
    obj._pending_voice_proposal_id = None

    latency.reset()
    try:
        # Tier AGENT membuat _voice_intercept return di baris 147-151,
        # sebelum menyentuh self.router — jadi objek di atas cukup.
        obj._voice_intercept("tolong riset topik ini")
        report = latency.voice_handoff(now=latency.time.monotonic() + 0.05)
    finally:
        latency.reset()

    stages = dict(report.get("stages", []))
    # Cacat: speech_end selalu nol karena start dan mark terjadi bersamaan.
    assert stages.get("speech_end") == 0.0, (
        "speech_end kini tidak nol — cacat Fase 42 sudah tertutup; "
        "balikkan assertion ini menjadi > 0 agar ia mengunci perbaikannya"
    )


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
