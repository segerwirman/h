"""OpenAI ChatGPT/Codex OAuth PKCE + loopback dan adapter chat Responses.

Endpoint, public client id, port callback, header, dan bentuk token exchange
mengikuti implementasi Codex resmi; token hanya disimpan di secrets_store.
"""
from __future__ import annotations

import base64
import json
import threading
import time

from jarvis.core import log, secrets_store
from jarvis.integrations import oauth_loopback

_logger = log.get("integrations.openai_oauth")
_lock = threading.Lock()
_status_lock = threading.Lock()
_last_error_code = ""

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = f"{ISSUER}/oauth/authorize"
TOKEN_URL = f"{ISSUER}/oauth/token"
CODEX_BASE = "https://chatgpt.com/backend-api/codex"
SCOPES = ("openid profile email offline_access "
          "api.connectors.read api.connectors.invoke")
_STORE_KEY = "jarvis/oauth/openai"
_UA = "codex_cli_rs/0.0.0 (jarvis-mk50)"
_REFRESH_SKEW_S = 300


class OAuthError(RuntimeError):
    """Kesalahan OAuth yang aman ditampilkan melalui LLM/UI."""

    def __init__(self, message: str, code: str = "unknown"):
        super().__init__(message)
        self.code = code


def _set_last_error(code: str) -> None:
    global _last_error_code
    with _status_lock:
        _last_error_code = code


def _error(message: str, code: str = "unknown") -> OAuthError:
    _set_last_error(code)
    return OAuthError(message, code)


def _reset_clients() -> None:
    """Perubahan credential OAuth harus berlaku tanpa restart aplikasi."""
    try:
        from jarvis.agent import providers
        providers.reset_clients()
    except Exception:                                       # noqa: BLE001
        pass


