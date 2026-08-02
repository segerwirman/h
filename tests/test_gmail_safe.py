"""Fase 16B: privacy-tiered Gmail summary untuk konsumsi remote/voice/desktop."""
from __future__ import annotations


def test_summarize_masks_sender_and_keeps_subject_time():
    from jarvis.integrations.gmail_summary import summarize_unread

    messages = [
        {"from": "Budi Santoso <budi.santoso@example.com>",
         "subject": "Rapat besok", "date": "2026-07-31T09:20:00"},
        {"from": "noreply@bank.example.com",
         "subject": "Info saldo", "date": "2026-07-31T08:05:00"},
    ]
    out = summarize_unread(messages, tier="default")

    assert out["unread_count"] == 2
    items = out["items"]
    # sender masked: local part truncated, domain kept
    assert "budi.santoso" not in str(items)
    assert "example.com" in str(items[0]["sender"])
    assert items[0]["subject"] == "Rapat besok"
    assert items[0]["time"]


def test_summarize_redacts_otp_and_payment_and_password_reset():
    from jarvis.integrations.gmail_summary import summarize_unread

    messages = [
        {"from": "security@x.com", "subject": "Your OTP code is 123456", "date": "t"},
        {"from": "noreply@bank.com", "subject": "Password reset request", "date": "t"},
        {"from": "billing@shop.com", "subject": "Payment of $500 confirmed", "date": "t"},
    ]
    out = summarize_unread(messages, tier="default")

    blob = str(out)
    assert "123456" not in blob
    for item in out["items"]:
        assert item["sensitive"] is True
        assert item["subject"] == "[disensor: pesan sensitif]"


def test_count_only_tier_returns_no_subjects_or_senders():
    from jarvis.integrations.gmail_summary import summarize_unread

    messages = [{"from": "a@b.com", "subject": "hi", "date": "t"}]
    out = summarize_unread(messages, tier="count_only")

    assert out["unread_count"] == 1
    assert out["items"] == []


def test_body_summary_only_when_explicitly_requested():
    from jarvis.integrations.gmail_summary import summarize_body

    body = "Halo, ini isi email panjang sekali " * 50
    # not requested -> refused
    assert summarize_body(body, allow_body=False) == ""
    # requested -> capped, no attachment auto
    out = summarize_body(body, allow_body=True, max_chars=200)
    assert 0 < len(out) <= 200


def test_body_summary_redacts_sensitive_even_when_requested():
    from jarvis.integrations.gmail_summary import summarize_body

    body = "Kode OTP Anda adalah 987654 jangan dibagikan"
    out = summarize_body(body, allow_body=True, sensitive=True)

    assert out == "[disensor: konten sensitif tidak dibacakan]"
    assert "987654" not in out


def test_tts_text_is_distinct_from_display_and_bounded():
    from jarvis.integrations.gmail_summary import summarize_unread, briefing_text

    messages = [
        {"from": "a@x.com", "subject": "Rapat", "date": "t"},
        {"from": "b@y.com", "subject": "Laporan", "date": "t"},
        {"from": "sec@z.com", "subject": "OTP 111222", "date": "t"},
    ]
    out = summarize_unread(messages, tier="default")
    speech = briefing_text(out)

    assert "111222" not in speech
    assert "3" in speech  # count spoken
    # speech is a short brief, not a raw dump
    assert len(speech) <= 400


def test_attachment_metadata_never_auto_delivered():
    from jarvis.integrations.gmail_summary import summarize_unread

    messages = [{"from": "a@b.com", "subject": "file", "date": "t",
                 "attachments": ["secret.pdf"]}]
    out = summarize_unread(messages, tier="default")

    assert "secret.pdf" not in str(out)
    assert "attachments" not in out["items"][0]
