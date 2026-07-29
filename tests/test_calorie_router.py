"""Router — pola kalori MK50 masuk SYSTEM/calorie_analyze, tanpa salah rute."""
from __future__ import annotations

from jarvis.core.router import Intent, IntentRouter


def _rules(text: str):
    return IntentRouter()._rules(text)


def test_calorie_phrases_route_to_system():
    for text in ("berapa kalori makanan ini",
                 "analisis kalori",
                 "hitung kalori makanan di depanku",
                 "cek gizi makanan ini",
                 "scan makanan",
                 "how many calories is this",
                 "analyze food please",
                 "kalori makanannya berapa"):
        c = _rules(text)
        assert c is not None, text
        assert c.intent is Intent.SYSTEM, text
        assert c.slots.get("action") == "calorie_analyze", text


def test_non_calorie_not_hijacked():
    c = _rules("buka kamera")
    assert c.slots.get("action") == "vision_open"
    c = _rules("matikan wifi")
    assert c.slots.get("action") == "wifi_off"
    c = _rules("apa kabar")
    assert c.intent is Intent.CHAT
