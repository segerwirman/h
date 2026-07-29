"""Service seam for the Capabilities → Image Generation selector (UI-thin).

Menyediakan daftar provider image + status kesiapan, katalog model (statis per
provider + katalog OAuth Codex untuk gpt-image-2 Low/Medium/High), tier quality,
serta baca/tulis konfigurasi ``image_generation.*`` yang aman.

Tidak melakukan I/O berat di jalur list default; deteksi model provider bersifat
opt-in lewat :func:`detect_models`. Semua penulisan lewat ``config_write`` agar
kompatibel dengan lapisan settings lain.
"""
from __future__ import annotations

from dataclasses import dataclass

from jarvis.core import config, log

_logger = log.get("agent.image_gen_service")

# Tiga tier gpt-image-2 (persis panel Hermes) → reasoning effort Codex OAuth.
GPT_IMAGE_TIERS: tuple[dict, ...] = (
    {"quality": "low", "label": "GPT Image 2 (Low)",
     "hint": "~15s · iterasi cepat, biaya terendah"},
    {"quality": "medium", "label": "GPT Image 2 (Medium)",
     "hint": "~40s · seimbang — default"},
    {"quality": "high", "label": "GPT Image 2 (High)",
     "hint": "~2min · fidelitas tertinggi, prompt adherence terkuat"},
)

# Model default per provider (fallback saat deteksi katalog tidak dijalankan).
_STATIC_MODELS: dict[str, tuple[str, ...]] = {
    "gemini": ("imagen-4.0-generate-001", "imagen-3.0-generate-002"),
    "openai": ("gpt-image-2", "dall-e-3"),
    "openai_oauth": ("gpt-image-2",),
}


@dataclass(frozen=True)
class ImageProvider:
    name: str
    label: str
    kind: str
    ready: bool
    tag: str          # "subscription" | "paid" | "free" | "local"
    reason: str = ""


def _provider_tag(kind: str, auth: str) -> str:
    if auth == "oauth":
        return "free"
    if auth == "none":
        return "local"
    return "paid"


def list_providers() -> list[ImageProvider]:
    """Provider ber-capability image + status siap (untuk panel selektor).

    Codex OAuth muncul sebagai jalur ``free`` (gpt-image-2 tanpa API key),
    hanya ``ready`` setelah sign in.
    """
    out: list[ImageProvider] = []
    try:
        from jarvis.agent import providers
        names = providers.list_names()
    except Exception:                                        # noqa: BLE001
        return out
    for name in names:
        try:
            p = providers.get_provider(name)
        except Exception:                                    # noqa: BLE001
            continue
        if not p.supports("image"):
            continue
        ready = False
        reason = ""
        if p.kind == "openai_oauth":
            try:
                from jarvis.integrations import openai_oauth
                ready = openai_oauth.image_generation_supported()
            except Exception:                                # noqa: BLE001
                ready = False
            if not ready:
                reason = "sign in di Connect Account"
        elif p.kind == "gemini":
            ready = bool(p.api_key)
            if not ready:
                reason = "butuh API key"
        else:
            ready = bool(p.api_key or p.auth == "none"
                         or (p.base_url and "api.openai.com" not in p.base_url))
            if not ready:
                reason = "butuh API key / base URL"
        out.append(ImageProvider(
            name=name, label=p.label or name, kind=p.kind, ready=ready,
            tag=_provider_tag(p.kind, p.auth), reason=reason))
    return out


def models_for(provider_name: str) -> list[str]:
    """Model statis yang diketahui untuk provider (tanpa network)."""
    return list(_STATIC_MODELS.get(provider_name, ()))


def detect_models(provider_name: str) -> list[str]:
    """Deteksi katalog model provider secara opt-in (blocking; panggil di worker).

    Fail-soft: kembalikan model statis bila katalog tidak tersedia.
    """
    try:
        from jarvis.agent import providers, model_catalog
        catalog = model_catalog.discover(providers.get_provider(provider_name))
        models = list(catalog.models)
        if models:
            return models
    except Exception as exc:                                 # noqa: BLE001
        _logger.info("image_gen.detect_failed", provider=provider_name,
                     error=str(exc)[:80])
    return models_for(provider_name)


def current() -> dict:
    """Konfigurasi image aktif untuk render panel."""
    return {
        "provider": str(config.get("image_generation.provider", "") or ""),
        "model": str(config.get("image_generation.model", "") or ""),
        "quality": str(config.get("image_generation.quality", "medium") or "medium"),
        "size": str(config.get("image_generation.size", "1024x1024") or "1024x1024"),
    }


def _write(key: str, value: str) -> bool:
    try:
        from jarvis.core import config_write
        return bool(config_write.set_scalar(key, value))
    except Exception as exc:                                 # noqa: BLE001
        _logger.error("image_gen.write_failed", key=key, error=str(exc)[:80])
        return False


def set_provider(provider_name: str) -> bool:
    return _write("image_generation.provider", provider_name)


def set_model(model: str) -> bool:
    return _write("image_generation.model", model)


def set_quality(quality: str) -> bool:
    q = str(quality or "").lower()
    if q not in {"instant", "thinking", "low", "medium", "high"}:
        return False
    return _write("image_generation.quality", q)


def select_gpt_image_tier(quality: str) -> bool:
    """Pilih tier gpt-image-2 Low/Medium/High (Codex OAuth) sekaligus set model."""
    if quality not in {t["quality"] for t in GPT_IMAGE_TIERS}:
        return False
    ok_model = set_model("gpt-image-2")
    ok_quality = set_quality(quality)
    return ok_model and ok_quality
