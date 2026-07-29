"""image_generate (§3.1.O) — provider-agnostic.

openai_compat → endpoint /images/generations; gemini → Imagen via
google-genai. Hasil disimpan ke data/generated/, return path.
"""
from __future__ import annotations

import asyncio
import base64
import time

from pydantic import BaseModel, Field

from jarvis.core import config, log
from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.paths import generated_dir

_logger = log.get("agent.tools.image")


def _image_provider_name() -> str:
    """Provider jalur image: image_generation.provider → legacy
    agent.image_provider → '' (provider LLM aktif)."""
    return str(config.get("image_generation.provider", "")
               or config.get("agent.image_provider", "") or "")


def available() -> bool:
    """Gate registry (§7.3.3): False bila tidak ada jalur ber-capability
    image — tool tidak masuk schema, grup Image Generation tampil abu."""
    try:
        from jarvis.agent import providers
        provider_name = _image_provider_name()
        if provider_name:
            p = providers.get_provider(provider_name)
        else:
            # Belum diset di Image Generation Settings: pilih provider mana pun
            # yang terkonfigurasi & mendukung image (Gemini / OAuth / local).
            p = None
            for name in providers.list_names():
                cand = providers.get_provider(name)
                if cand and cand.supports("image") and cand.configured():
                    p = cand
                    break
            if p is None:
                p = providers.get_provider(None)

        if p is None or not p.supports("image"):
            return False
        if p.kind == "openai_oauth":
            # Codex OAuth image lewat built-in tool image_generation; hanya
            # tersedia setelah sign in (fail-closed).
            from jarvis.integrations import openai_oauth
            return openai_oauth.image_generation_supported()
        if p.kind == "gemini":
            return bool(p.api_key)
        return bool(p.api_key or p.auth == "none"
                    or (p.base_url and "api.openai.com" not in p.base_url))
    except Exception:                          # noqa: BLE001
        return False


def resolve_openai_request(size_arg: str = "") -> dict:
    """Model + argumen images.generate untuk jalur OpenAI-compatible.

    quality instant|thinking hanya dikirim untuk gpt-image-2* — server
    lokal / model lama menolak parameter asing.
    """
    model = str(config.get("image_generation.model", "")
                or config.get("agent.image_model_openai", "")
                or "gpt-image-2")
    out: dict = {"model": model,
                 "size": size_arg
                 or str(config.get("image_generation.size", "1024x1024"))}
    if model.startswith("gpt-image-2"):
        quality = str(config.get("image_generation.quality", "instant"))
        if quality in ("instant", "thinking"):
            out["quality"] = quality
    return out


class _Params(BaseModel):
    prompt: str = Field(description="Deskripsi gambar")
    size: str = Field("", description="Ukuran, mis. 1024x1024; kosong = "
                                      "default config")
    n: int = Field(1, description="Jumlah gambar (maks 2)")


class ImageGenerate(Tool):
    name = "image_generate"
    description = ("Generate gambar dari teks memakai provider image aktif "
                   "(OpenAI-compatible / Gemini Imagen). Return path file.")
    params_schema = _Params
    timeout_s = 180

    async def run(self, prompt: str, size: str = "", n: int = 1,
                  **_) -> ToolResult:
        n = max(1, min(int(n or 1), 2))

        def _generate() -> list[str]:
            paths: list[str] = []
            from jarvis.agent import providers
            p = providers.get_provider(_image_provider_name() or None)
            if p.kind == "openai_oauth":
                # Codex OAuth: built-in tool image_generation via Responses.
                from jarvis.integrations import openai_oauth
                quality = str(config.get("image_generation.quality", "medium"))
                if quality not in openai_oauth.IMAGE_QUALITY_EFFORT:
                    quality = "medium"
                images = openai_oauth.generate_image(
                    prompt,
                    size=str(config.get("image_generation.size", "auto")),
                    quality=quality)
                for data in images[:n]:
                    path = generated_dir() / f"img_{int(time.time())}_" \
                                             f"{len(paths)}.png"
                    path.write_bytes(data)
                    paths.append(str(path))
            elif p.kind == "gemini":
                from google import genai
                client = genai.Client(api_key=p.api_key)
                model = str(config.get("agent.image_model",
                                       "imagen-4.0-generate-001"))
                resp = client.models.generate_images(
                    model=model, prompt=prompt,
                    config={"number_of_images": n})
                for img in (resp.generated_images or []):
                    path = generated_dir() / f"img_{int(time.time())}_" \
                                             f"{len(paths)}.png"
                    path.write_bytes(img.image.image_bytes)
                    paths.append(str(path))
            else:
                from openai import OpenAI
                client = OpenAI(api_key=p.api_key or "not-needed",
                                base_url=p.base_url or None, timeout=170)
                req = resolve_openai_request(size)
                resp = client.images.generate(prompt=prompt, n=n, **req)
                for d in resp.data:
                    path = generated_dir() / f"img_{int(time.time())}_" \
                                             f"{len(paths)}.png"
                    if getattr(d, "b64_json", None):
                        path.write_bytes(base64.b64decode(d.b64_json))
                    elif getattr(d, "url", None):
                        import requests
                        r = requests.get(d.url, timeout=60)
                        r.raise_for_status()
                        path.write_bytes(r.content)
                    else:
                        continue
                    paths.append(str(path))
            return paths

        try:
            paths = await asyncio.to_thread(_generate)
        except Exception as e:                               # noqa: BLE001
            return ToolResult.fail(f"generate gambar gagal: {str(e)[:200]}")
        if not paths:
            return ToolResult.fail("provider tidak mengembalikan gambar")
        return ToolResult.success(
            "gambar tersimpan:\n" + "\n".join(paths),
            display=f"{len(paths)} gambar", paths=paths)
