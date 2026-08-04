"""S-15 — komposer tidak boleh mengucapkan kalimat yang terpotong.

Gejalanya muncul sebagai test yang gagal acak: teks yang diucapkan terpotong
di tengah kata pada 44 karakter.

    'Video "Deddy Corbuzier Episode 123" sudah dip'

Bukan flake, dan bukan `sanitize_for_speech` — potongan itu tidak berakhiran
elipsis. Penyebabnya di produksi: `auxiliary.response_composer` aktif dengan
`max_tokens: 120`, dan `_validated_speech` memeriksa panjang, anchor wajib,
serta anchor terlarang — tetapi **tidak pernah memeriksa apakah kalimatnya
utuh**. Generasi yang terpotong token cap lolos keempat pemeriksaan lalu
diucapkan sebagai laporan.

Komposer sifatnya opsional: menolak kandidat selalu aman karena teks
deterministik yang sudah terverifikasi tetap dipakai.
"""
from __future__ import annotations

import pytest

from jarvis.agent import response_composer as rc
from jarvis.agent.interaction import success_delivery

_RAW = ('Video "Deddy Corbuzier Episode 123" sudah diputar.\n'
        "URL: https://youtube.com/watch?v=abc123")
_TASK = "putar video terbaru deddy corbuzier"


@pytest.fixture
def delivery():
    return success_delivery(_RAW, _TASK)


@pytest.mark.parametrize("candidate", [
    'Video "Deddy Corbuzier Episode 123" sudah dip',
    'Video "Deddy Corbuzier Episode 123" sudah diputar dan sekarang sedang',
    'Video "Deddy Corbuzier Episode 123" sudah diputar,',
    'Video "Deddy Corbuzier Episode 123" sudah diputar -',
])
def test_truncated_candidate_is_rejected(candidate, delivery):
    """Kandidat tanpa akhir kalimat = generasi terpotong. Tolak."""
    required = rc._speech_anchors(delivery)
    assert rc._validated_speech(candidate, delivery, required) == ""


@pytest.mark.parametrize("candidate", [
    'Video "Deddy Corbuzier Episode 123" sudah diputar, sir.',
    'Sudah saya putar video "Deddy Corbuzier Episode 123"!',
    'Video "Deddy Corbuzier Episode 123" sudah diputar. Ada lagi?',
])
def test_complete_candidate_is_still_accepted(candidate, delivery):
    """Gerbang yang menolak semuanya tidak memverifikasi apa pun."""
    required = rc._speech_anchors(delivery)
    assert rc._validated_speech(candidate, delivery, required) == candidate


def test_truncated_generation_falls_back_to_deterministic_text(delivery):
    """Kontrak komposer: gagal apa pun → teks deterministik dipakai utuh."""
    result = rc.compose(
        delivery, _TASK, enabled=True,
        client_factory=lambda: _FakeClient(
            'Video "Deddy Corbuzier Episode 123" sudah dip'),
    )

    assert result.speech_text == delivery.speech_text
    assert result.speech_text.endswith(".")
    assert result.mode != "natural"


def test_complete_generation_still_replaces_the_deterministic_text(delivery):
    natural = 'Video "Deddy Corbuzier Episode 123" sudah diputar, sir.'
    result = rc.compose(delivery, _TASK, enabled=True,
                        client_factory=lambda: _FakeClient(natural))

    assert result.speech_text == natural
    assert result.mode == "natural"


class _FakeClient:
    def __init__(self, reply: str):
        self._reply = reply

    def available(self) -> bool:
        return True

    def generate(self, *_a, **_k) -> str:
        return self._reply

    def chat(self, *_a, **_k):
        class _R:
            ok = True
            error = None
            tool_calls: list = []

        response = _R()
        response.content = self._reply
        return response


# ── higiene tes: suite tidak boleh memanggil provider sungguhan ───────────

def test_ingress_tests_do_not_reach_a_live_provider():
    """Test yang memanggil LLM nyata gagal acak dan menyeret jaringan.

    `test_typed_t2_speaks_ack_then_concrete_report` memakai delivery lifecycle
    dengan `naturalize=True`, sementara `auxiliary.response_composer.enabled`
    bernilai true di config repo — jadi tanpa stub ia benar-benar menembak
    endpoint provider di tengah suite.
    """
    from pathlib import Path

    source = Path("tests/test_phase2_ingress.py").read_text(encoding="utf-8")
    body = source.split("def test_typed_t2_speaks_ack_then_concrete_report")[1]
    body = body.split("\ndef ")[0]
    assert "response_composer" in body, (
        "test ini harus menstub komposer, bukan memanggil provider nyata")
