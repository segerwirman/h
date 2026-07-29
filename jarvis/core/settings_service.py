"""SettingsService (PARITY v2 §7) — seksi Settings sebagai DATA.

Panel Settings sebagian besar adalah UI untuk config.yaml yang SUDAH
berjalan — service ini mendeklarasikan seksi + field (key config, tipe,
label), membaca nilai via ``config.get`` dan menulis via
``config_write.set_scalar`` (surgical, komentar utuh).

Batas keras yang dihormati (§2.3, §7.2):
  - Voice: read-only — tidak ada pipeline baru, tidak ada provider Edge/
    AriaNeural Hermes.
  - Tidak ada theme picker Hermes — preset dari theme.py Jarvis sendiri.
  - Tidak ada Gateway/Nous/Kawaii/petdex.

Seksi Hermes: Notifications & Archived Chats belum ada padanan di Jarvis —
tidak dibangun (lapor, bukan diam-diam kosong).
"""
from __future__ import annotations

from jarvis.core import config, config_write, log

_logger = log.get("core.settings")

# type: text | int | float | bool | choice | readonly
# action: "providers" → UI membuka ProviderSettingsSheet yang sudah ada


def _themes() -> list[str]:
    try:
        from jarvis.ui import theme
        return theme.available_themes() or ["legacy"]
    except Exception:                                        # noqa: BLE001
        return ["legacy"]


def _aux_providers() -> list[str]:
    try:
        from jarvis.agent import providers
        return ["auto", *providers.list_names()]
    except Exception:                                        # noqa: BLE001
        return ["auto", "gemini", "openai", "anthropic", "local", "custom"]


def _auxiliary_fields() -> list[dict]:
    try:
        from jarvis.agent.auxiliary import SLOTS
    except Exception:                                        # noqa: BLE001
        return []
    out = [
        {"key": "auxiliary.response_composer.enabled",
         "label": "Natural response composer — aktif", "type": "bool"},
        {"key": "auxiliary.response_composer.provider",
         "label": "Natural response composer — provider", "type": "choice",
         "choices": _aux_providers()},
        {"key": "auxiliary.response_composer.model",
         "label": "Natural response composer — model", "type": "text"},
        {"key": "auxiliary.response_composer.timeout_s",
         "label": "Natural response composer — timeout (s)", "type": "float"},
        {"key": "auxiliary.response_composer.max_tokens",
         "label": "Natural response composer — max tokens", "type": "int"},
    ]
    for slot in SLOTS:
        sid, label = slot["id"], slot["label"]
        mark = " (aktif)" if slot["wired"] else ""
        if sid == "embedding":                 # terkunci — lihat hint seksi
            out.append({"key": f"auxiliary.{sid}.provider",
                        "label": label, "type": "readonly"})
            continue
        out.append({"key": f"auxiliary.{sid}.provider",
                    "label": f"{label}{mark} — provider",
                    "type": "choice", "choices": _aux_providers()})
        out.append({"key": f"auxiliary.{sid}.model",
                    "label": f"{label}{mark} — model",
                    "type": "text"})
    return out


def _image_providers() -> list[str]:
    try:
        from jarvis.agent import providers
        names = []
        for name in providers.list_names():
            provider = providers.get_provider(name)
            if not provider.supports("image"):
                continue
            # OAuth Codex mengiklankan capability image, tapi hanya benar-benar
            # tersedia setelah sign in — jangan tampilkan saat belum login.
            if provider.kind == "openai_oauth":
                try:
                    from jarvis.integrations import openai_oauth
                    if not openai_oauth.image_generation_supported():
                        continue
                except Exception:                            # noqa: BLE001
                    continue
            names.append(name)
    except Exception:                                        # noqa: BLE001
        names = ["gemini", "openai", "local", "custom"]
    return list(dict.fromkeys(["", *names]))


def _heavy_providers() -> list[str]:
    try:
        from jarvis.agent import providers
        return ["", *providers.chat_provider_names(only_enabled=True)]
    except Exception:                                        # noqa: BLE001
        return [""]


def _light_providers() -> list[str]:
    """Lane ringan dapat memilih provider chat apa pun, termasuk OAuth.

    Provider yang belum siap tetap tampil agar user dapat memilihnya lebih
    dahulu lalu melengkapi konfigurasi di ProviderSettingsSheet. Runtime tetap
    fail-closed melalui ``model_routing`` sampai provider benar-benar siap.
    """
    try:
        from jarvis.agent import providers
        names = providers.chat_provider_names()
    except Exception:                                        # noqa: BLE001
        names = ["gemini", "openai", "openai_oauth", "local", "custom"]
    return list(dict.fromkeys(["gemini", *names]))


