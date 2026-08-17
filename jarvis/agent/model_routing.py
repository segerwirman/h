"""Model routing per lane (MK50 §3) — provider ringan configurable, heavy untuk T2+.

Sumber keputusan lane adalah Router (§2, ``Route.model_profile``); modul ini
menerjemahkan profile menjadi klien LLM nyata di atas registry provider yang
SUDAH ada (``jarvis.agent.providers`` + ``jarvis.agent.llm_client``) — bukan
registry baru.

Resolusi lane berat (urutan kandidat, §3.1–§3.2):

  1. ``routing.heavy.provider`` di config.yaml (pilihan eksplisit; boleh
     dengan override ``routing.heavy.model``).
  2. Provider aktif Settings (ikon gear) BILA berbeda dari provider lane
     ringan — mekanisme pemilihan agent-model yang sudah ada tetap dihormati.
     Provider light (Gemini) TIDAK pernah dipromosikan otomatis ke lane berat
     (§0 keputusan 3: kunci Gemini hanya percakapan + tugas ringan).
  3. ``routing.heavy.fallback`` — daftar nama provider, dipakai berurutan.

Kandidat yang belum terkonfigurasi dilewati (dicatat di log); tidak ada
kandidat sama sekali → ``heavy_resolution()`` mengembalikan ``None`` dan
pemanggil WAJIB degrade jujur (§3.2), bukan diam-diam memakai Gemini.

Side-task murah (§3.3 — kompresi konteks, embedding) memakai lane ringan
lewat ``light_client()``/``compression_client()``. Default light tetap Gemini,
tetapi UI dapat memilih provider chat yang sudah tersedia, termasuk OAuth.
Classifier Router tetap ter-pin ke Gemini di ``jarvis.agent.router``. Tidak ada
fungsi di modul ini yang raise ke pemanggil.
"""
from __future__ import annotations

import re
import threading

from jarvis.core import config, log, quiet
from jarvis.agent.providers import Provider, get_provider

_logger = log.get("agent.model_routing")

DEFAULT_LIGHT_PROVIDER = "gemini"

# Kegagalan yang membenarkan pindah provider dalam satu run (§3.1:
# "rantai fallback bila 402/kredit habis/timeout"). 429/5xx transient sudah
# di-retry di dalam llm_client; sampai di sini artinya retry habis.
_FAILOVER_RE = re.compile(
    r"402|payment|billing|credit|kredit|insufficient|quota|exceeded"
    r"|resource.?exhausted|429|rate.?limit|timeout|timed.?out|belum "
    r"dikonfigurasi|404|not.?found|unknown.?model|model.{0,40}"
    r"(?:invalid|unsupported)|(?:tool|function).{0,40}(?:unsupported|"
    r"not.?supported)",
    re.IGNORECASE)

_warn_once_lock = threading.Lock()
_warned: set[str] = set()


def _warn_once(key: str, message: str, **kwargs) -> None:
    with _warn_once_lock:
        if key in _warned:
            return
        _warned.add(key)
    _logger.warning(message, **kwargs)


def publish_provider_event(role: str, provider: str, reason: str,
                           event: str) -> None:
    """Publikasikan observability provider tanpa credential atau error mentah."""
    try:
        from jarvis.core.bus import BUS
        BUS.publish("agent.provider_policy", role=str(role)[:40],
                    provider=str(provider)[:80], reason=str(reason)[:180],
                    event=str(event)[:40])
    except Exception as exc:                                 # noqa: BLE001
        quiet.swallowed("agent.model_routing.policy_publish_failed", exc)


# ── lane ringan ───────────────────────────────────────────────────────────

def light_name() -> str:
    name = str(config.get("routing.light.provider",
                          DEFAULT_LIGHT_PROVIDER) or DEFAULT_LIGHT_PROVIDER)
    return name.strip() or DEFAULT_LIGHT_PROVIDER


def light_client():
    """Klien lane ringan (§3.2/§3.3). Model override via ``routing.light.model``."""
    from jarvis.agent import llm_client

    name = light_name()
    model = str(config.get("routing.light.model", "") or "").strip()
    try:
        if not model:
            return llm_client.client(name)
        provider = get_provider(name)
        if model == provider.model:
            return llm_client.client(name)
        clone = Provider(**{**provider.__dict__})
        clone.model = model
        return llm_client.LLMClient(clone)
    except Exception as e:                                   # noqa: BLE001
        _logger.warning("model_routing.light_client_failed",
                        error=str(e)[:120])
        return llm_client.client(name)


