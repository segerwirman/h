"""Analisis kalori makanan dari frame kamera (permintaan user MK50).

Murni komputasi: JPEG bytes → vision LLM (provider aktif via
jarvis.agent.llm_client) → JSON ketat → ``FoodAnalysis``. Publikasi event/BUS
adalah urusan pemanggil (UI handler / tool agent), bukan modul ini.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from jarvis.core import log

_logger = log.get("vision.food")

_PROMPT = """Kamu ahli gizi. Analisis foto ini.

Jika TIDAK ada makanan/minuman di foto, kembalikan: {"is_food": false}

Jika ada, kembalikan JSON persis berbentuk:
{
  "is_food": true,
  "items": [
    {"name": "nama makanan (Indonesia)", "portion_g": 150,
     "calories_kcal": 250, "protein_g": 10, "carbs_g": 30, "fat_g": 8}
  ],
  "confidence": 0.8,
  "notes": "catatan singkat (metode masak, asumsi porsi)"
}

Aturan:
- Estimasi porsi dari ukuran visual relatif piring/tangan.
- Satu entri per jenis makanan yang terlihat.
- confidence 0..1 (turunkan bila porsi sulit diperkirakan).
- HANYA JSON. Tanpa teks lain, tanpa pagar kode."""


@dataclass
class FoodItem:
    name: str
    portion_g: float = 0.0
    calories_kcal: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0


@dataclass
class FoodAnalysis:
    is_food: bool = False
    items: list[FoodItem] = field(default_factory=list)
    confidence: float = 0.0
    notes: str = ""
    error: str | None = None

    @property
    def total_kcal(self) -> float:
        return round(sum(i.calories_kcal for i in self.items), 1)

    @property
    def total_protein(self) -> float:
        return round(sum(i.protein_g for i in self.items), 1)

    @property
    def total_carbs(self) -> float:
        return round(sum(i.carbs_g for i in self.items), 1)

    @property
    def total_fat(self) -> float:
        return round(sum(i.fat_g for i in self.items), 1)

    def summary_line(self) -> str:
        """Satu kalimat untuk TTS/log."""
        if self.error:
            return f"Analisis kalori gagal: {self.error}"
        if not self.is_food:
            return "Tidak terlihat makanan di kamera."
        names = ", ".join(i.name for i in self.items[:3])
        more = f" dan {len(self.items) - 3} lainnya" if len(self.items) > 3 \
            else ""
        return (f"Terdeteksi {names}{more} — total sekitar "
                f"{int(self.total_kcal)} kilokalori.")

    def detail_text(self) -> str:
        """Teks multi-baris untuk log/stage/Telegram."""
        if not self.is_food:
            return "Tidak ada makanan terdeteksi."
        lines = [f"• {i.name}: ~{int(i.portion_g)} g, "
                 f"{int(i.calories_kcal)} kkal "
                 f"(P{i.protein_g:g} K{i.carbs_g:g} L{i.fat_g:g})"
                 for i in self.items]
        lines.append(f"TOTAL ≈ {int(self.total_kcal)} kkal | protein "
                     f"{self.total_protein:g} g | karbo "
                     f"{self.total_carbs:g} g | lemak {self.total_fat:g} g")
        if self.notes:
            lines.append(f"Catatan: {self.notes}")
        return "\n".join(lines)


def _to_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_result(raw: str) -> FoodAnalysis:
    """Parse output model (defensif: pagar kode, teks nyasar, field hilang)."""
    if not raw or not raw.strip():
        return FoodAnalysis(error="model tidak menjawab")
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        text = text[start:end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return FoodAnalysis(error="jawaban model bukan JSON valid")
    if not isinstance(data, dict):
        return FoodAnalysis(error="bentuk JSON tidak dikenal")
    if not data.get("is_food"):
        return FoodAnalysis(is_food=False,
                            confidence=_to_float(data.get("confidence")))
    items = []
    for it in data.get("items") or []:
        if not isinstance(it, dict) or not it.get("name"):
            continue
        items.append(FoodItem(
            name=str(it["name"])[:60],
            portion_g=_to_float(it.get("portion_g")),
            calories_kcal=_to_float(it.get("calories_kcal")),
            protein_g=_to_float(it.get("protein_g")),
            carbs_g=_to_float(it.get("carbs_g")),
            fat_g=_to_float(it.get("fat_g"))))
    if not items:
        return FoodAnalysis(is_food=False,
                            confidence=_to_float(data.get("confidence")))
    return FoodAnalysis(
        is_food=True, items=items,
        confidence=max(0.0, min(1.0, _to_float(data.get("confidence"), 0.5))),
        notes=str(data.get("notes", ""))[:300])


def analyze_jpeg(jpeg_bytes: bytes, question: str = "") -> FoodAnalysis:
    """BLOCKING (panggil dari worker thread). Tidak pernah raise."""
    if not jpeg_bytes:
        return FoodAnalysis(error="frame kamera kosong")
    try:
        from jarvis.agent import llm_client
        cl = llm_client.vision_client()
        if not cl.available():
            return FoodAnalysis(
                error="vision provider belum dikonfigurasi — buka Settings")
        prompt = _PROMPT if not question else f"{_PROMPT}\n\nFokus user: " \
                                              f"{question}"
        raw = cl.vision(jpeg_bytes, "image/jpeg", prompt, json_mode=True)
        analysis = parse_result(raw)
        _logger.info("food.analyzed", is_food=analysis.is_food,
                     items=len(analysis.items),
                     kcal=analysis.total_kcal, error=analysis.error)
        return analysis
    except Exception as e:                                   # noqa: BLE001
        _logger.error("food.analyze_failed", error=str(e)[:150])
        return FoodAnalysis(error=str(e)[:150])
