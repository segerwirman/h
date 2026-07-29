"""Fase 6: OpenAI OAuth PKCE storage, refresh, dan adapter chat Codex."""
from __future__ import annotations

import base64
import json
import sys
import time
import types

import pytest

from jarvis.core import secrets_store
from jarvis.integrations import openai_oauth as oa


@pytest.fixture()
def store(monkeypatch):
    data: dict[str, str] = {}
    monkeypatch.setattr(secrets_store, "available", lambda: True)
    monkeypatch.setattr(secrets_store, "get", lambda key: data.get(key))
    monkeypatch.setattr(secrets_store, "set",
                        lambda key, value: (data.__setitem__(key, value), True)[1])
    monkeypatch.setattr(secrets_store, "delete",
                        lambda key: (data.pop(key, None), True)[1])
    return data


def _jwt(payload: dict) -> str:
    def enc(data):
        return base64.urlsafe_b64encode(
            json.dumps(data).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'none'})}.{enc(payload)}.sig"


class _Resp:
    def __init__(self, status=200, body=None, lines=None):
        self.status_code = status
        self._body = body or {}
        self._lines = lines or []

    def json(self):
        return self._body

    def iter_lines(self):
        return iter(self._lines)


def _fake_requests(monkeypatch, handler):
    monkeypatch.setitem(sys.modules, "requests",
                        types.SimpleNamespace(post=handler))


def test_login_menyimpan_token_dan_provider_enabled(store, monkeypatch):
    resets = []
    monkeypatch.setattr(oa, "_reset_clients", lambda: resets.append("reset"),
                        raising=False)
    monkeypatch.setattr(oa.oauth_loopback, "authorize", lambda **kwargs: {
        "access_token": _jwt({"exp": time.time() + 3600}),
        "refresh_token": "refresh", "id_token": _jwt({
            "chatgpt_account_id": "account"})})
    assert oa.start_login(open_browser=False)["connected"] is True
    assert oa.connected() is True
    saved = json.loads(store[oa._STORE_KEY])
    assert saved["refresh_token"] == "refresh"
    oa.logout()
    assert oa.connected() is False
    assert resets == ["reset", "reset"]


def test_access_token_refresh_rotasi(store, monkeypatch):
    store[oa._STORE_KEY] = json.dumps({
        "access_token": _jwt({"exp": 0}), "refresh_token": "old"})
    fresh = _jwt({"exp": time.time() + 3600})
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs["data"]))
        return _Resp(body={"access_token": fresh, "refresh_token": "new"})

    _fake_requests(monkeypatch, post)
    assert oa.access_token() == fresh
    assert calls[0][0] == oa.TOKEN_URL
    assert json.loads(store[oa._STORE_KEY])["refresh_token"] == "new"


def test_chat_codex_responses_normalisasi(store, monkeypatch):
    store[oa._STORE_KEY] = json.dumps({
        "access_token": _jwt({"exp": time.time() + 3600,
                              "chatgpt_account_id": "acc"}),
        "refresh_token": "refresh"})
    captured = {}
    events = [
        {"type": "response.output_text.delta", "delta": "Siap."},
        {"type": "response.output_item.done", "item": {
            "type": "function_call", "call_id": "call_1",
            "name": "read_file", "arguments": '{"path":"x"}'}},
        {"type": "response.completed", "response": {
            "status": "completed", "usage": {
                "input_tokens": 10, "output_tokens": 4}}},
    ]

    def post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return _Resp(lines=[f"data: {json.dumps(e)}".encode() for e in events])

    _fake_requests(monkeypatch, post)
    result = oa.chat(
        [{"role": "system", "content": "persona"},
         {"role": "user", "content": "baca"}],
        [{"type": "function", "function": {"name": "read_file",
          "description": "baca", "parameters": {"type": "object"}}}],
        "gpt-test", 30)
    assert captured["url"] == f"{oa.CODEX_BASE}/responses"
    assert captured["headers"]["originator"] == "codex_cli_rs"
    assert captured["json"]["instructions"] == "persona"
    assert captured["json"]["tools"][0]["name"] == "read_file"
    assert result["content"] == "Siap."
    assert result["tool_calls"][0]["id"] == "call_1"
    assert result["usage"] == {"prompt_tokens": 10,
                                "completion_tokens": 4}


