"""A51c: remote read renderer must redact sensitive values, not just keys.

Regression: render_remote_read only filtered forbidden keys; sensitive values
under allowed fields (briefing/sender/subject/title) were echoed verbatim.
"""
from jarvis.agent.remote_read_policy import render_remote_read


def _render(payload, **kwargs):
    return render_remote_read(payload, chat_id="1", expected_chat_id="1", **kwargs)


def test_briefing_with_access_token_is_redacted():
    result = _render({"briefing": "access token: TOPSECRET123"})
    assert result["ok"] is True
    assert "TOPSECRET123" not in result["content"]
    assert "[REDACTED]" in result["content"]


def test_subject_with_api_key_is_redacted():
    payload = {
        "unread_count": 1,
        "items": [{
            "sender": "admin@corp.local", "subject": "rotasi api key: sk-live-abc",
            "time": "10:00", "sensitive": False,
        }],
    }
    result = _render(payload)
    assert result["ok"] is True
    assert "sk-live-abc" not in result["content"]
    assert "[REDACTED]" in result["content"]


def test_path_like_briefing_is_redacted():
    result = _render({"briefing": "lihat file di C:\\Users\\me\\keys\\prod.txt"})
    assert result["ok"] is True
    assert "prod.txt" not in result["content"]
    assert "[REDACTED]" in result["content"]


def test_agenda_title_with_secret_word_is_redacted():
    payload = {"count": 1, "items": [{"time": "09:00", "title": "reset password"}]}
    result = _render(payload)
    assert result["ok"] is True
    assert "password" not in result["content"]
    assert "[REDACTED]" in result["content"]


def test_unc_path_briefing_is_redacted():
    result = _render({"briefing": r"lihat \\nas01\backup\keys\prod.txt"})
    assert result["ok"] is True
    assert "prod.txt" not in result["content"]
    assert "[REDACTED]" in result["content"]


def test_normal_briefing_passes_through_unmodified():
    result = _render({"briefing": "Rapat mingguan jam 10 di ruang rapat"})
    assert result["ok"] is True
    assert "Rapat mingguan jam 10 di ruang rapat" in result["content"]
