"""Klien LLM terpadu untuk agent — openai_compat | anthropic | gemini.

Format kanonik pesan = gaya OpenAI chat.completions:

  {"role": "system"|"user"|"assistant"|"tool", "content": str|list,
   "tool_calls": [...], "tool_call_id": "..."}

Klien mengonversi ke format native provider saat memanggil. Semua panggilan
BLOCKING (jalankan lewat ``asyncio.to_thread`` / worker thread), tidak pernah
raise ke pemanggil biasa — kegagalan menjadi ``ChatResponse(error=...)``.
"""
from __future__ import annotations

import base64
import copy
import json
import threading
import time
from dataclasses import dataclass, field

from jarvis.core import config, log
from jarvis.agent.providers import Provider, get_provider, vision_provider

_logger = log.get("agent.llm")

_clients: dict[tuple, object] = {}
_clients_lock = threading.Lock()


def reset() -> None:
    """Buang cache klien — perubahan provider berlaku tanpa restart."""
    with _clients_lock:
        _clients.clear()
    _logger.info("agent.llm.reset")


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    error: str | None = None
    usage: dict = field(default_factory=dict)
    stop_reason: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None


class LLMClient:
    """Satu instance per provider; dapatkan lewat ``client()``/``vision_client()``."""

    def __init__(self, provider: Provider):
        self.provider = provider
        self.timeout_s = float(config.get("agent.request_timeout_s", 120))
        self._sdk = None
        self._sdk_lock = threading.Lock()
        self._embed_unavailable_until = 0.0

    # ── konstruksi SDK per kind ───────────────────────────────────────────

    def _client(self):
        with self._sdk_lock:
            if self._sdk is not None:
                return self._sdk
            p = self.provider
            if p.kind == "openai_compat":
                from openai import OpenAI
                self._sdk = OpenAI(
                    api_key=p.api_key or "not-needed",
                    base_url=p.base_url or None,
                    timeout=self.timeout_s, max_retries=0)
            elif p.kind in ("anthropic", "anthropic_oauth"):
                import anthropic
                if p.kind == "anthropic_oauth":
                    from jarvis.integrations import anthropic_oauth
                    kwargs = anthropic_oauth.client_kwargs()
                    kwargs.update({"timeout": self.timeout_s,
                                   "max_retries": 0})
                else:
                    kwargs = {"api_key": p.api_key,
                              "timeout": self.timeout_s, "max_retries": 0}
                if p.base_url:
                    kwargs["base_url"] = p.base_url
                self._sdk = anthropic.Anthropic(**kwargs)
            elif p.kind == "openai_oauth":
                # Responses OAuth memakai requests langsung; tidak ada SDK
                # singleton yang perlu dibuat.
                self._sdk = object()
            elif p.kind == "gemini":
                from google import genai
                from google.genai import types as gtypes
                # tanpa http_options, request bisa menggantung bermenit-menit
                self._sdk = genai.Client(
                    api_key=p.api_key,
                    http_options=gtypes.HttpOptions(
                        timeout=int(self.timeout_s * 1000)))
            else:
                raise ValueError(f"provider kind tidak dikenal: {p.kind}")
            return self._sdk

    def available(self) -> bool:
        return self.provider.configured()

    # ── API utama ─────────────────────────────────────────────────────────

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             json_mode: bool = False, temperature: float | None = None,
             max_tokens: int | None = None) -> ChatResponse:
        """``tools`` = daftar schema gaya OpenAI:
        {"type":"function","function":{"name","description","parameters"}}."""
        if not self.available():
            return ChatResponse(error="provider belum dikonfigurasi "
                                      f"({self.provider.name})")
        attempts = int(config.get("agent.llm_retries", 2)) + 1
        delay = 1.5
        last = "unknown"
        for i in range(attempts):
            try:
                if self.provider.kind == "openai_compat":
                    return self._chat_openai(messages, tools, json_mode,
                                             temperature, max_tokens)
                if self.provider.kind == "openai_oauth":
                    return self._chat_openai_oauth(messages, tools, json_mode)
                if self.provider.kind in ("anthropic", "anthropic_oauth"):
                    return self._chat_anthropic(messages, tools, json_mode,
                                                temperature, max_tokens)
                return self._chat_gemini(messages, tools, json_mode,
                                         temperature, max_tokens)
            except Exception as e:                           # noqa: BLE001
                last = f"{type(e).__name__}: {str(e)[:300]}"
                if i < attempts - 1 and _transient(e):
                    _logger.warning("agent.llm.retry", attempt=i + 1,
                                    error=last[:120])
                    time.sleep(delay)
                    delay *= 2
                    continue
                break
        _logger.error("agent.llm.chat_failed", provider=self.provider.name,
                      error=last[:200])
        return ChatResponse(error=last)

    def _chat_openai_oauth(self, messages, tools,
                           json_mode: bool) -> ChatResponse:
        from jarvis.integrations import openai_oauth

        result = openai_oauth.chat(messages, tools, self.provider.model,
                                   self.timeout_s, json_mode=json_mode)
        calls = [ToolCall(id=str(item.get("id") or f"call_{index}"),
                          name=str(item.get("name") or ""),
                          arguments=_parse_args(item.get("arguments", "{}")))
                 for index, item in enumerate(result.get("tool_calls") or [])]
        return ChatResponse(content=result.get("content"), tool_calls=calls,
                            usage=result.get("usage") or {},
                            stop_reason=str(result.get("stop_reason") or ""))

    def generate(self, prompt: str, system: str | None = None,
                 json_mode: bool = False) -> str:
        """Single-shot sederhana. '' saat gagal (pola jarvis.core.llm)."""
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        r = self.chat(msgs, json_mode=json_mode)
        return (r.content or "").strip() if r.ok else ""

    def vision(self, image_bytes: bytes, mime_type: str, prompt: str,
               json_mode: bool = False) -> str:
        """Analisis satu gambar → teks. '' saat gagal."""
        b64 = base64.b64encode(image_bytes).decode("ascii")
        content = [
            {"type": "image_url",
             "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]
        model = self.provider.resolve_vision_model()
        r = self.chat([{"role": "user", "content": content}],
                      json_mode=json_mode, max_tokens=2048)
        if not r.ok:
            _logger.error("agent.llm.vision_failed", model=model,
                          error=(r.error or "")[:160])
            return ""
        return (r.content or "").strip()

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        """Embedding untuk memory store. None bila provider tak mendukung.

        Kontrak: **satu vektor per satu teks, urut posisi** — pemanggil
        (``memory_store``) menyandingkan keduanya berdasarkan indeks. Vektor
        yang lebih sedikit dari teks berarti memori mendapat vektor milik
        memori lain, dan pencarian semantik jadi salah tanpa satu pun error.

        Temuan S-10: google-genai 2.14.0 dengan ``gemini-embedding-2``
        mengembalikan **satu** embedding untuk banyak ``contents``. Karena itu
        paritas diperiksa, lalu dipulihkan dengan permintaan per teks. Bila
        paritas tetap tidak tercapai, kembalikan ``None`` — hasil sebagian
        lebih berbahaya daripada tidak ada hasil.
        """
        if time.monotonic() < self._embed_unavailable_until:
            return None
        if not texts:
            return []
        try:
            vectors = self._embed_batch(texts)
            if vectors is not None and len(vectors) != len(texts):
                # Fallback paritas: satu permintaan per teks.
                recovered: list[list[float]] = []
                for text in texts:
                    single = self._embed_batch([text])
                    if not single or len(single) != 1:
                        recovered = []
                        break
                    recovered.append(single[0])
                vectors = recovered or None
            if vectors is None or len(vectors) != len(texts):
                _logger.warning("agent.llm.embed_parity_failed",
                                requested=len(texts),
                                returned=0 if vectors is None else len(vectors))
                return None
            self._embed_unavailable_until = 0.0
            return vectors
        except Exception as e:                               # noqa: BLE001
            cooldown = max(30.0, float(config.get(
                "agent.embedding_failure_cooldown_s", 900)))
            self._embed_unavailable_until = time.monotonic() + cooldown
            _logger.warning("agent.llm.embed_failed", error=str(e)[:120])
        return None

    def _embed_batch(self, texts: list[str]) -> list[list[float]] | None:
        """Satu permintaan embedding mentah; paritas diurus ``embed()``."""
        if self.provider.kind == "gemini":
            from google.genai import types as gtypes

            res = self._client().models.embed_content(
                model=str(config.get("agent.embedding_model",
                                     "gemini-embedding-2")),
                contents=texts,
                config=gtypes.EmbedContentConfig(
                    output_dimensionality=int(config.get(
                        "agent.embedding_dimensions", 768)),
                ),
            )
            return [list(e.values) for e in res.embeddings]
        if self.provider.kind == "openai_compat":
            res = self._client().embeddings.create(
                model=str(config.get("agent.embedding_model_openai",
                                     "text-embedding-3-small")),
                input=texts)
            return [list(d.embedding) for d in res.data]
        return None

    # ── openai_compat ─────────────────────────────────────────────────────

    def _chat_openai(self, messages, tools, json_mode, temperature,
                     max_tokens) -> ChatResponse:
        kwargs: dict = {"model": self.provider.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = self._client().chat.completions.create(**kwargs)
        except Exception:
            if not json_mode:
                raise
            # server lokal lama kadang tak kenal response_format → ulang tanpa
            kwargs.pop("response_format", None)
            resp = self._client().chat.completions.create(**kwargs)

        choice = resp.choices[0]
        msg = choice.message
        calls: list[ToolCall] = []
        for tc in (msg.tool_calls or []):
            calls.append(ToolCall(
                id=tc.id or f"call_{len(calls)}",
                name=tc.function.name,
                arguments=_parse_args(tc.function.arguments)))
        usage = {}
        if getattr(resp, "usage", None):
            usage = {"prompt_tokens": resp.usage.prompt_tokens,
                     "completion_tokens": resp.usage.completion_tokens}
        return ChatResponse(content=msg.content, tool_calls=calls,
                            usage=usage,
                            stop_reason=choice.finish_reason or "")

    # ── anthropic ─────────────────────────────────────────────────────────

    def _chat_anthropic(self, messages, tools, json_mode, temperature,
                        max_tokens) -> ChatResponse:
        system_parts: list[str] = []
        out: list[dict] = []
        for m in messages:
            role, content = m["role"], m.get("content")
            if role == "system":
                system_parts.append(_text_of(content))
            elif role == "tool":
                block = {"type": "tool_result",
                         "tool_use_id": m.get("tool_call_id", ""),
                         "content": _text_of(content)}
                # hasil tool beruntun harus bergabung dalam satu pesan user
                if out and out[-1]["role"] == "user" and isinstance(
                        out[-1]["content"], list) and out[-1]["content"] and \
                        out[-1]["content"][0].get("type") == "tool_result":
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
            elif role == "assistant":
                blocks: list[dict] = []
                if content:
                    blocks.append({"type": "text", "text": _text_of(content)})
                for tc in m.get("tool_calls") or []:
                    fn = tc.get("function", {})
                    blocks.append({
                        "type": "tool_use", "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": _parse_args(fn.get("arguments", "{}"))})
                out.append({"role": "assistant",
                            "content": blocks or [{"type": "text", "text": ""}]})
            else:                                            # user
                out.append({"role": "user",
                            "content": _anthropic_user_content(content)})

        if json_mode:
            system_parts.append("Jawab HANYA dengan satu objek JSON valid, "
                                "tanpa teks lain, tanpa pagar kode.")
        kwargs: dict = {
            "model": self.provider.model,
            "max_tokens": max_tokens or int(
                config.get("agent.max_output_tokens", 8192)),
            "messages": out,
        }
        if system_parts:
            kwargs["system"] = "\n\n".join(system_parts)
        if temperature is not None:
            kwargs["temperature"] = temperature
        if tools:
            kwargs["tools"] = [{
                "name": t["function"]["name"],
                "description": t["function"].get("description", ""),
                "input_schema": t["function"].get(
                    "parameters", {"type": "object", "properties": {}}),
            } for t in tools]

        resp = self._client().messages.create(**kwargs)
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name,
                                      arguments=dict(block.input or {})))
        usage = {}
        if getattr(resp, "usage", None):
            usage = {"prompt_tokens": resp.usage.input_tokens,
                     "completion_tokens": resp.usage.output_tokens}
        return ChatResponse(content="\n".join(text_parts) or None,
                            tool_calls=calls, usage=usage,
                            stop_reason=resp.stop_reason or "")

    # ── gemini ────────────────────────────────────────────────────────────

    def _chat_gemini(self, messages, tools, json_mode, temperature,
                     max_tokens) -> ChatResponse:
        from google.genai import types

        system_parts: list[str] = []
        contents: list = []
        # peta id panggilan → nama fungsi (function_response butuh nama)
        call_names: dict[str, str] = {}
        for m in messages:
            for tc in m.get("tool_calls") or []:
                call_names[tc.get("id", "")] = \
                    tc.get("function", {}).get("name", "")

        for m in messages:
            role, content = m["role"], m.get("content")
            if role == "system":
                system_parts.append(_text_of(content))
            elif role == "assistant":
                parts = []
                if content:
                    parts.append(types.Part(text=_text_of(content)))
                for tc in m.get("tool_calls") or []:
                    fn = tc.get("function", {})
                    parts.append(types.Part(
                        function_call=types.FunctionCall(
                            name=fn.get("name", ""),
                            args=_parse_args(fn.get("arguments", "{}")))))
                if parts:
                    contents.append(types.Content(role="model", parts=parts))
            elif role == "tool":
                name = call_names.get(m.get("tool_call_id", ""), "tool")
                contents.append(types.Content(role="user", parts=[
                    types.Part.from_function_response(
                        name=name,
                        response={"result": _text_of(content)})]))
            else:                                            # user
                contents.append(types.Content(
                    role="user", parts=_gemini_user_parts(content, types)))

        gen_cfg: dict = {}
        if system_parts:
            gen_cfg["system_instruction"] = "\n\n".join(system_parts)
        if temperature is not None:
            gen_cfg["temperature"] = temperature
        if max_tokens:
            gen_cfg["max_output_tokens"] = max_tokens
        if json_mode:
            gen_cfg["response_mime_type"] = "application/json"
        if tools:
            decls = [types.FunctionDeclaration(
                name=t["function"]["name"],
                description=t["function"].get("description", ""),
                parameters=_gemini_schema(t["function"].get("parameters")))
                for t in tools]
            gen_cfg["tools"] = [types.Tool(function_declarations=decls)]
            # matikan "thinking hidden call" otomatis — kita loop manual
            gen_cfg["automatic_function_calling"] = \
                types.AutomaticFunctionCallingConfig(disable=True)

        resp = self._client().models.generate_content(
            model=self.provider.model, contents=contents,
            config=types.GenerateContentConfig(**gen_cfg) if gen_cfg else None)

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        cand = (resp.candidates or [None])[0]
        if cand is not None and cand.content is not None:
            for part in (cand.content.parts or []):
                if getattr(part, "function_call", None) is not None:
                    fc = part.function_call
                    calls.append(ToolCall(
                        id=f"call_{len(calls)}_{fc.name}",
                        name=fc.name or "",
                        arguments=dict(fc.args or {})))
                elif getattr(part, "text", None):
                    text_parts.append(part.text)
        usage = {}
        if getattr(resp, "usage_metadata", None) is not None:
            usage = {
                "prompt_tokens": resp.usage_metadata.prompt_token_count or 0,
                "completion_tokens":
                    resp.usage_metadata.candidates_token_count or 0}
        stop = ""
        if cand is not None and getattr(cand, "finish_reason", None):
            stop = str(cand.finish_reason)
        return ChatResponse(content="\n".join(text_parts) or None,
                            tool_calls=calls, usage=usage, stop_reason=stop)


# ── helpers ───────────────────────────────────────────────────────────────

def _parse_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {"value": v}
    except (json.JSONDecodeError, TypeError):
        return {"_raw": str(raw)[:2000]}


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content
                         if isinstance(p, dict) and p.get("type") == "text")
    return str(content or "")


