"""Deteksi interupsi suara yang adaptif terhadap kebisingan (Fase 19, S-4).

Dua permintaan Takeda adalah SATU pekerjaan: "bisa diinterupsi natural" dan
"tidak terlalu sensitif pada noise". Detektor lama di ``jarvis/ui/window.py``
adalah gerbang RMS ambang TETAP (0.14) — tanpa noise floor adaptif, tanpa
pembeda suara-vs-bunyi, dan dengan echo guard yang hanya menutup 400 ms
pertama. Menyalakannya apa adanya menghasilkan persis kepekaan yang ditolak;
itulah sebabnya ia dimatikan sejak awal.

Preseden dipakai ulang dari detektor tepuk (``jarvis/core/wake.py``, FROZEN —
dibaca sebagai contoh, tidak disentuh): kalibrasi awal + EMA noise floor,
crest factor, dan rasio spektral.

**Ambangnya dibalik, dan itu intinya.** Tepukan = transien pendek, crest
TINGGI, broadband. Suara manusia = berkelanjutan, crest RENDAH, energi
terkonsentrasi di pita suara. Primitif sama, keputusan berlawanan.

Modul ini murni: tidak membuka perangkat audio, tidak menyentuh UI, tidak
pernah melempar ke pemanggilnya. Ia hanya menilai satu blok sampel.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.core import config, log

_logger = log.get("voice.barge_in")

SENSITIVITIES = ("low", "medium", "high")

# Pengali ambang per tingkat kepekaan: makin peka, makin dekat ke noise floor.
_SENSITIVITY_MULTIPLIER = {"low": 6.0, "medium": 4.0, "high": 2.5}
# Sustain minimum per tingkat, dalam ms. Lebih peka = boleh lebih pendek.
_SENSITIVITY_MIN_MS = {"low": 600, "medium": 450, "high": 350}


@dataclass
class BargeInConfig:
    enabled: bool = False
    sensitivity: str = "medium"
    threshold_multiplier: float = 0.0     # 0 = ikut sensitivity
    min_ms: int = 0                       # 0 = ikut sensitivity
    cooldown_ms: int = 2000
    tts_grace_ms: int = 400
    calibration_s: float = 1.5
    noise_alpha: float = 0.05
    min_abs_rms: float = 0.02             # lantai mutlak; ruangan sunyi total
    echo_multiplier: float = 8.0          # kenaikan ambang saat Jarvis bicara
    max_crest: float = 6.0                # di atas ini = transien, bukan ucapan
    min_voice_band_ratio: float = 0.55    # energi < 1 kHz terhadap total
    sample_rate: int = 16000

    def __post_init__(self) -> None:
        if self.sensitivity not in SENSITIVITIES:
            self.sensitivity = "medium"
        if not self.threshold_multiplier:
            self.threshold_multiplier = _SENSITIVITY_MULTIPLIER[self.sensitivity]
        if not self.min_ms:
            self.min_ms = _SENSITIVITY_MIN_MS[self.sensitivity]

    @classmethod
    def from_config(cls) -> "BargeInConfig":
        try:
            section = config.section("voice.barge_in") or {}
        except Exception:                                    # noqa: BLE001
            section = {}

        def _num(key, default, cast):
            try:
                return cast(section.get(key, default))
            except (TypeError, ValueError):
                return default

        return cls(
            enabled=bool(section.get("enabled", False)),
            sensitivity=str(section.get("sensitivity", "medium") or "medium"),
            threshold_multiplier=_num("threshold_multiplier", 0.0, float),
            min_ms=_num("min_ms", 0, int),
            cooldown_ms=_num("cooldown_ms", 2000, int),
            tts_grace_ms=_num("tts_grace_ms", 400, int),
            calibration_s=_num("calibration_seconds", 1.5, float),
            noise_alpha=_num("noise_alpha", 0.05, float),
            min_abs_rms=_num("min_abs_rms", 0.02, float),
            echo_multiplier=_num("echo_multiplier", 8.0, float),
            max_crest=_num("max_crest", 6.0, float),
            min_voice_band_ratio=_num("min_voice_band_ratio", 0.55, float),
        )


@dataclass(frozen=True)
class BargeInVerdict:
    interrupt: bool
    reason: str
    rms: float = 0.0
    noise_floor: float = 0.0
    threshold: float = 0.0


@dataclass
class BargeInAnalyzer:
    cfg: BargeInConfig = field(default_factory=BargeInConfig)
    noise_floor: float = 0.01
    sustained_s: float = 0.0
    _calibrating_until: float | None = None
    _calib: list = field(default_factory=list)
    _cooldown_until: float = 0.0
    _last_block_at: float = 0.0

    def start_calibration(self, now: float) -> None:
        self._calibrating_until = now + max(0.1, self.cfg.calibration_s)
        self._calib = []

    def threshold(self, playback_level: float = 0.0) -> float:
        """Ambang RMS saat ini — relatif terhadap kebisingan ruangan.

        Naik sebanding dengan seberapa keras Jarvis sedang berbunyi, sepanjang
        ucapan, bukan hanya di 400 ms pertama.
        """
        base = max(self.noise_floor * self.cfg.threshold_multiplier,
                   self.cfg.min_abs_rms)
        level = max(0.0, min(1.0, float(playback_level or 0.0)))
        return base * (1.0 + level * (self.cfg.echo_multiplier - 1.0))

    def process_block(self, samples, now: float, *, speaking: bool = False,
                      speaking_since: float = 0.0,
                      playback_level: float = 0.0) -> BargeInVerdict:
        """Nilai satu blok. Tidak pernah melempar — jalur audio harus hidup."""
        try:
            return self._process(samples, now, speaking, speaking_since,
                                 playback_level)
        except Exception as exc:                             # noqa: BLE001
            _logger.warning("barge_in.block_failed", error=str(exc)[:120])
            return BargeInVerdict(False, "error")

    # ── internal ─────────────────────────────────────────────────────────
    def _process(self, samples, now, speaking, speaking_since,
                 playback_level) -> BargeInVerdict:
        import numpy as np

        if samples is None:
            return BargeInVerdict(False, "empty")
        x = np.asarray(samples, dtype=np.float32)
        if x.size == 0:
            return BargeInVerdict(False, "empty")
        if x.dtype.kind in "iu" or float(np.max(np.abs(x))) > 1.5:
            x = x / 32768.0
        dt = max(0.0, min(0.5, now - self._last_block_at)) \
            if self._last_block_at else x.size / self.cfg.sample_rate
        self._last_block_at = now

        rms = float(np.sqrt(np.mean(np.square(x))))
        peak = float(np.max(np.abs(x)))

        # Kalibrasi awal: hanya kumpulkan level ambient.
        if self._calibrating_until is not None:
            if now < self._calibrating_until:
                self._calib.append(rms)
                return BargeInVerdict(False, "calibrating", rms)
            base = (sorted(self._calib)[len(self._calib) // 2]
                    if self._calib else 0.01)
            self.noise_floor = max(base, 1e-4)
            self._calibrating_until = None
            _logger.info("barge_in.calibrated",
                         noise_floor=round(self.noise_floor, 4))

        if not self.cfg.enabled:
            return BargeInVerdict(False, "disabled", rms, self.noise_floor)
        if not speaking:
            # Hanya relevan saat Jarvis bicara; selain itu blok ini justru
            # bahan belajar noise floor.
            self._learn(rms)
            self.sustained_s = 0.0
            return BargeInVerdict(False, "not_speaking", rms, self.noise_floor)
        if now < self._cooldown_until:
            return BargeInVerdict(False, "cooldown", rms, self.noise_floor)
        if speaking_since and (now - speaking_since) * 1000.0 < self.cfg.tts_grace_ms:
            self.sustained_s = 0.0
            return BargeInVerdict(False, "tts_onset", rms, self.noise_floor)

        threshold = self.threshold(playback_level)
        if rms < threshold:
            self._learn(rms)
            self.sustained_s = 0.0
            return BargeInVerdict(False, "below_threshold", rms,
                                  self.noise_floor, threshold)

        # Transien (tepukan, pintu, ketukan) punya crest tinggi. Ucapan tidak.
        crest = peak / (rms + 1e-9)
        if crest > self.cfg.max_crest:
            self.sustained_s = 0.0
            return BargeInVerdict(False, f"transient crest={crest:.1f}", rms,
                                  self.noise_floor, threshold)

        # Ucapan memusatkan energi di bawah ~1 kHz; desis broadband tidak.
        mag = np.abs(np.fft.rfft(x))
        total = float(np.sum(mag)) + 1e-9
        cut = max(1, int(1000 * x.size / self.cfg.sample_rate))
        voice_ratio = float(np.sum(mag[:cut])) / total
        if voice_ratio < self.cfg.min_voice_band_ratio:
            self.sustained_s = 0.0
            return BargeInVerdict(False, f"broadband ratio={voice_ratio:.2f}",
                                  rms, self.noise_floor, threshold)

        # Harus BERTURUT-TURUT: satu blok keras bukan interupsi, dan jeda
        # mengembalikan hitungan ke nol.
        self.sustained_s += dt
        if self.sustained_s * 1000.0 < self.cfg.min_ms:
            return BargeInVerdict(False, "sustaining", rms, self.noise_floor,
                                  threshold)

        self.sustained_s = 0.0
        self._cooldown_until = now + self.cfg.cooldown_ms / 1000.0
        _logger.info("barge_in.triggered", rms=round(rms, 3),
                     threshold=round(threshold, 3))
        return BargeInVerdict(True, "speech", rms, self.noise_floor, threshold)

    def _learn(self, rms: float) -> None:
        a = max(0.0, min(1.0, self.cfg.noise_alpha))
        self.noise_floor = (1 - a) * self.noise_floor + a * max(rms, 1e-4)


__all__ = ["BargeInAnalyzer", "BargeInConfig", "BargeInVerdict",
           "SENSITIVITIES"]
