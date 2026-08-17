"""DeviceCapabilityResolver — pick the best available inference backend (§16).

Probes each optional accelerator (CUDA/TensorRT via torch, ONNX Runtime GPU
providers, DirectML) behind guarded imports and returns the first backend in
the configured ``vision.yolo.backend_preference`` that is actually usable,
falling back to CPU. Every probe is isolated: a missing or broken optional
provider degrades to "unavailable", never raises into startup (§16 rule:
"never crash startup because an optional GPU provider is unavailable").

Pure detection logic with injectable probes, so backend selection and the
whole fallback chain are unit-testable with mocks and no real GPU.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.core import config, log, quiet

_logger = log.get("vision.device_caps")

_DEFAULT_PREFERENCE = ["tensorrt", "cuda", "directml", "onnxruntime_gpu", "cpu"]


@dataclass
class DeviceCapabilities:
    backend: str = "cpu"                    # selected backend
    device: str = "cpu"                     # torch device or provider label
    device_name: str = "CPU"
    compute_capability: str = ""
    vram_mb: int | None = None
    half_precision: bool = False
    tensorrt: bool = False
    cuda: bool = False
    onnx_gpu: bool = False
    directml: bool = False
    fallback_reason: str = ""
    available_backends: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"backend={self.backend}", f"device={self.device_name}"]
        if self.vram_mb:
            parts.append(f"vram={self.vram_mb}MB")
        if self.half_precision:
            parts.append("fp16")
        if self.fallback_reason:
            parts.append(f"fallback={self.fallback_reason}")
        return " ".join(parts)


# ── individual probes (each returns dict|None; never raises) ──────────────

def _probe_cuda() -> dict | None:
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        idx = 0
        props = torch.cuda.get_device_properties(idx)
        cc = f"{props.major}.{props.minor}"
        return {"device": f"cuda:{idx}", "device_name": props.name,
                "compute_capability": cc,
                "vram_mb": int(props.total_memory / (1024 * 1024)),
                "half_precision": props.major >= 6}
    except Exception as e:
        _logger.debug("device.cuda_probe_failed", error=str(e)[:80])
        return None


def _probe_tensorrt() -> dict | None:
    try:
        import tensorrt  # noqa: F401
    except Exception:
        return None
    cuda = _probe_cuda()
    if cuda is None:
        return None
    return {**cuda, "device": "tensorrt"}


def _probe_onnx_gpu() -> dict | None:
    try:
        import onnxruntime as ort
        providers = ort.get_available_providers()
        for p in ("CUDAExecutionProvider", "TensorrtExecutionProvider"):
            if p in providers:
                return {"device": p, "device_name": p, "half_precision": True}
    except Exception:
        return None
    return None


def _probe_directml() -> dict | None:
    try:
        import onnxruntime as ort
        if "DmlExecutionProvider" in ort.get_available_providers():
            return {"device": "DmlExecutionProvider",
                    "device_name": "DirectML", "half_precision": False}
    except Exception as exc:
        quiet.swallowed("vision.device_caps.directml_probe_failed", exc)
    try:
        import torch_directml  # noqa: F401
        return {"device": "directml", "device_name": "DirectML (torch)",
                "half_precision": False}
    except Exception:
        return None


_PROBES = {
    "tensorrt": _probe_tensorrt,
    "cuda": _probe_cuda,
    "directml": _probe_directml,
    "onnxruntime_gpu": _probe_onnx_gpu,
    "cpu": lambda: {"device": "cpu", "device_name": "CPU"},
}


class DeviceCapabilityResolver:
    def __init__(self, probes: dict | None = None):
        self._probes = probes or _PROBES

    def resolve(self, preference: list[str] | None = None,
                half_precision: str = "auto") -> DeviceCapabilities:
        preference = preference or list(config.get(
            "vision.yolo.backend_preference", _DEFAULT_PREFERENCE))
        if "cpu" not in preference:
            preference = [*preference, "cpu"]      # CPU is always the floor

        available: list[str] = []
        chosen: dict | None = None
        chosen_backend = "cpu"
        tried = []
        for backend in preference:
            probe = self._probes.get(backend)
            if probe is None:
                continue
            result = self._safe(probe)
            if result is not None:
                available.append(backend)
                if chosen is None:
                    chosen, chosen_backend = result, backend
            else:
                tried.append(backend)

        chosen = chosen or {"device": "cpu", "device_name": "CPU"}
        caps = DeviceCapabilities(
            backend=chosen_backend,
            device=chosen.get("device", "cpu"),
            device_name=chosen.get("device_name", "CPU"),
            compute_capability=chosen.get("compute_capability", ""),
            vram_mb=chosen.get("vram_mb"),
            tensorrt="tensorrt" in available,
            cuda="cuda" in available,
            onnx_gpu="onnxruntime_gpu" in available,
            directml="directml" in available,
            available_backends=available,
        )
        want_half = chosen.get("half_precision", False)
        if half_precision == "auto":
            caps.half_precision = bool(want_half)
        else:
            caps.half_precision = (str(half_precision).lower() in ("1", "true", "yes")
                                   and bool(want_half))
        if chosen_backend == "cpu" and tried:
            caps.fallback_reason = "no GPU backend available: " + ",".join(tried)
        _logger.info("device.resolved", **{
            "backend": caps.backend, "device": caps.device_name,
            "available": available, "half": caps.half_precision})
        return caps

    @staticmethod
    def _safe(probe):
        try:
            return probe()
        except Exception as e:
            _logger.debug("device.probe_error", error=str(e)[:80])
            return None