def _conversation_providers() -> list[str]:
    try:
        from jarvis.agent import providers
        return ["auto", *providers.chat_provider_names(only_enabled=True)]
    except Exception:                                        # noqa: BLE001
        return ["auto"]


def provider_role_summary() -> str:
    """Ringkasan role provider yang aman untuk Settings provider sheet."""
    try:
        from jarvis.agent import model_routing
        roles = model_routing.role_statuses()
    except Exception:                                        # noqa: BLE001
        return "Provider role status unavailable"

    labels = {
        "voice_transport": "VOICE",
        "light": "LIGHT",
        "heavy": "HEAVY",
        "conversation": "CONVERSATION",
        "auxiliary": "AUXILIARY",
    }
    lines = []
    for role, label in labels.items():
        status = roles.get(role, {})
        provider = str(status.get("provider") or "")
        model = str(status.get("model") or "")
        if role == "voice_transport":
            value = "runtime-managed" + (f" ({model})" if model else "")
        elif status.get("configured") is True:
            value = provider + (f" ({model})" if model else "")
        else:
            value = "not configured"
        lines.append(f"{label}: {value}")
    return "\n".join(lines)


def _openai_oauth_connected() -> bool:
    try:
        from jarvis.integrations import openai_oauth
        return bool(openai_oauth.connected())
    except Exception:                                        # noqa: BLE001
        return False


def active_stack_summary() -> str:
    """Ringkasan sederhana 'provider apa yang sedang dipakai' untuk Voice, LLM,
    dan Image — plus aturan auto-switch OpenAI (Codex auth) ↔ Gemini.

    Ini bukan status role teknis; ini tampilan sekali-lihat agar user langsung
    tahu stack aktif. Tidak pernah menampilkan credential.
    """
    try:
        from jarvis.agent import providers
    except Exception:                                        # noqa: BLE001
        return "Status stack provider tidak tersedia."

    openai_on = _openai_oauth_connected()

    if openai_on:
        # OpenAI (Codex auth) terhubung → satu paket OpenAI; Gemini Live OFF.
        voice = "OpenAI (Codex auth) — cascade TTS"
        llm = "OpenAI (Codex auth)"
        image = "OpenAI (Codex auth) · gpt-image-2"
        switch = "OpenAI (Codex auth) TERHUBUNG → Gemini Live OFF"
    else:
        voice = "Gemini Live (native audio)"
        llm = _active_llm_label(providers)
        image = _active_image_label(providers)
        switch = "OpenAI (Codex auth) TIDAK terhubung → Gemini ON"

    return (
        "STACK AKTIF\n"
        f"  Voice : {voice}\n"
        f"  LLM   : {llm}\n"
        f"  Image : {image}\n"
        f"  Auto  : {switch}"
    )


def _active_llm_label(_providers) -> str:
    try:
        from jarvis.agent import model_routing

        status = model_routing.role_statuses().get("heavy", {})
        name = str(status.get("provider") or "")
        model_name = str(status.get("model") or "")
        model = f" ({model_name})" if model_name else ""
        if status.get("configured") and name:
            return f"{name}{model}"
        return "native agent belum dikonfigurasi"
    except Exception:                                        # noqa: BLE001
        return "belum dikonfigurasi"


def _active_image_label(providers) -> str:
    try:
        # image_generation.provider kosong = pakai provider aktif ber-capability
        prov = str(config.get("image_generation.provider", "") or "").strip()
        if not prov:
            for name in providers.list_names():
                try:
                    if providers.get_provider(name).supports("image"):
                        prov = name
                        break
                except Exception:                            # noqa: BLE001
                    continue
        return prov or "tidak ada provider image ber-capability"
    except Exception:                                        # noqa: BLE001
        return "tidak diketahui"