def _load_tokens() -> dict:
    raw = secrets_store.get(_STORE_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_tokens(tokens: dict) -> bool:
    return secrets_store.set(_STORE_KEY, json.dumps(
        tokens, ensure_ascii=False, separators=(",", ":")))


def status() -> dict[str, bool | str]:
    """Status OAuth aman untuk Settings/provider registry tanpa refresh I/O."""
    tokens = _load_tokens()
    access = str(tokens.get("access_token") or "")
    refresh = str(tokens.get("refresh_token") or "")
    refresh_due = bool(refresh and (not access or _expiring(access)))
    needs_reauth = bool((access or refresh) and not refresh
                        and (not access or _expiring(access)))
    with _status_lock:
        last_error = _last_error_code
    return {
        "connected": bool(access or refresh) and not needs_reauth,
        "needs_reauth": needs_reauth,
        "token_refresh_due": refresh_due,
        "last_error_code": last_error,
    }


def connected() -> bool:
    return bool(status()["connected"])


def logout() -> None:
    secrets_store.delete(_STORE_KEY)
    _set_last_error("")
    _reset_clients()
    _logger.info("oauth.logout", provider="openai_oauth")


def _jwt_claims(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _account_id(token: str) -> str:
    claims = _jwt_claims(token)
    auth = claims.get("https://api.openai.com/auth") or {}
    return str(auth.get("chatgpt_account_id")
               or claims.get("chatgpt_account_id") or "")


def _expiring(token: str) -> bool:
    try:
        return time.time() >= float(_jwt_claims(token).get("exp")) \
            - _REFRESH_SKEW_S
    except (TypeError, ValueError):
        return True


def _exchange(code: str, verifier: str, redirect_uri: str) -> dict:
    import requests
    try:
        response = requests.post(TOKEN_URL, data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": redirect_uri, "client_id": CLIENT_ID,
            "code_verifier": verifier,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20)
    except Exception as exc:
        raise _error(f"tukar token gagal: {type(exc).__name__}",
                     "network") from exc
    if response.status_code != 200:
        raise _error(f"tukar token ditolak (HTTP {response.status_code})",
                     "provider_rejected")
    data = response.json()
    if not data.get("access_token"):
        raise _error("token exchange tanpa access_token", "provider_rejected")
    return data


def start_login(open_browser: bool = True, timeout_s: int = 300) -> dict:
    if not secrets_store.available():
        raise _error("backend penyimpanan terenkripsi tidak tersedia",
                     "provider_rejected")
    try:
        tokens = oauth_loopback.authorize(
            authorize_url=AUTHORIZE_URL, client_id=CLIENT_ID, scope=SCOPES,
            exchange=_exchange, ports=(1455, 1457),
            callback_path="/auth/callback", timeout_s=timeout_s,
            open_browser=open_browser,
            extra_params={"id_token_add_organizations": "true",
                          "codex_cli_simplified_flow": "true",
                          "originator": "codex_cli_rs"})
    except oauth_loopback.LoopbackOAuthError as exc:
        raise _error(str(exc), "provider_rejected") from exc
    stored = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "id_token": tokens.get("id_token", ""),
        "obtained_at": int(time.time()),
    }
    if not _save_tokens(stored):
        raise _error("token tidak dapat disimpan terenkripsi", "provider_rejected")
    _set_last_error("")
    _reset_clients()
    _logger.info("oauth.connected", provider="openai_oauth")
    return {"provider": "openai_oauth", "connected": True}


def access_token(force_refresh: bool = False) -> str:
    """Ambil access token, atau refresh sekali bila dipaksa oleh HTTP 401."""
    refreshed = False
    with _lock:
        tokens = _load_tokens()
        access = str(tokens.get("access_token") or "")
        refresh = str(tokens.get("refresh_token") or "")
        if access and not force_refresh and not _expiring(access):
            token = access
        else:
            if not refresh:
                raise _error("belum terhubung atau token kedaluwarsa; sign in ulang",
                             "reauth_required")
            import requests
            try:
                response = requests.post(TOKEN_URL, data={
                    "grant_type": "refresh_token", "refresh_token": refresh,
                    "client_id": CLIENT_ID,
                }, headers={"Content-Type": "application/x-www-form-urlencoded",
                            "User-Agent": _UA}, timeout=20)
            except Exception as exc:
                raise _error(f"refresh gagal: {type(exc).__name__}",
                             "network") from exc
            if response.status_code == 429:
                raise _error("OpenAI me-rate-limit refresh (429); coba lagi nanti",
                             "rate_limited")
            if response.status_code != 200:
                raise _error(f"refresh gagal (HTTP {response.status_code}); sign in ulang",
                             "reauth_required")
            data = response.json()
            if not data.get("access_token"):
                raise _error("refresh tanpa access_token; sign in ulang",
                             "reauth_required")
            tokens["access_token"] = data["access_token"]
            if data.get("refresh_token"):
                tokens["refresh_token"] = data["refresh_token"]
            if data.get("id_token"):
                tokens["id_token"] = data["id_token"]
            if not _save_tokens(tokens):
                raise _error("token refresh tidak dapat disimpan terenkripsi",
                             "provider_rejected")
            token = str(tokens["access_token"])
            refreshed = True
    if refreshed:
        _reset_clients()
    _set_last_error("")
    return token


def _headers(token: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}", "User-Agent": _UA,
        "originator": "codex_cli_rs", "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    tokens = _load_tokens()
    account = _account_id(str(tokens.get("id_token") or token))
    if account:
        headers["ChatGPT-Account-ID"] = account
    return headers


def _text_parts(content, role: str) -> list[dict]:
    text_type = "output_text" if role == "assistant" else "input_text"
    if isinstance(content, str):
        return [{"type": text_type, "text": content}]
    out = []
    for part in content or []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            out.append({"type": text_type, "text": str(part.get("text") or "")})
        elif role == "user" and part.get("type") == "image_url":
            ref = part.get("image_url") or {}
            url = ref.get("url") if isinstance(ref, dict) else ref
            if url:
                out.append({"type": "input_image", "image_url": url})
    return out


def _input_items(messages: list[dict]) -> tuple[str, list[dict]]:
    systems: list[str] = []
    items: list[dict] = []
    for message in messages:
        role = str(message.get("role") or "")
        if role == "system":
            systems.append(str(message.get("content") or ""))
        elif role in ("user", "assistant"):
            parts = _text_parts(message.get("content"), role)
            if parts:
                items.append({"role": role, "content": parts})
            if role == "assistant":
                for call in message.get("tool_calls") or []:
                    fn = call.get("function") or {}
                    args = fn.get("arguments", "{}")
                    if isinstance(args, dict):
                        args = json.dumps(args, ensure_ascii=False)
                    items.append({"type": "function_call",
                                  "call_id": str(call.get("id") or ""),
                                  "name": str(fn.get("name") or ""),
                                  "arguments": str(args or "{}")})
        elif role == "tool" and message.get("tool_call_id"):
            items.append({"type": "function_call_output",
                          "call_id": str(message["tool_call_id"]),
                          "output": str(message.get("content") or "")})
    return "\n\n".join(systems), items


def _response_tools(tools: list[dict] | None) -> list[dict]:
    out = []
    for item in tools or []:
        fn = item.get("function") or {}
        if fn.get("name"):
            out.append({"type": "function", "name": fn["name"],
                        "description": fn.get("description", ""),
                        "strict": False,
                        "parameters": fn.get("parameters") or
                        {"type": "object", "properties": {}}})
    return out


def _responses_request(payload: dict, timeout_s: float,
                       force_refresh: bool = False):
    import requests
    try:
        return requests.post(f"{CODEX_BASE}/responses",
                             headers=_headers(access_token(
                                 force_refresh=force_refresh)),
                             json=payload, timeout=timeout_s, stream=True)
    except OAuthError:
        raise
    except Exception as exc:
        raise _error(f"request Codex gagal: {type(exc).__name__}",
                     "network") from exc


def _response_error_code(response) -> str:
    """Klasifikasi respons tanpa menyimpan atau menampilkan body provider."""
    status_code = int(response.status_code)
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "network"
    if status_code == 404:
        try:
            body = response.json()
            error = body.get("error") if isinstance(body, dict) else {}
            error = error if isinstance(error, dict) else {}
            detail = " ".join(str(error.get(key) or "")
                              for key in ("code", "message")).lower()
            if "model" in detail and ("not_found" in detail or "not found" in detail):
                return "model_not_found"
        except Exception:                                  # noqa: BLE001
            pass
        return "not_found"
    return "provider_rejected"


def available_models(timeout_s: float = 20) -> list[str]:
    """Ambil katalog Codex yang diizinkan akun, tanpa menyimpan responsnya."""
    import requests
    try:
        response = requests.get(f"{CODEX_BASE}/models",
                                headers=_headers(access_token()),
                                timeout=timeout_s)
    except OAuthError:
        raise
    except Exception as exc:
        raise _error(f"catalog model gagal: {type(exc).__name__}",
                     "network") from exc
    if response.status_code != 200:
        raise _error(f"catalog model ditolak (HTTP {response.status_code})",
                     _response_error_code(response))
    try:
        body = response.json()
    except Exception as exc:
        raise _error("catalog model tidak valid", "provider_rejected") from exc
    entries = body.get("models", body.get("data", [])) if isinstance(body, dict) \
        else body
    if not isinstance(entries, list):
        raise _error("catalog model tidak valid", "provider_rejected")
    models: list[str] = []
    for entry in entries:
        if isinstance(entry, str):
            name = entry
        elif isinstance(entry, dict):
            if entry.get("supported_in_api") is False:
                continue
            name = str(entry.get("id") or entry.get("slug") or
                       entry.get("model") or "")
        else:
            continue
        if name and name not in models:
            models.append(name)
    return models


_IMAGE_TOOL_TYPE = "image_generation"
_IMAGE_MODEL = "gpt-image-2"
# Model routing yang mengeksekusi built-in tool image_generation. Codex OAuth
# menolak request tanpa mainline model yang mendukung pemanggilan tool ini.
_IMAGE_ROUTER_MODEL = "gpt-5.5"
_IMAGE_INSTRUCTIONS = (
    "Use the image_generation tool when the user asks to draw, create, "
    "generate, or edit an image.")
# quality label UI → reasoning effort Codex (persis 3 tier gpt-image-2)
IMAGE_QUALITY_EFFORT: dict[str, str] = {
    "low": "low", "medium": "medium", "high": "high"}


def image_generation_supported() -> bool:
    """OAuth Codex menyediakan capability image lewat built-in tool bila
    akun terhubung. Fail-closed saat belum sign in."""
    return connected()


def build_image_payload(prompt: str, *, size: str = "auto",
                        output_format: str = "png",
                        background: str = "auto",
                        quality: str = "medium",
                        router_model: str = "") -> dict:
    """Payload Responses untuk built-in tool image_generation (kontrak Codex).

    Tidak melakukan I/O; dipisah agar dapat diverifikasi lewat unit test tanpa
    memanggil endpoint berbayar."""
    if background == "transparent":
        raise _error("gpt-image-2 tidak mendukung background transparan",
                     "provider_rejected")
    tool = {"type": _IMAGE_TOOL_TYPE, "model": _IMAGE_MODEL,
            "size": size or "auto", "output_format": output_format or "png",
            "background": background or "auto"}
    payload: dict = {
        "model": router_model or _IMAGE_ROUTER_MODEL,
        "instructions": _IMAGE_INSTRUCTIONS,
        "input": [{"role": "user",
                   "content": [{"type": "input_text", "text": prompt}]}],
        "tools": [tool],
        "tool_choice": {"type": _IMAGE_TOOL_TYPE},
        "stream": True, "store": False,
    }
    effort = IMAGE_QUALITY_EFFORT.get(str(quality or "").lower())
    if effort:
        payload["reasoning"] = {"effort": effort}
    return payload


def parse_image_events(response) -> list[bytes]:
    """Ekstrak base64 gambar dari SSE Codex; tidak menyimpan body mentah.

    Dua sumber sesuai kontrak: item terminal ``image_generation_call.result``
    dan event delta ``response.image_generation_call.partial_image``.
    """
    import base64
    finals: list[bytes] = []
    partials: dict[int, bytes] = {}
    saw_terminal = False
    for raw in response.iter_lines():
        line = raw.decode("utf-8", errors="replace") \
            if isinstance(raw, bytes) else str(raw)
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if not body or body == "[DONE]":
            continue
        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            continue
        etype = str(event.get("type") or "")
        if etype == "error":
            raise _error("Codex image stream mengembalikan error",
                         "provider_rejected")
        if etype.endswith("image_generation_call.partial_image"):
            b64 = str(event.get("partial_image_b64") or "")
            if b64:
                try:
                    partials[int(event.get("partial_image_index", 0))] = \
                        base64.b64decode(b64, validate=True)
                except Exception:                          # noqa: BLE001
                    pass
        elif etype == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == _IMAGE_TOOL_TYPE + "_call":
                result = str(item.get("result") or "")
                if result:
                    try:
                        finals.append(base64.b64decode(result, validate=True))
                    except Exception as exc:               # noqa: BLE001
                        raise _error("hasil image bukan base64 valid",
                                     "provider_rejected") from exc
        elif etype in ("response.completed", "response.incomplete",
                       "response.failed"):
            saw_terminal = True
            final = event.get("response") or {}
            for item in final.get("output") or []:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == _IMAGE_TOOL_TYPE + "_call":
                    result = str(item.get("result") or "")
                    if result:
                        try:
                            finals.append(
                                base64.b64decode(result, validate=True))
                        except Exception as exc:           # noqa: BLE001
                            raise _error("hasil image bukan base64 valid",
                                         "provider_rejected") from exc
    if finals:
        return finals
    if not saw_terminal:
        raise _error("Codex image stream berakhir tanpa status final",
                     "provider_rejected")
    if partials:
        return [partials[max(partials)]]
    raise _error("Codex tidak mengembalikan hasil image", "provider_rejected")


def generate_image(prompt: str, *, size: str = "auto",
                   output_format: str = "png", background: str = "auto",
                   quality: str = "medium", timeout_s: float = 300) -> list[bytes]:
    """Generate gambar via Codex OAuth Responses built-in tool image_generation.

    Return list bytes PNG/format; caller menyimpan ke disk. Refresh + retry 401
    sekali persis seperti jalur chat.
    """
    import requests
    payload = build_image_payload(prompt, size=size, output_format=output_format,
                                  background=background, quality=quality)

    def _post(force_refresh: bool = False):
        try:
            return requests.post(
                f"{CODEX_BASE}/responses",
                headers=_headers(access_token(force_refresh=force_refresh)),
                json=payload, timeout=timeout_s, stream=True)
        except OAuthError:
            raise
        except Exception as exc:                           # noqa: BLE001
            raise _error(f"request image Codex gagal: {type(exc).__name__}",
                         "network") from exc

    response = _post()
    if response.status_code == 401:
        response = _post(force_refresh=True)
    if response.status_code == 401:
        raise _error("token OpenAI ditolak (401); sign in ulang",
                     "reauth_required")
    if response.status_code != 200:
        code = _response_error_code(response)
        if code == "model_not_found":
            raise _error("model image Codex tidak tersedia untuk akun ini", code)
        raise _error(f"Codex menolak image request (HTTP {response.status_code})",
                     code)
    images = parse_image_events(response)
    _set_last_error("")
    return images


def chat(messages: list[dict], tools: list[dict] | None, model: str,
         timeout_s: float, json_mode: bool = False) -> dict:
    """Panggil Codex Responses dan normalkan ke kontrak LLMClient."""
    instructions, input_items = _input_items(messages)
    if json_mode:
        instructions = (instructions + "\n\n" if instructions else "") \
            + "Jawab hanya dengan satu objek JSON valid tanpa markdown."
    payload: dict = {"model": model, "instructions": instructions,
                     "input": input_items, "store": False, "stream": True}
    converted = _response_tools(tools)
    if converted:
        payload.update({"tools": converted, "tool_choice": "auto",
                        "parallel_tool_calls": True})
    response = _responses_request(payload, timeout_s)
    if response.status_code == 401:
        # Token dapat dicabut di server walau klaim JWT lokal belum kadaluarsa.
        # Refresh lalu ulang request asli sekali, dan tidak pernah lebih dari itu.
        response = _responses_request(payload, timeout_s, force_refresh=True)
    if response.status_code == 401:
        raise _error("token OpenAI ditolak (401); sign in ulang",
                     "reauth_required")
    if response.status_code != 200:
        code = _response_error_code(response)
        if code == "model_not_found":
            raise _error("model Codex tidak tersedia untuk akun ini; "
                         "sinkronkan lalu pilih model OAuth", code)
        raise _error(f"Codex menolak request (HTTP {response.status_code})",
                     code)
    text_parts: list[str] = []
    calls: list[dict] = []
    usage: dict = {}
    status = "completed"
    saw_event = False
    saw_terminal = False
    malformed = False
    for raw in response.iter_lines():
        line = raw.decode("utf-8", errors="replace") \
            if isinstance(raw, bytes) else str(raw)
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if not body or body == "[DONE]":
            continue
        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            malformed = True
            continue
        saw_event = True
        etype = str(event.get("type") or "")
        if etype == "error":
            raise _error("Codex stream mengembalikan error", "provider_rejected")
        if etype == "response.output_text.delta" and event.get("delta"):
            text_parts.append(str(event["delta"]))
        elif etype == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                calls.append({"id": str(item.get("call_id") or item.get("id") or ""),
                              "name": str(item.get("name") or ""),
                              "arguments": item.get("arguments") or "{}"})
        elif etype in ("response.completed", "response.incomplete",
                       "response.failed"):
            saw_terminal = True
            final = event.get("response") or {}
            status = str(final.get("status") or etype.removeprefix("response."))
            raw_usage = final.get("usage") or {}
            usage = {"prompt_tokens": raw_usage.get("input_tokens", 0),
                     "completion_tokens": raw_usage.get("output_tokens", 0)}
    if not saw_terminal:
        if malformed and not saw_event:
            raise _error("Codex stream tidak valid", "provider_rejected")
        raise _error("Codex stream berakhir tanpa status final", "provider_rejected")
    if status != "completed":
        raise _error("Codex tidak menyelesaikan response", "provider_rejected")
    _set_last_error("")
    return {"content": "".join(text_parts) or None, "tool_calls": calls,
            "usage": usage,
            "stop_reason": "tool_calls" if calls else status}
