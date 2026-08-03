"""Phase 2 Slice E routes voice messaging into native confirmation flow."""
from __future__ import annotations



def test_voice_schema_exposes_native_message_handoff_only():
    from jarvis.integrations import voice_native_tools

    names = {item["name"] for item in voice_native_tools.declarations()}

    assert "message_send" in names
    assert "send_message" not in names


def test_voice_message_handoff_is_native_owned():
    from jarvis.integrations import voice_native_tools

    assert "message_send" in voice_native_tools.native_tool_names()


def test_message_handoff_builds_native_task_without_exposing_message_text_in_error():
    from jarvis.integrations import voice_native_tools

    task = voice_native_tools.message_task({
        "platform": "whatsapp", "recipient": "Budi", "message": "rahasia test",
    })

    assert task == "Kirim pesan WhatsApp ke Budi: rahasia test"


def test_native_telegram_send_requires_confirmation_and_allowlisted_target():
    from jarvis.agent.tools.native_messaging import TelegramSendMessage

    tool = TelegramSendMessage()
    assert tool.needs_confirmation(chat_id="123", message="halo") is True
    assert "Telegram" in tool.confirmation_text(chat_id="123", message="halo")


def test_voice_rules_hold_direct_message_send_for_native_confirmation_flow():
    from jarvis.integrations import voice_native_tools

    rules = voice_native_tools.rules()

    assert "message_send" in rules
    assert "konfirmasi" in rules
    assert "send_message" in rules