def sections() -> list[dict]:
    """Deklarasi seksi + nilai saat ini. UI merender dari sini."""
    return [
        {"id": "model", "title": "Model & Providers",
         "hint": "Provider LLM agent — kelola API key lewat sheet provider "
                 "yang sudah ada.",
         "action": "providers",
         "fields": [
             {"key": "agent.provider", "label": "Provider aktif",
              "type": "readonly"},
             {"key": "routing.light.provider", "label": "Provider ringan",
              "type": "choice", "choices": _light_providers()},
             {"key": "routing.light.model", "label": "Model ringan",
              "type": "text"},
             {"key": "routing.heavy.provider", "label": "Provider berat",
              "type": "choice", "choices": _heavy_providers()},
             {"key": "routing.heavy.model", "label": "Model agent",
              "type": "text"},
             {"key": "routing.conversation.provider",
              "label": "Provider conversation",
              "type": "choice", "choices": _conversation_providers()},
             {"key": "routing.conversation.model",
              "label": "Model conversation", "type": "text"},
             {"key": "agent.max_output_tokens", "label": "Max output token",
              "type": "int"},
         ]},
        {"id": "accounts", "title": "Connect Account",
         "hint": "Sign in OpenAI ChatGPT/Codex atau Anthropic Claude lewat "
                 "browser eksternal (PKCE + callback localhost). Token "
                 "disimpan terenkripsi; OAuth memberi capability chat.",
         "action": "oauth", "fields": []},
        {"id": "google", "title": "Google Cloud",
         "hint": "Satu OAuth Desktop untuk Calendar, YouTube Data, Gmail, "
                 "dan Drive. Aktifkan hanya API yang diperlukan; scope write "
                 "bersifat opt-in. Client secret dan token disimpan "
                 "terenkripsi, bukan di config.yaml.",
         "action": "google_oauth",
         "fields": [
             {"key": "providers.google.enabled", "label": "Akun terhubung",
              "type": "readonly"},
             {"key": "providers.google.apis.calendar.enabled",
              "label": "Calendar — read", "type": "bool"},
             {"key": "providers.google.apis.calendar.write",
              "label": "Calendar — create event", "type": "bool"},
             {"key": "providers.google.apis.youtube.enabled",
              "label": "YouTube Data — read", "type": "bool"},
             {"key": "providers.google.apis.youtube.write",
              "label": "YouTube — comments/write", "type": "bool"},
             {"key": "providers.google.apis.gmail.enabled",
              "label": "Gmail — read", "type": "bool"},
             {"key": "providers.google.apis.gmail.write",
              "label": "Gmail — send", "type": "bool"},
             {"key": "providers.google.apis.drive.enabled",
              "label": "Drive — read", "type": "bool"},
         ]},
        {"id": "image", "title": "Image Generation",
         "hint": "Provider image ber-capability image. gpt-image-2 via API key "
                 "OpenAI butuh tier berbayar; via OpenAI Codex OAuth "
                 "(gpt-image-2) tanpa API key setelah sign in di Connect "
                 "Account. Quality instant/thinking untuk API key; "
                 "low/medium/high (reasoning effort) untuk Codex OAuth.",
         "fields": [
             {"key": "image_generation.provider", "label": "Provider",
              "type": "choice", "choices": _image_providers()},
             {"key": "image_generation.model", "label": "Model",
              "type": "text"},
             {"key": "image_generation.quality", "label": "Quality",
              "type": "choice",
              "choices": ["instant", "thinking", "low", "medium", "high"]},
             {"key": "image_generation.size", "label": "Ukuran default",
              "type": "text"},
         ]},
        {"id": "chat", "title": "Chat",
         "hint": "Persona dari core/prompt.txt — dipakai apa adanya (§2.3).",
         "fields": [
             {"key": "agent.persona_file", "label": "File persona",
              "type": "readonly"},
             {"key": "agent.ack_phrase", "label": "Frasa ACK",
              "type": "text"},
             {"key": "agent.max_iterations", "label": "Iterasi maks / tugas",
              "type": "int"},
         ]},
        {"id": "appearance", "title": "Appearance",
         "hint": "Preset tema milik Jarvis (theme.py) — bukan tema Hermes.",
         "fields": [
             {"key": "ui.themes.active", "label": "Tema",
              "type": "choice", "choices": _themes()},
             {"key": "ui.reduced_motion", "label": "Reduced motion",
              "type": "bool"},
         ]},
        {"id": "workspace", "title": "Workspace",
         "hint": "Sandbox operasi file agent.",
         "fields": [
             {"key": "agent.workspace_root", "label": "Workspace root",
              "type": "text"},
             {"key": "agent.data_dir", "label": "Data dir",
              "type": "readonly"},
             {"key": "agent.skills_dir", "label": "Skills dir",
              "type": "readonly"},
         ]},
        {"id": "safety", "title": "Safety",
         "hint": "Konfirmasi tool berbahaya ditegakkan registry (§A.6) — "
                 "di sini hanya knob-nya.",
         "fields": [
             {"key": "security.secrets_backend",
              "label": "Penyimpanan aman", "type": "readonly"},
             {"key": "agent.confirm_timeout_s",
              "label": "Timeout konfirmasi (s)", "type": "int"},
             {"key": "agent.task_timeout_s", "label": "Timeout tugas (s)",
              "type": "int"},
         ]},
        {"id": "memory", "title": "Memory & Context",
         "hint": "Knob memory_store + kompaksi konteks.",
         "fields": [
             {"key": "agent.context_window_tokens",
              "label": "Context window (token)", "type": "int"},
             {"key": "agent.context_threshold",
              "label": "Ambang kompaksi (0-1)", "type": "float"},
             {"key": "agent.compact_keep_last",
              "label": "Pesan terakhir dipertahankan", "type": "int"},
         ]},
        {"id": "auxiliary", "title": "Auxiliary Models",
         "hint": "Model terpisah per side-task (§7.1). auto = ikut provider "
                 "utama. Slot bertanda (aktif) sudah dipakai; sisanya "
                 "menunggu fitur pemakainya. Embedding terkunci — ganti "
                 "model merusak dimensi vektor memory.",
         "fields": _auxiliary_fields()},
        {"id": "voice", "title": "Voice",
         "hint": "FROZEN (§7.2) — konfigurasi suara Jarvis yang berjalan, "
                 "hanya baca.",
         "fields": [
             {"key": "llm.live_model", "label": "Model live",
              "type": "readonly"},
             {"key": "voice.barge_in.enabled", "label": "Barge-in",
              "type": "readonly"},
             {"key": "wake.enabled", "label": "Wake trigger",
              "type": "readonly"},
         ]},
        {"id": "whatsapp_web", "title": "WhatsApp Web",
         "hint": "Otomasi profil khusus dengan allowlist dan konfirmasi wajib.",
         "fields": [
             {"key": "whatsapp_web.enabled", "label": "Aktif",
              "type": "bool"},
             {"key": "whatsapp_web.user_data_dir", "label": "Folder profil",
              "type": "text"},
             {"key": "whatsapp_web.audio_bridge.enabled",
              "label": "Audio bridge", "type": "bool"},
             {"key": "whatsapp_web.audio_bridge.remote_input_device",
              "label": "Audio lawan → Jarvis", "type": "text"},
             {"key": "whatsapp_web.audio_bridge.remote_output_device",
              "label": "Audio Jarvis → WhatsApp", "type": "text"},
         ]},
        {"id": "about", "title": "About",
         "hint": "J.A.R.V.I.S MK50 Hybrid — parity layer di atas fondasi "
                 "Mark XLIX/L.",
         "fields": [
             {"key": "window.title", "label": "Build", "type": "readonly"},
         ]},
    ]