def compression_client():
    """Klien kompresi konteks (§3.3): override slot auxiliary dihormati
    (toggle nyata), selain itu SELALU lane ringan — bukan model berat."""
    try:
        from jarvis.agent import auxiliary
        prov_name, model = auxiliary.slot_config("compression")
        if prov_name not in ("", "auto") or model:
            return auxiliary.client_for("compression")
    except Exception as e:                                   # noqa: BLE001
        _logger.warning("model_routing.compression_override_failed",
                        error=str(e)[:120])
    return light_client()


def conversation_resolution() -> tuple[object | None, str, str]:
    """(klien, provider, alasan) untuk response-composer/conversation.

    Role ini tidak mengubah voice transport. Saat ``auto`` (atau override
    belum siap), ia memakai lane light agar phrasing percakapan tetap murah dan
    cepat; hanya override yang benar-benar terkonfigurasi yang dipilih.
    """
    from jarvis.agent import llm_client

    requested = str(config.get("routing.conversation.provider", "auto")
                    or "auto").strip()
    model = str(config.get("routing.conversation.model", "") or "").strip()
    if requested not in ("", "auto"):
        provider = _configured(requested)
        if provider is not None:
            try:
                if model and model != provider.model:
                    clone = Provider(**{**provider.__dict__})
                    clone.model = model
                    return (llm_client.LLMClient(clone), requested,
                            f"routing.conversation: {requested} model={model}")
                return (llm_client.client(requested), requested,
                        f"routing.conversation: {requested}")
            except Exception as e:                           # noqa: BLE001
                _logger.warning("model_routing.conversation_client_failed",
                                provider=requested, error=str(e)[:120])
        fallback_note = f"override {requested} belum dikonfigurasi; "
    else:
        fallback_note = ""

    name = light_name()
    if _configured(name) is None:
        return None, "", (fallback_note + "provider lane light belum "
                          "dikonfigurasi")
    try:
        return light_client(), name, (fallback_note +
                                      f"routing.conversation: light ({name})")
    except Exception as e:                                   # noqa: BLE001
        _logger.warning("model_routing.conversation_light_failed",
                        provider=name, error=str(e)[:120])
        return None, "", fallback_note + "klien lane light tidak tersedia"


def conversation_client():
    """Klien role conversation; ``None`` bila tidak ada provider siap."""
    client, _, _ = conversation_resolution()
    return client


def _role_status(role: str, provider: str, model: str, configured: bool,
                 reason: str) -> dict[str, bool | str]:
    return {"role": role, "provider": provider, "model": model,
            "configured": configured, "reason": reason}


def role_statuses() -> dict[str, dict[str, bool | str]]:
    """Status role provider yang aman untuk Settings dan telemetry.

    Tidak membuat panggilan jaringan dan tidak pernah mengembalikan credential.
    ``voice_transport`` bersifat runtime-managed: model dicatat untuk konteks,
    sedangkan kesiapan audio ditentukan oleh lifecycle Gemini Live yang ada.
    """
    live_model = str(config.get("llm.live_model", "") or "").strip()
    light = light_name()
    light_provider = _configured(light)
    light_model = str(config.get("routing.light.model", "") or "").strip()
    if not light_model and light_provider is not None:
        light_model = light_provider.model

    try:
        _, heavy_name, heavy_reason = heavy_resolution()
    except Exception:                                        # noqa: BLE001
        heavy_name, heavy_reason = "", "gagal meresolusikan provider berat"
    heavy_provider = _configured(heavy_name) if heavy_name else None

    try:
        _, conversation_name, conversation_reason = conversation_resolution()
    except Exception:                                        # noqa: BLE001
        conversation_name = ""
        conversation_reason = "gagal meresolusikan provider conversation"
    conversation_provider = _configured(conversation_name) \
        if conversation_name else None

    auxiliary_name = str(config.get("auxiliary.response_composer.provider",
                                    "auto") or "auto").strip() or "auto"
    auxiliary_model = str(config.get("auxiliary.response_composer.model", "")
                          or "").strip()

    return {
        "voice_transport": _role_status(
            "voice_transport", "gemini_live", live_model, False,
            "runtime-managed oleh Gemini Live; bukan fallback agent"),
        "light": _role_status(
            "light", light, light_model, light_provider is not None,
            f"routing.light: {light}" if light_provider is not None
            else "provider lane light belum dikonfigurasi"),
        "heavy": _role_status(
            "heavy", heavy_name, heavy_provider.model if heavy_provider else "",
            heavy_provider is not None, heavy_reason),
        "conversation": _role_status(
            "conversation", conversation_name,
            conversation_provider.model if conversation_provider else "",
            conversation_provider is not None, conversation_reason),
        "auxiliary": _role_status(
            "auxiliary", auxiliary_name, auxiliary_model, False,
            "diresolusikan per slot auxiliary" if auxiliary_name == "auto"
            else "konfigurasi auxiliary response composer"),
    }