def _split_data_url(url: str) -> tuple[str, str]:
    """data:mime;base64,payload → (mime, b64)."""
    head, _, payload = url.partition(",")
    mime = head.removeprefix("data:").removesuffix(";base64") or "image/jpeg"
    return mime, payload


def _anthropic_user_content(content):
    if isinstance(content, str):
        return content
    blocks = []
    for p in content or []:
        if p.get("type") == "text":
            blocks.append({"type": "text", "text": p.get("text", "")})
        elif p.get("type") == "image_url":
            mime, b64 = _split_data_url(p["image_url"]["url"])
            blocks.append({"type": "image", "source": {
                "type": "base64", "media_type": mime, "data": b64}})
    return blocks or [{"type": "text", "text": ""}]


def _gemini_user_parts(content, types):
    if isinstance(content, str):
        return [types.Part(text=content)]
    parts = []
    for p in content or []:
        if p.get("type") == "text":
            parts.append(types.Part(text=p.get("text", "")))
        elif p.get("type") == "image_url":
            mime, b64 = _split_data_url(p["image_url"]["url"])
            parts.append(types.Part.from_bytes(
                data=base64.b64decode(b64), mime_type=mime))
    return parts or [types.Part(text="")]


_GEMINI_ALLOWED = {"type", "properties", "required", "items", "enum",
                   "description", "nullable", "format", "anyOf"}


