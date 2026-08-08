"""Sidik suara lokal — mengenali penuturnya (Fase 30).

Permintaan Takeda: *"saya ingin jarvis bisa mengenali suara saya seperti siri
dan hanya merespon suara saya ketika pertama kali booting."*

**Batas jujur, di muka.** Tidak ada model speaker di repo, dan
ECAPA/Resemblyzer berarti unduhan puluhan MB — keputusan Takeda, bukan
keputusan kode. Yang ada di sini adalah sidik spektral memakai numpy saja:
selubung rata-rata dan sebarannya di 32 pita mel, dinormalisasi terhadap
kekerasan suara. Ia memisahkan dua suara yang jelas berbeda pada mikrofon dan
ruangan yang sama. Ia **bukan** pengenal suara neural dan tidak berlagak
begitu. Antarmukanya sengaja sempit — ``fingerprint`` dan ``similarity`` —
supaya model neural bisa menggantikannya tanpa menyentuh satu pun pemanggil.

**Gerbangnya MATI sampai Takeda menyalakannya.** Verifikasi yang keliru
membuat Jarvis TULI terhadap pemiliknya sendiri, dan itu jauh lebih buruk
daripada menjawab orang lain sesekali. Default modul ini adalah *mengamati*:
skor tiap ucapan dihitung dan dicatat, tanpa menolak apa pun. Ambangnya lahir
dari suara Takeda di mikrofon Takeda — S-25 sudah mengajarkan dengan mahal apa
yang terjadi ketika ambang lahir dari nada sintetis: 262 blok suara sungguhan
ditolak oleh angka yang terdengar masuk akal di atas kertas.

Dan ketika kelak menolak, penolakannya **terlihat**. Perintah yang diabaikan
diam-diam adalah kelas bug yang tujuh fase dihabiskan untuk memberantasnya.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass

import numpy as np

from jarvis.core import config, log

_logger = log.get("core.speaker_id")
_lock = threading.Lock()

#: 32 pita mel × (rata-rata, sebaran) — cukup memisahkan penutur, cukup kecil
#: untuk stabil dari satu ucapan pendek.
BANDS = 32
DIM = BANDS * 2

MIN_SAMPLES = 3
MIN_SECONDS = 0.35
#: Di bawah ini blok dianggap sunyi: tidak ada suara siapa pun untuk disidik.
MIN_RMS = 0.01

#: Cadangan terakhir bila profil tidak membawa kalibrasi. SENGAJA tidak
#: dipakai sebagai angka utama: diukur pada suara sintetis, 2 dari 3 "penutur
#: lain" justru LOLOS ambang tetap (0.903 dan 0.860), sementara take pemilik
#: semuanya 1.000. Angka tetap apa pun yang lahir dari data sebersih itu
#: adalah tebakan yang berpakaian pengukuran — S-25 persis.
DEFAULT_THRESHOLD = 0.82
#: Jarak aman di bawah take pemilik yang PALING buruk saat pendaftaran.
DEFAULT_MARGIN = 0.04

#: Satu ucapan dipotong di sini. Orang yang bicara panjang tidak boleh
#: memakan memori, dan bagian awal sudah cukup untuk mengenalinya.
MAX_UTTERANCE_SECONDS = 4.0
#: Sekian blok sunyi berturut-turut menutup ucapan. Tanpa ini, buffer akan
#: mencampur dua penutur yang berbicara bergantian menjadi satu sidik.
SILENCE_BLOCKS_TO_CLOSE = 8

_cached: dict | None = None


# ── sidik suara ───────────────────────────────────────────────────────────

def _mel_edges(sample_rate: int, bands: int) -> np.ndarray:
    def to_mel(hz):
        return 2595.0 * np.log10(1.0 + hz / 700.0)

    def to_hz(mel):
        return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

    low, high = to_mel(80.0), to_mel(min(7600.0, sample_rate / 2 - 1))
    return to_hz(np.linspace(low, high, bands + 1))


def fingerprint(audio, sample_rate: int = 16_000) -> list[float]:
    """Sidik suara ternormalisasi. ``[]`` bila audionya tidak bisa dipakai."""
    try:
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        if samples.size < int(sample_rate * MIN_SECONDS):
            return []
        if float(np.sqrt(np.mean(np.square(samples)))) < MIN_RMS:
            return []

        window = 512
        hop = 256
        count = 1 + (samples.size - window) // hop
        if count < 4:
            return []
        frames = np.lib.stride_tricks.as_strided(
            samples, shape=(count, window),
            strides=(samples.strides[0] * hop, samples.strides[0]))
        spectrum = np.abs(np.fft.rfft(frames * np.hanning(window), axis=1))

        freqs = np.fft.rfftfreq(window, 1.0 / sample_rate)
        edges = _mel_edges(sample_rate, BANDS)
        energies = np.zeros((count, BANDS), dtype=np.float64)
        for band in range(BANDS):
            mask = (freqs >= edges[band]) & (freqs < edges[band + 1])
            if mask.any():
                energies[:, band] = spectrum[:, mask].mean(axis=1)

        # Log lalu kurangi rata-ratanya per frame: bicara lebih keras tidak
        # boleh membuat seseorang menjadi orang lain.
        energies = np.log(energies + 1e-8)
        energies -= energies.mean(axis=1, keepdims=True)

        vector = np.concatenate([energies.mean(axis=0), energies.std(axis=0)])
        norm = float(np.linalg.norm(vector))
        if not np.isfinite(norm) or norm <= 0.0:
            return []
        return [float(value) for value in (vector / norm)]
    except Exception:                                        # noqa: BLE001
        return []


def similarity(first, second) -> float:
    """Cosine 0..1. Sidik kosong selalu 0.0, bukan 1.0."""
    try:
        if not len(first) or not len(second) or len(first) != len(second):
            return 0.0
        score = float(np.dot(np.asarray(first, dtype=np.float64),
                             np.asarray(second, dtype=np.float64)))
        return max(0.0, min(1.0, score))
    except Exception:                                        # noqa: BLE001
        return 0.0


# ── profil pemilik ────────────────────────────────────────────────────────

def _profile_path():
    from jarvis.agent.paths import data_dir

    return data_dir() / "speaker_profile.json"


def _load() -> dict | None:
    global _cached
    if _cached is not None:
        return _cached
    try:
        path = _profile_path()
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        vectors = data.get("vectors")
        if not isinstance(vectors, list) or not vectors:
            return None
        _cached = data
        return _cached
    except Exception:                                        # noqa: BLE001
        # Profil rusak diperlakukan sebagai BELUM terdaftar, bukan sebagai
        # penolakan — kalau tidak, satu berkas cacat membuat Jarvis tuli.
        _logger.warning("speaker_id.profile_unreadable")
        return None


def enrolled() -> bool:
    return _load() is not None


def _calibrate(vectors: list[list[float]]) -> float:
    """Ambang dari sebaran suara PEMILIK sendiri, bukan dari angka bawaan.

    Tiap take dibandingkan dengan take lainnya (leave-one-out); yang paling
    buruk di antaranya adalah seberapa jauh suara Takeda bisa menyimpang dari
    dirinya sendiri pada mikrofon itu, di ruangan itu. Ambangnya ditaruh
    sedikit di bawah itu.

    Inilah pelajaran S-25 yang diterapkan: ambang 0.55 dulu lahir dari nada
    empat harmonik dan menolak 262 blok suara Takeda yang sungguhan.
    """
    worst = 1.0
    for index, vector in enumerate(vectors):
        others = [other for position, other in enumerate(vectors)
                  if position != index]
        if not others:
            continue
        worst = min(worst, max(similarity(vector, other) for other in others))
    margin = DEFAULT_MARGIN
    try:
        margin = float(config.get("voice.speaker_id.margin", DEFAULT_MARGIN))
    except (TypeError, ValueError):
        pass
    return round(max(0.5, min(0.99, worst - margin)), 4)


def threshold() -> float:
    """Ambang terkalibrasi milik profil ini; setelan eksplisit tetap menang."""
    try:
        configured = config.get("voice.speaker_id.threshold", None)
        if configured is not None:
            return float(configured)
    except (TypeError, ValueError):
        pass
    profile = _load()
    if profile is not None:
        try:
            value = float(profile.get("threshold", 0.0))
            if value > 0.0:
                return value
        except (TypeError, ValueError):
            pass
    return DEFAULT_THRESHOLD


def gating_enabled() -> bool:
    """Menolak suara asing? Default **False** dengan sengaja.

    Fase 30 mengamati dulu; Takeda yang menyalakannya setelah melihat angka
    dari suaranya sendiri di mikrofonnya sendiri.
    """
    try:
        return bool(config.get("voice.speaker_id.gate", False))
    except Exception:                                        # noqa: BLE001
        return False


def enroll(samples, sample_rate: int = 16_000) -> bool:
    """Daftarkan pemiliknya dari beberapa potong suara. ``False`` bila kurang."""
    global _cached
    try:
        vectors = []
        for sample in (samples or []):
            vector = fingerprint(sample, sample_rate)
            if vector:
                vectors.append(vector)
        if len(vectors) < MIN_SAMPLES:
            _logger.info("speaker_id.enroll_insufficient", usable=len(vectors),
                         needed=MIN_SAMPLES)
            return False
        data = {"version": 1, "sample_rate": int(sample_rate),
                "vectors": vectors, "threshold": _calibrate(vectors)}
        with _lock:
            path = _profile_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
            _cached = data
        _logger.info("speaker_id.enrolled", samples=len(vectors),
                     threshold=data["threshold"])
        return True
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("speaker_id.enroll_failed", error=str(exc)[:120])
        return False


def forget() -> None:
    global _cached
    try:
        with _lock:
            path = _profile_path()
            if path.exists():
                path.unlink()
            _cached = None
    except Exception:                                        # noqa: BLE001
        _cached = None


@dataclass(frozen=True)
class SpeakerVerdict:
    status: str            # match | stranger | unusable | not_enrolled
    score: float
    threshold: float
    blocked: bool


def diagnostics() -> dict:
    """Angka mentah untuk Takeda — sunyi bukan bukti (§22)."""
    profile = _load()
    return {"enrolled": profile is not None,
            "samples": len(profile.get("vectors", [])) if profile else 0,
            "threshold": threshold(),
            "gating": gating_enabled()}


def verify(audio, sample_rate: int = 16_000) -> SpeakerVerdict:
    """Nilai satu ucapan. Tidak pernah melempar, dan jarang menolak."""
    limit = threshold()
    profile = _load()
    if profile is None:
        return SpeakerVerdict("not_enrolled", 0.0, limit, False)

    vector = fingerprint(audio, sample_rate)
    if not vector:
        # Audio yang tidak bisa dinilai BUKAN bukti bahwa itu orang lain.
        # Menolaknya berarti Jarvis membisu setiap kali mikrofonnya buruk.
        return SpeakerVerdict("unusable", 0.0, limit, False)

    score = max((similarity(vector, known)
                 for known in profile.get("vectors", [])), default=0.0)
    if score >= limit:
        _logger.info("speaker_id.match", score=round(score, 3),
                     threshold=round(limit, 3))
        return SpeakerVerdict("match", score, limit, False)

    gate = gating_enabled()
    if gate:
        # Penolakan HARUS terlihat. Perintah yang diabaikan diam-diam adalah
        # kelas bug yang tujuh fase dihabiskan untuk memberantasnya.
        _logger.info("speaker_id.blocked", score=round(score, 3),
                     threshold=round(limit, 3))
    else:
        _logger.info("speaker_id.observed", score=round(score, 3),
                     threshold=round(limit, 3), would_block=True)
    return SpeakerVerdict("stranger", score, limit, gate)


class Listener:
    """Kumpulkan satu ucapan dari blok mic, lalu nilai penuturnya (§30).

    ``MainWindow._mic_meter`` menyuapkan blok 1024 sampel pada 16 kHz — 64 ms,
    jauh terlalu pendek untuk mengenali siapa pun. Kelas ini menyatukannya
    sampai satu ucapan utuh, menutupnya saat sunyi, lalu menilai sekali.

    Selama pemilik belum terdaftar, ucapan pertama justru dipakai MENDAFTAR —
    itulah "ketika pertama kali booting" dalam permintaan Takeda. Karena
    gerbangnya mati secara default, profil yang keliru tidak menutup apa pun;
    ia hanya membuat pengamatannya salah, dan ``forget()`` mengulanginya.
    """

    def __init__(self, sample_rate: int = 16_000) -> None:
        self.sample_rate = int(sample_rate or 16_000)
        self._buffer: list = []
        self._samples = 0
        self._silence = 0
        self._enrolment: list = []

    def buffered_seconds(self) -> float:
        return round(self._samples / float(self.sample_rate), 4)

    def _reset(self) -> None:
        self._buffer.clear()
        self._samples = 0
        self._silence = 0

    def feed(self, block, *, listening: bool):
        """Satu blok mic. Mengembalikan vonis hanya saat ucapan selesai."""
        try:
            if not listening:
                if self._samples:
                    self._reset()
                return None
            samples = np.asarray(block, dtype=np.float32).reshape(-1)
            if samples.size == 0:
                return None

            loud = float(np.sqrt(np.mean(np.square(samples)))) >= MIN_RMS
            if not loud:
                if self._samples:
                    self._silence += 1
                    if self._silence >= SILENCE_BLOCKS_TO_CLOSE:
                        verdict = self._close()
                        return verdict
                return None

            self._silence = 0
            self._buffer.append(samples)
            self._samples += samples.size
            if self._samples >= int(self.sample_rate * MAX_UTTERANCE_SECONDS):
                return self._close()
            return None
        except Exception:                                    # noqa: BLE001
            self._reset()
            return None

    def _close(self):
        try:
            if self._samples < int(self.sample_rate * MIN_SECONDS):
                self._reset()
                return None
            audio = np.concatenate(self._buffer)
            self._reset()

            if not enrolled():
                vector = fingerprint(audio, self.sample_rate)
                if vector:
                    self._enrolment.append(audio)
                if len(self._enrolment) >= MIN_SAMPLES:
                    enroll(self._enrolment, self.sample_rate)
                    self._enrolment = []
                return None
            return verify(audio, self.sample_rate)
        except Exception:                                    # noqa: BLE001
            self._reset()
            return None


__all__ = ["BANDS", "DEFAULT_MARGIN", "DEFAULT_THRESHOLD", "DIM",
           "Listener", "MAX_UTTERANCE_SECONDS", "MIN_SAMPLES", "diagnostics", "SpeakerVerdict",
           "enroll", "enrolled", "fingerprint", "forget", "gating_enabled",
           "similarity", "threshold", "verify"]