def resolve(sections_list: list[dict] | None = None) -> list[dict]:
    """Isi ``value`` tiap field dari config saat ini."""
    out = []
    for sec in (sections_list or sections()):
        fields = []
        for f in sec["fields"]:
            if f["key"] == "security.secrets_backend":
                try:
                    from jarvis.core import secrets_store
                    val = secrets_store.backend_label()
                except Exception:                            # noqa: BLE001
                    val = "Tidak tersedia"
            else:
                val = config.get(f["key"], "")
            fields.append({**f, "value": "" if val is None else val})
        out.append({**sec, "fields": fields})
    return out


_COERCE = {
    "int": int,
    "float": float,
    "text": str,
    "choice": str,
}


def set_value(key: str, value, ftype: str) -> tuple[bool, str]:
    """Validasi tipe + tulis surgical. readonly ditolak di sini juga —
    penegakan bukan hanya di UI."""
    field = None
    for sec in sections():
        for f in sec["fields"]:
            if f["key"] == key:
                field = f
                break
    if field is None:
        return False, f"key tidak dikenal: {key}"
    if field["type"] == "readonly":
        return False, f"{key} read-only"
    if field["type"] != ftype:
        return False, f"tipe salah untuk {key}"
    try:
        if ftype == "bool":
            coerced = value if isinstance(value, bool) \
                else str(value).strip().lower() in ("1", "true", "yes", "on")
        else:
            coerced = _COERCE[ftype](value)
    except (ValueError, KeyError):
        return False, f"nilai tidak valid untuk {key}"
    if field["type"] == "choice" and coerced not in field.get("choices", []):
        return False, f"pilihan tidak dikenal: {coerced}"
    if not config_write.set_scalar(key, coerced):
        return False, "gagal menulis config.yaml"
    # tema berlaku langsung — modul lain membaca theme.PAL singleton
    if key == "ui.themes.active":
        try:
            from jarvis.ui import theme
            theme.set_theme(str(coerced))
        except Exception:                                    # noqa: BLE001
            pass
    if key.startswith("providers.google.apis."):
        try:
            from jarvis.integrations import google_auth
            google_auth.refresh_registry()
        except Exception:                                    # noqa: BLE001
            pass
    return True, "tersimpan"