def _gemini_schema(schema: dict | None) -> dict:
    """Gemini menerima subset JSON Schema — buang kunci yang ditolak dan
    ratakan $ref sederhana dari pydantic ($defs)."""
    if not schema:
        return {"type": "object", "properties": {}}
    schema = copy.deepcopy(schema)
    defs = schema.pop("$defs", {})

    def _clean(node):
        """``node`` = dict SCHEMA. Kunci non-keyword dibuang di level schema
        saja — map ``properties`` berisi NAMA FIELD dan tidak boleh difilter."""
        if not isinstance(node, dict):
            return
        if "$ref" in node:
            ref = node.pop("$ref").split("/")[-1]
            node.update(copy.deepcopy(defs.get(ref, {})))
        # {"anyOf": [X, {"type":"null"}]} (Optional pydantic) → X nullable
        if "anyOf" in node:
            variants = [v for v in node["anyOf"] if v.get("type") != "null"]
            if len(variants) == 1:
                node.pop("anyOf")
                node.update(variants[0])
                node["nullable"] = True
        for k in list(node):
            if k not in _GEMINI_ALLOWED:
                node.pop(k)
        props = node.get("properties")
        if isinstance(props, dict):
            for sub in props.values():
                _clean(sub)
        items = node.get("items")
        if isinstance(items, dict):
            _clean(items)
        elif isinstance(items, list):
            for sub in items:
                _clean(sub)
        anyof = node.get("anyOf")
        if isinstance(anyof, list):
            for sub in anyof:
                _clean(sub)

    _clean(schema)
    if "type" not in schema:
        schema["type"] = "object"
    return schema


def _transient(e: Exception) -> bool:
    s = f"{type(e).__name__} {e}".lower()
    return any(k in s for k in ("429", "rate", "timeout", "timed out",
                                "overloaded", "503", "502", "500",
                                "connection", "temporarily"))


# ── factory ───────────────────────────────────────────────────────────────

def client(name: str | None = None) -> LLMClient:
    p = get_provider(name)
    key = (p.name, p.kind, p.base_url, bool(p.api_key), p.model)
    with _clients_lock:
        c = _clients.get(key)
        if c is None:
            c = LLMClient(p)
            _clients[key] = c
        return c


def vision_client() -> LLMClient:
    p = vision_provider()
    key = ("vision", p.name, p.kind, p.base_url, bool(p.api_key),
           p.resolve_vision_model())
    with _clients_lock:
        c = _clients.get(key)
        if c is None:
            vp = Provider(**{**p.__dict__})
            vp.model = p.resolve_vision_model()
            c = LLMClient(vp)
            _clients[key] = c
        return c


def available() -> bool:
    try:
        return client().available()
    except Exception:                                        # noqa: BLE001
        return False