# ── lane berat ────────────────────────────────────────────────────────────

def _configured(name: str) -> Provider | None:
    try:
        p = get_provider(name)
        return p if p.configured() else None
    except Exception as e:                                   # noqa: BLE001
        _logger.warning("model_routing.provider_failed", provider=name,
                        error=str(e)[:100])
        return None


def heavy_candidates() -> list[str]:
    """Nama kandidat provider berat, urut prioritas, tanpa duplikat.
    Belum difilter ketersediaan — lihat ``heavy_resolution()``."""
    names: list[str] = []

    explicit = str(config.get("routing.heavy.provider", "") or "").strip()
    if explicit and explicit != "auto":
        names.append(explicit)
        if explicit == light_name():
            _warn_once(
                "heavy_is_light",
                "model_routing.heavy_equals_light",
                provider=explicit,
                note="routing.heavy.provider menunjuk provider lane ringan; "
                     "§0 keputusan 3 memisahkan keduanya — dihormati karena "
                     "eksplisit dari user")

    try:
        from jarvis.agent.providers import active_name
        active = active_name()
    except Exception:                                        # noqa: BLE001
        active = ""
    if active and active != light_name() and active not in names:
        names.append(active)

    fallback = config.get("routing.heavy.fallback", []) or []
    if isinstance(fallback, str):
        fallback = [fallback]
    for raw in fallback:
        name = str(raw or "").strip()
        if name and name not in names:
            names.append(name)

    # Explicit opt-in: keep T2/T3 functional when the dedicated work model is
    # absent by reusing the already configured conversation provider.  This is
    # appended last, so a real heavy provider always wins and the light
    # conversation lane itself is never changed.
    if bool(config.get("routing.heavy.allow_light_fallback", False)):
        light = light_name()
        if light and light not in names:
            names.append(light)
    return names


def heavy_resolution() -> tuple[object | None, str, str]:
    """(klien, nama_provider, alasan) untuk lane berat.

    Klien ``None`` berarti TIDAK ADA provider berat yang siap — pemanggil
    wajib menyampaikan degrade §3.2. Provider lane ringan hanya dapat muncul
    sebagai kandidat terakhir saat ``allow_light_fallback`` diaktifkan.
    """
    from jarvis.agent import llm_client

    candidates = heavy_candidates()
    explicit = candidates[0] if candidates else ""
    for name in candidates:
        provider = _configured(name)
        if provider is None:
            _logger.info("model_routing.heavy_skip", provider=name,
                         reason="belum dikonfigurasi")
            continue
        model = ""
        if name == explicit:
            model = str(config.get("routing.heavy.model", "") or "").strip()
        try:
            if model and model != provider.model:
                clone = Provider(**{**provider.__dict__})
                clone.model = model
                return (llm_client.LLMClient(clone), name,
                        f"routing.heavy: {name} model={model}")
            return llm_client.client(name), name, f"routing.heavy: {name}"
        except Exception as e:                               # noqa: BLE001
            _logger.warning("model_routing.heavy_client_failed",
                            provider=name, error=str(e)[:120])
    return None, "", ("tidak ada provider berat terkonfigurasi "
                      f"(kandidat: {', '.join(candidates) or '-'})")


def next_heavy_client(tried: set[str]):
    """Kandidat berat berikutnya yang siap dan belum dicoba, untuk failover
    dalam-run (§3.1). ``None`` bila rantai habis."""
    from jarvis.agent import llm_client

    for name in heavy_candidates():
        if name in tried:
            continue
        if _configured(name) is None:
            continue
        try:
            return llm_client.client(name), name
        except Exception as e:                               # noqa: BLE001
            _logger.warning("model_routing.failover_client_failed",
                            provider=name, error=str(e)[:120])
    return None


def heavy_ready() -> bool:
    client, _, _ = heavy_resolution()
    if client is None:
        return False
    try:
        return bool(client.available())
    except Exception:                                        # noqa: BLE001
        return False


def failover_error(error: str | None) -> bool:
    """Apakah error LLM membenarkan pindah ke provider berikutnya?"""
    return bool(_FAILOVER_RE.search(str(error or "")))
