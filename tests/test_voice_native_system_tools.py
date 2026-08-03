"""Phase 2 Slice D keeps voice weather/reminder/system calls native."""
from __future__ import annotations


def test_native_reminder_and_wifi_actions_require_confirmation():
    from jarvis.agent.tools.native_voice_system import ReminderCreate, SystemReflex

    assert ReminderCreate().needs_confirmation(
        date="2030-01-01", time="09:00", message="Tes"
    ) is True
    assert SystemReflex().needs_confirmation(action="wifi_off") is True
    assert SystemReflex().needs_confirmation(action="volume_up") is False
