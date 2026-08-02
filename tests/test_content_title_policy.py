"""Phase 19 — Intent-specific bounded title setter (Judul Project only). GREEN"""
from __future__ import annotations

def test_content_title_policy_rejects_empty_and_non_string():
    from jarvis.core.content_title_policy import admit_title
    for bad in ("", "   ", None, 123, False):
        res = admit_title(bad)
        assert res["ok"] is False

def test_title_policy_rejects_oversize():
    from jarvis.core.content_title_policy import admit_title
    long_title = "x" * 201
    res = admit_title(long_title)
    assert res["ok"] is False
    assert any(k in res["reason"] for k in ("length", "oversize", "bound", "rejected"))

def test_title_policy_rejects_password_otp_payment_url_terminal():
    from jarvis.core.content_title_policy import admit_title
    deny_cases = [
        "password: 1234",
        "OTP 123456",
        "credit card 4111",
        "https://evil.com/steal",
        "rm -rf /",
        "send email to bos@co.id",
        "payment checkout",
        "sign in google",
    ]
    for txt in deny_cases:
        res = admit_title(txt)
        assert res["ok"] is False, f"should reject: {txt}"

def test_title_policy_accepts_normal_title_and_trims():
    from jarvis.core.content_title_policy import admit_title
    res = admit_title("  Peluncuran Musim Panas  ")
    assert res["ok"] is True
    assert res["title"] == "Peluncuran Musim Panas"
    assert res["intent"] == "content_studio_title"

def test_title_policy_has_no_network_or_path_authority():
    from pathlib import Path
    import jarvis.core.content_title_policy as mod
    src = Path(mod.__file__).read_text(encoding="utf-8").lower()
    for forbidden in ("webbrowser", "requests", "subprocess", "upload", "telegram", "open_url", "pyautogui", "desktop"):
        assert forbidden not in src

def test_title_policy_max_len_constant():
    from jarvis.core import content_title_policy
    assert content_title_policy.MAX_LEN == 120

def test_title_policy_return_shape_is_safe():
    from jarvis.core.content_title_policy import admit_title
    ok = admit_title("Kampanye Lokal")
    assert set(ok.keys()) == {"ok", "title", "intent"}
    fail = admit_title("")
    assert set(fail.keys()) == {"ok", "reason"}
    # never returns raw input path/secret
    assert "E:" not in str(fail)
    assert "token" not in str(fail).lower()
