"""Fase 3 — deterministic ConversationDelivery."""
from __future__ import annotations

from jarvis.agent import interaction


def test_default_speech_budget_besar_agar_tidak_terpotong():
    # Default besar agar kalimat JARVIS tidak terpotong di tengah.
    assert interaction.speech_limit() >= 600
    assert interaction.SPEECH_LIMIT >= 600


def test_success_delivery_memisahkan_display_dan_speech_dengan_anchor():
    raw = (
        '**Video "Deddy Corbuzier Episode 123" sudah diputar.**\n'
        "URL: https://youtube.com/watch?v=abc123\n"
        r"Log lengkap tersimpan di C:\Jarvis\reports\episode-123.txt"
    )

    delivery = interaction.success_delivery(
        raw,
        "buka dan putar video terbaru Deddy Corbuzier",
        address="sir",
    )

    assert delivery.display_text == (
        'Video "Deddy Corbuzier Episode 123" sudah diputar.\n'
        "URL: https://youtube.com/watch?v=abc123\n"
        r"Log lengkap tersimpan di C:\Jarvis\reports\episode-123.txt"
    )
    assert delivery.speech_text != delivery.display_text
    assert "Deddy Corbuzier Episode 123" in delivery.speech_text
    assert "Deddy Corbuzier Episode 123" in delivery.factual_anchors
    assert "123" in delivery.factual_anchors
    assert "https://youtube.com/watch?v=abc123" in delivery.factual_anchors
    assert r"C:\Jarvis\reports\episode-123.txt" in delivery.factual_anchors
    assert len(delivery.speech_text) <= interaction.SPEECH_LIMIT


def test_failure_delivery_mempertahankan_detail_dan_brief_yang_jujur():
    raw = "permission denied for C:\\Jarvis\\reports\\secret.txt (code 403)"

    delivery = interaction.failure_delivery(
        raw,
        "tolong simpan laporan ini",
        address="sir",
    )

    assert delivery.display_text == raw
    assert delivery.speech_text.startswith("Maaf, sir. Tugas gagal:")
    assert "permission denied" in delivery.speech_text
    assert r"C:\Jarvis\reports\secret.txt" in delivery.factual_anchors
    assert "403" in delivery.factual_anchors


def test_success_delivery_membatasi_speech_sesuai_config(monkeypatch):
    # Batas kalimat honor config; di sini dipaksa 2 untuk determinisme.
    monkeypatch.setattr(interaction, "speech_sentence_limit", lambda: 2)
    raw = (
        "Laporan pertama telah selesai. "
        "Temuan kedua telah diverifikasi. "
        "Detail ketiga hanya untuk display."
    )

    delivery = interaction.success_delivery(raw, "tolong buat laporan", address="sir")

    assert delivery.display_text == raw
    assert "Laporan pertama telah selesai" in delivery.speech_text
    assert "Temuan kedua telah diverifikasi" in delivery.speech_text
    assert "Detail ketiga hanya untuk display" not in delivery.speech_text


def test_success_delivery_default_tidak_memotong_jawaban_natural():
    # Dengan default besar, jawaban multi-kalimat natural tidak terpotong.
    raw = (
        "Gambar sudah selesai saya buat. "
        "Nuansanya robot kucing biru futuristik dengan gadis sekolah. "
        "Silakan lihat hasilnya di panel."
    )
    delivery = interaction.success_delivery(raw, "buatkan gambar", address="sir")
    assert "robot kucing biru futuristik" in delivery.speech_text
    assert not delivery.speech_text.endswith("…")
