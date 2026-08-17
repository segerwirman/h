"""Auxiliary model router (PARITY v2 §7.1) — model terpisah per side-task.

Pola Hermes (agent/auxiliary_client.py) disederhanakan untuk Jarvis:

    resolusi per task:  auxiliary.<task>.provider/model di config.yaml
                        (default "auto" = provider & model utama)
    fallback:           override tidak tersedia → provider utama →
                        provider lain pertama yang tersedia

8 slot mengikuti layout Hermes (img 8); dua yang PUNYA titik integrasi
nyata di Jarvis langsung di-wire (vision, reflect). Slot lain resolvable —
menunggu fitur pemakainya; UI menandai jujur mana yang aktif.

Slot ``embedding`` sengaja TIDAK di-wire: ganti model embedding di tengah
jalan merusak kecocokan dimensi vektor di memory_store (§4.2).
"""
from __future__ import annotations

from jarvis.core import config, log, quiet
from jarvis.agent import llm_client
from jarvis.agent.providers import Provider, get_provider, list_names

_logger = log.get("agent.auxiliary")

# id, label, wired (punya titik integrasi nyata sekarang)
SLOTS: tuple[dict, ...] = (
    {"id": "vision", "label": "Vision / image analysis", "wired": True},
    {"id": "reflect", "label": "Reflection / self-learning", "wired": True},
    # compression di-wire Fase 3 (§3.3): default lane ringan via
    # model_routing.compression_client(); override slot ini tetap menang.
    {"id": "compression", "label": "Context compression", "wired": True},
    {"id": "web_extract", "label": "Web extract", "wired": False},
    {"id": "title_gen", "label": "Title generation", "wired": False},
    {"id": "approval", "label": "Approval review", "wired": False},
    {"id": "curator_review", "label": "Curator review", "wired": False},
    {"id": "embedding", "label": "Embedding (terkunci — dimensi vektor)",
     "wired": False},
)

SLOT_IDS = tuple(s["id"] for s in SLOTS)


def slot_config(task: str) -> tuple[str, str]:
    """(provider, model) dari config; 'auto'/'' = ikut utama."""
    provider = str(config.get(f"auxiliary.{task}.provider", "auto") or "auto")
    model = str(config.get(f"auxiliary.{task}.model", "") or "")
    return provider, model


def _provider_available(p: Provider) -> bool:
    if p.kind == "openai_compat":
        return bool(p.api_key or p.base_url)
    return bool(p.api_key)


def resolve(task: str) -> tuple[Provider, str]:
    """Provider + model final untuk task. Tidak pernah raise.

    Urutan: override per-task (bila tersedia) → provider utama →
    provider lain pertama yang tersedia → provider utama apa adanya
    (caller melihat available()=False seperti biasa).
    """
    prov_name, model = slot_config(task)
    if prov_name not in ("", "auto"):
        try:
            p = get_provider(prov_name)
            if _provider_available(p):
                return p, (model or p.model)
            _logger.warning("auxiliary.override_unavailable", task=task,
                            provider=prov_name)
        except Exception as e:                               # noqa: BLE001
            _logger.warning("auxiliary.override_failed", task=task,
                            error=str(e)[:100])
    main = get_provider(None)
    if _provider_available(main):
        return main, (model or main.model)
    for name in list_names():
        try:
            p = get_provider(name)
            if _provider_available(p):
                _logger.info("auxiliary.fallback", task=task, provider=name)
                return p, (model or p.model)
        except Exception as exc:                             # noqa: BLE001
            quiet.swallowed("agent.auxiliary.provider_probe_failed", exc)
            continue
    return main, (model or main.model)


def client_for(task: str):
    """LLMClient siap pakai untuk task. Task 'vision' tanpa override →
    vision_client() lama (resolusi vision_model tetap dihormati)."""
    prov_name, model = slot_config(task)
    if task == "vision" and prov_name in ("", "auto") and not model:
        return llm_client.vision_client()
    if prov_name in ("", "auto") and not model:
        return llm_client.client()
    p, final_model = resolve(task)
    if final_model == p.model:
        return llm_client.client(p.name)
    ap = Provider(**{**p.__dict__})
    ap.model = final_model
    return llm_client.LLMClient(ap)