def test_image_oauth_diiklankan_saat_terhubung(monkeypatch):
    from jarvis.core import settings_service
    monkeypatch.setattr(oa, "image_generation_supported", lambda: True)
    sections = {s["id"]: s for s in settings_service.sections()}
    fields = {f["key"]: f for f in sections["image"]["fields"]}
    assert "openai_oauth" in fields["image_generation.provider"]["choices"]
    assert "Codex OAuth" in sections["image"]["hint"]
    quality = fields["image_generation.quality"]["choices"]
    assert {"low", "medium", "high"} <= set(quality)


def test_build_image_payload_kontrak_codex_tool():
    payload = oa.build_image_payload("kucing astronot", size="1024x1024",
                                     quality="high")
    assert payload["model"] == oa._IMAGE_ROUTER_MODEL
    assert payload["tool_choice"] == {"type": "image_generation"}
    assert payload["stream"] is True and payload["store"] is False
    tool = payload["tools"][0]
    assert tool["type"] == "image_generation"
    assert tool["model"] == "gpt-image-2"
    assert tool["size"] == "1024x1024"
    assert payload["reasoning"] == {"effort": "high"}
    content = payload["input"][0]["content"][0]
    assert content == {"type": "input_text", "text": "kucing astronot"}


def test_build_image_payload_menolak_background_transparan():
    with pytest.raises(oa.OAuthError):
        oa.build_image_payload("x", background="transparent")


def test_parse_image_events_ekstrak_base64_dari_output_item():
    png = base64.b64encode(b"PNGDATA").decode()
    resp = _Resp(lines=[
        b'data: {"type":"response.output_item.done","item":'
        b'{"type":"image_generation_call","result":"' + png.encode() + b'"}}',
        b'data: {"type":"response.completed","response":{"output":[]}}',
        b"data: [DONE]",
    ])
    out = oa.parse_image_events(resp)
    assert out == [b"PNGDATA"]


def test_generate_image_end_to_end_via_oauth(store, monkeypatch):
    store[oa._STORE_KEY] = json.dumps({
        "access_token": _jwt({"exp": time.time() + 3600,
                              "chatgpt_account_id": "acc"}),
        "refresh_token": "refresh"})
    png = base64.b64encode(b"IMG").decode()
    captured = {}

    def post(url, **kwargs):
        captured["url"] = url
        captured["payload"] = kwargs.get("json")
        return _Resp(lines=[
            b'data: {"type":"response.completed","response":{"output":[{'
            b'"type":"image_generation_call","result":"' + png.encode()
            + b'"}]}}',
        ])

    _fake_requests(monkeypatch, post)
    out = oa.generate_image("robot", size="512x512", quality="low")
    assert out == [b"IMG"]
    assert captured["url"].endswith("/responses")
    assert captured["payload"]["tools"][0]["type"] == "image_generation"
    assert captured["payload"]["reasoning"] == {"effort": "low"}


def test_image_oauth_tidak_diiklankan_saat_belum_login(monkeypatch):
    from jarvis.core import settings_service
    from jarvis.agent import providers as prov
    monkeypatch.setattr(oa, "image_generation_supported", lambda: False)
    monkeypatch.setattr(prov, "_oauth_connected", lambda _name: False)
    sections = {s["id"]: s for s in settings_service.sections()}
    fields = {f["key"]: f for f in sections["image"]["fields"]}
    assert "openai_oauth" not in fields["image_generation.provider"]["choices"]


