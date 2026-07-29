"""Analisis kalori — parser defensif + totals + jalur analyze_jpeg palsu."""
from __future__ import annotations

import jarvis.vision.food_calories as fc


def test_parse_clean_json():
    raw = ('{"is_food": true, "items": [{"name": "nasi goreng", '
           '"portion_g": 300, "calories_kcal": 520, "protein_g": 14, '
           '"carbs_g": 68, "fat_g": 20}], "confidence": 0.82, '
           '"notes": "porsi piring penuh"}')
    a = fc.parse_result(raw)
    assert a.is_food and not a.error
    assert a.items[0].name == "nasi goreng"
    assert a.total_kcal == 520
    assert a.confidence == 0.82
    assert "520" in a.detail_text()
    assert "nasi goreng" in a.summary_line()


def test_parse_fenced_and_noisy():
    raw = ("Tentu! Ini hasilnya:\n```json\n"
           '{"is_food": true, "items": ['
           '{"name": "telur", "calories_kcal": 78},'
           '{"name": "roti", "calories_kcal": 160}], "confidence": 0.6}'
           "\n```\nSemoga membantu!")
    a = fc.parse_result(raw)
    assert a.is_food
    assert len(a.items) == 2
    assert a.total_kcal == 238


def test_parse_not_food():
    a = fc.parse_result('{"is_food": false}')
    assert not a.is_food and not a.error
    assert "Tidak" in a.summary_line()


def test_parse_garbage():
    a = fc.parse_result("model bingung dan tidak menjawab json")
    assert a.error
    assert "gagal" in a.summary_line().lower()


def test_parse_missing_numbers_default_zero():
    a = fc.parse_result('{"is_food": true, "items": [{"name": "air"}]}')
    assert a.is_food
    assert a.total_kcal == 0


def test_analyze_jpeg_without_provider(monkeypatch):
    class Dead:
        def available(self):
            return False

    import jarvis.agent.llm_client as lc
    monkeypatch.setattr(lc, "vision_client", lambda: Dead())
    a = fc.analyze_jpeg(b"\xff\xd8fakejpeg")
    assert a.error and "Settings" in a.error


def test_analyze_jpeg_happy_path(monkeypatch):
    class Fake:
        def available(self):
            return True

        def vision(self, data, mime, prompt, json_mode=False):
            assert mime == "image/jpeg"
            return ('{"is_food": true, "items": [{"name": "apel", '
                    '"portion_g": 120, "calories_kcal": 62}], '
                    '"confidence": 0.9}')

    import jarvis.agent.llm_client as lc
    monkeypatch.setattr(lc, "vision_client", lambda: Fake())
    a = fc.analyze_jpeg(b"\xff\xd8fakejpeg")
    assert a.is_food and a.total_kcal == 62
    assert a.items[0].name == "apel"


def test_analyze_empty_frame():
    a = fc.analyze_jpeg(b"")
    assert a.error
