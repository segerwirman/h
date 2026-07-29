"""Fase 4 — optional, fact-grounded response composer."""
from __future__ import annotations

import time

from jarvis.agent import interaction, llm_client, response_composer
from jarvis.core import config


RAW_RESULT = (
    '**Video "Deddy Corbuzier Episode 123" sudah diputar.**\n'
    "URL: https://youtube.com/watch?v=abc123\n"
    r"Path: C:\Jarvis\reports\episode-123.txt"
)


def _delivery():
    return interaction.success_delivery(
        RAW_RESULT,
        "buka dan putar video terbaru Deddy Corbuzier",
        address="sir",
    )


def test_response_composer_config_aktif_dan_tetap_bounded():
    # DIAGNOSIS_2 MASALAH 4a — composer DINYALAKAN. Yang dijaga tes ini
    # bukan lagi "default mati", melainkan bahwa menyalakannya tidak
    # melonggarkan batas apa pun: deadline dan max_tokens tetap kecil,
    # sehingga delivery deterministik tetap menang saat provider lambat.
    assert config.get("auxiliary.response_composer.enabled") is True
    assert config.get("release_controls.naturalizer") is True
    assert config.get("auxiliary.response_composer.timeout_s") == 2.0
    assert config.get("auxiliary.response_composer.max_tokens") == 120


def test_composer_disabled_mengembalikan_delivery_deterministik_tanpa_client():
    calls = []

    result = response_composer.compose(
        _delivery(),
        "buka dan putar video terbaru Deddy Corbuzier",
        enabled=False,
        client_factory=lambda: calls.append("called"),
    )

    assert result == _delivery()
    assert calls == []


def test_composer_valid_memakai_speech_natural_dan_anchor_exact():
    class Client:
        def chat(self, messages, **kwargs):
            assert "Deddy Corbuzier Episode 123" in messages[-1]["content"]
            return llm_client.ChatResponse(
                content='Sudah saya putar "Deddy Corbuzier Episode 123" untuk Anda.'
            )

    deterministic = _delivery()
    result = response_composer.compose(
        deterministic,
        "buka dan putar video terbaru Deddy Corbuzier",
        enabled=True,
        client_factory=lambda: Client(),
        timeout_s=0.2,
    )

    assert result.display_text == deterministic.display_text
    assert result.factual_anchors == deterministic.factual_anchors
    assert result.mode == "natural"
    assert result.speech_text == 'Sudah saya putar "Deddy Corbuzier Episode 123" untuk Anda.'


def test_composer_anchor_berubah_fallback_ke_delivery_deterministik():
    class Client:
        def chat(self, *_args, **_kwargs):
            return llm_client.ChatResponse(content="Video episode 456 sudah diputar.")

    deterministic = _delivery()
    result = response_composer.compose(
        deterministic,
        "buka dan putar video terbaru Deddy Corbuzier",
        enabled=True,
        client_factory=lambda: Client(),
        timeout_s=0.2,
    )

    assert result is deterministic


def test_composer_tolak_anchor_angka_yang_hanya_prefix():
    class Client:
        def chat(self, *_args, **_kwargs):
            return llm_client.ChatResponse(content="Laporan build 1234 sudah selesai.")

    deterministic = interaction.success_delivery(
        "Laporan build 123 sudah selesai.", "buat laporan", address="sir"
    )
    result = response_composer.compose(
        deterministic,
        "buat laporan",
        enabled=True,
        client_factory=lambda: Client(),
        timeout_s=0.2,
    )

    assert result is deterministic


def test_composer_timeout_fallback_ke_delivery_deterministik():
    class SlowClient:
        def chat(self, *_args, **_kwargs):
            time.sleep(0.05)
            return llm_client.ChatResponse(content="Tidak boleh dipakai.")

    deterministic = _delivery()
    result = response_composer.compose(
        deterministic,
        "buka dan putar video terbaru Deddy Corbuzier",
        enabled=True,
        client_factory=lambda: SlowClient(),
        timeout_s=0.01,
    )

    assert result is deterministic