def test_status_oauth_aman_dan_tidak_membocorkan_token(store):
    access = _jwt({"exp": time.time() + 3600})
    store[oa._STORE_KEY] = json.dumps({
        "access_token": access, "refresh_token": "refresh-rahasia",
        "id_token": "id-rahasia"})

    status = oa.status()

    assert set(status) == {"connected", "needs_reauth", "token_refresh_due",
                           "last_error_code"}
    assert status["connected"] is True
    assert status["needs_reauth"] is False
    assert status["token_refresh_due"] is False
    assert "rahasia" not in str(status)
    assert access not in str(status)


def test_chat_401_memaksa_refresh_dan_retry_tepat_satu_kali(store, monkeypatch):
    old = _jwt({"exp": time.time() + 3600})
    fresh = _jwt({"exp": time.time() + 7200})
    store[oa._STORE_KEY] = json.dumps({
        "access_token": old, "refresh_token": "refresh"})
    response_tokens = []
    resets = []
    monkeypatch.setattr(oa, "_reset_clients", lambda: resets.append("reset"),
                        raising=False)

    def post(url, **kwargs):
        if url == oa.TOKEN_URL:
            return _Resp(body={"access_token": fresh})
        assert url == f"{oa.CODEX_BASE}/responses"
        token = kwargs["headers"]["Authorization"]
        response_tokens.append(token)
        if len(response_tokens) == 1:
            return _Resp(status=401)
        return _Resp(lines=[b'data: {"type":"response.completed",'
                           b'"response":{"status":"completed"}}'])

    _fake_requests(monkeypatch, post)
    result = oa.chat([{"role": "user", "content": "uji"}], None,
                     "gpt-test", 30)

    assert result["stop_reason"] == "completed"
    assert response_tokens == [f"Bearer {old}", f"Bearer {fresh}"]
    assert resets == ["reset"]
    assert oa.status()["last_error_code"] == ""


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [(_Resp(status=429), "rate_limited"),
     (_Resp(lines=[b"data: {bukan-json"]), "provider_rejected"),
     (_Resp(lines=[b'data: {"type":"response.incomplete",'
                   b'"response":{"status":"incomplete"}}']),
      "provider_rejected")],
)
def test_chat_error_diklasifikasikan_tanpa_detail_rahasia(
        store, monkeypatch, response, expected_code):
    store[oa._STORE_KEY] = json.dumps({
        "access_token": _jwt({"exp": time.time() + 3600}),
        "refresh_token": "refresh-rahasia"})
    _fake_requests(monkeypatch, lambda *_args, **_kwargs: response)

    with pytest.raises(oa.OAuthError):
        oa.chat([{"role": "user", "content": "uji"}], None,
                "gpt-test", 30)

    status = oa.status()
    assert status["last_error_code"] == expected_code
    assert "rahasia" not in str(status)


def test_chat_404_model_not_found_mengarahkan_pemilihan_model(store, monkeypatch):
    store[oa._STORE_KEY] = json.dumps({
        "access_token": _jwt({"exp": time.time() + 3600}),
        "refresh_token": "refresh-rahasia"})
    _fake_requests(monkeypatch, lambda *_args, **_kwargs: _Resp(
        status=404, body={"error": {"code": "model_not_found"}}))

    with pytest.raises(oa.OAuthError, match="model"):
        oa.chat([{"role": "user", "content": "uji"}], None,
                "gpt-kedaluwarsa", 30)

    assert oa.status()["last_error_code"] == "model_not_found"


def test_catalog_model_oauth_hanya_mengekspos_model_yang_didukung(store, monkeypatch):
    store[oa._STORE_KEY] = json.dumps({
        "access_token": _jwt({"exp": time.time() + 3600}),
        "refresh_token": "refresh"})

    def get(url, **kwargs):
        assert url == f"{oa.CODEX_BASE}/models"
        assert kwargs["headers"]["Authorization"].startswith("Bearer ")
        return _Resp(body={"models": [
            {"id": "gpt-available", "supported_in_api": True},
            {"id": "gpt-hidden", "supported_in_api": False},
            {"slug": "gpt-legacy"},
        ]})

    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=get))

    assert oa.available_models() == ["gpt-available", "gpt-legacy"]
