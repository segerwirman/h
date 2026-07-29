"""Agent core — registry, kontrak tool, loop dengan LLM palsu (tanpa network,
tanpa Qt)."""
from __future__ import annotations

import asyncio

import pytest

from jarvis.agent import registry
from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.llm_client import ChatResponse, ToolCall


class EchoTool(Tool):
    name = "echo"
    description = "echo balik"
    read_only = True
    timeout_s = 5

    async def run(self, text: str = "", **_) -> ToolResult:
        return ToolResult.success(f"ECHO:{text}")


class BoomTool(Tool):
    name = "boom"
    description = "selalu meledak"
    timeout_s = 5

    async def run(self, **_) -> ToolResult:
        raise RuntimeError("meledak")


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    import jarvis.agent.memory_store as ms
    import jarvis.agent.session as sess
    db = tmp_path / "agent.sqlite"
    monkeypatch.setattr(ms, "db_path", lambda: db)
    monkeypatch.setattr(sess, "db_path", lambda: db)
    return db


@pytest.fixture()
def fake_tools(monkeypatch):
    tools = {"echo": EchoTool(), "boom": BoomTool()}
    monkeypatch.setattr(registry, "_tools", tools)
    return tools


def test_registry_discovers_real_tools():
    tools = registry.all_tools(refresh=True)
    # tool inti yang tidak butuh kredensial harus selalu ada
    for name in ("file_read", "file_write", "terminal", "web_search",
                 "todo_write", "memory_write", "vision_analyze",
                 "execute_code", "delegate_task", "cron_create",
                 "skill_list", "analyze_food_calories",
                 "browser_snapshot", "computer_screenshot"):
        assert name in tools, f"tool {name} tidak ditemukan"
    # schema OpenAI valid
    schemas = registry.schemas()
    assert all(s["type"] == "function" for s in schemas)
    assert all("name" in s["function"] for s in schemas)
    registry._tools = None                      # jangan cemari test lain


def test_execute_unknown_tool(fake_tools):
    res = asyncio.run(registry.execute("tidak_ada", {}))
    assert not res.ok
    assert "tidak dikenal" in res.error


def test_execute_crash_becomes_result(fake_tools, tmp_db):
    res = asyncio.run(registry.execute("boom", {}))
    assert not res.ok
    assert "RuntimeError" in res.error


def test_execute_echo(fake_tools, tmp_db):
    res = asyncio.run(registry.execute("echo", {"text": "halo"}))
    assert res.ok
    assert res.content == "ECHO:halo"


def test_terminal_blacklist_detection():
    from jarvis.agent.tools.terminal import Terminal
    t = Terminal()
    assert t.needs_confirmation(command="rm -rf /")
    assert t.needs_confirmation(command="format c: /q")
    assert t.needs_confirmation(command="shutdown /s /t 0")
    assert not t.needs_confirmation(command="dir")
    assert not t.needs_confirmation(command="python --version")


def test_loop_completes_with_fake_llm(fake_tools, tmp_db, monkeypatch):
    """Loop: panggilan tool pertama → jawaban akhir kedua."""
    from jarvis.agent import loop as agent_loop
    from jarvis.agent import llm_client, model_routing

    responses = [
        ChatResponse(content=None, tool_calls=[
            ToolCall(id="c1", name="echo", arguments={"text": "uji"})]),
        ChatResponse(content="Selesai: uji berhasil."),
    ]

    class FakeClient:
        def available(self):
            return True

        def chat(self, messages, tools=None, **kw):
            return responses.pop(0)

        def generate(self, *a, **kw):
            return ""

    monkeypatch.setattr(llm_client, "client", lambda name=None: FakeClient())
    # Loop kini Lane B (§3): model dari resolusi routing.heavy, deterministik
    # di test tanpa bergantung config mesin.
    monkeypatch.setattr(model_routing, "heavy_resolution",
                        lambda: (FakeClient(), "fakeheavy", "test"))
    monkeypatch.setattr(agent_loop, "reflect_async", lambda s: None)

    from jarvis.agent.adapters.base import NullAdapter
    adapter = NullAdapter()
    result = asyncio.run(agent_loop.run("tes tugas", adapter=adapter))
    assert result.ok
    assert "Selesai" in result.text
    assert adapter.outputs and "Selesai" in adapter.outputs[-1]
    assert result.iterations == 2


def test_loop_delivers_generated_image_from_tool_result(fake_tools, tmp_db, monkeypatch):
    from jarvis.agent import loop as agent_loop
    from jarvis.agent import model_routing

    class ImageTool(Tool):
        name = "image_generate"
        description = "test image"
        timeout_s = 5

        async def run(self, **_):
            return ToolResult.success("gambar tersimpan", paths=["generated.png"])

    fake_tools["image_generate"] = ImageTool()
    responses = [
        ChatResponse(content=None, tool_calls=[
            ToolCall(id="image-1", name="image_generate", arguments={"prompt": "orb"})]),
        ChatResponse(content="Gambar selesai."),
    ]

    class FakeClient:
        def available(self):
            return True

        def chat(self, *_args, **_kwargs):
            return responses.pop(0)

    class ImageAdapter:
        name = "telegram"
        interactive = True

        def __init__(self):
            self.outputs = []
            self.images = []

        async def send(self, content, **_kwargs):
            self.outputs.append(content)

        async def progress(self, _text):
            return None

        async def send_image(self, path, caption=""):
            self.images.append((path, caption))

    monkeypatch.setattr(model_routing, "heavy_resolution",
                        lambda: (FakeClient(), "fakeheavy", "test"))
    monkeypatch.setattr(agent_loop, "reflect_async", lambda _session: None)
    adapter = ImageAdapter()

    result = asyncio.run(agent_loop.run("buatkan gambar orb", adapter=adapter))

    assert result.ok is True
    assert adapter.images == [("generated.png", "gambar tersimpan")]


def test_loop_reports_when_provider_missing(tmp_db, monkeypatch):
    from jarvis.agent import loop as agent_loop
    from jarvis.agent import model_routing

    class DeadClient:
        def available(self):
            return False

    # Provider berat ada tapi belum siap → degrade jujur §3.2 (arah Settings).
    monkeypatch.setattr(model_routing, "heavy_resolution",
                        lambda: (DeadClient(), "dead", "test"))
    from jarvis.agent.adapters.base import NullAdapter
    adapter = NullAdapter()
    result = asyncio.run(agent_loop.run("apa pun", adapter=adapter))
    assert not result.ok
    assert adapter.outputs and "Settings" in adapter.outputs[0]


def test_context_compaction_shape():
    from jarvis.agent import context as ctx

    class NoLLM:
        def generate(self, *a, **kw):
            return "ringkasan"

    msgs = [{"role": "system", "content": "sys"}]
    msgs += [{"role": "user", "content": f"pesan {i}" * 50}
             for i in range(40)]
    out = ctx.compact(msgs, NoLLM())
    assert out[0]["role"] == "system"
    assert "RINGKASAN KONTEKS" in out[1]["content"]
    assert len(out) < len(msgs)


def test_gemini_schema_sanitizer():
    from jarvis.agent.llm_client import _gemini_schema
    schema = {
        "type": "object", "additionalProperties": False,
        "$defs": {"Item": {"type": "object",
                           "properties": {"x": {"type": "string",
                                                "default": "a"}}}},
        "properties": {
            "items": {"type": "array", "items": {"$ref": "#/$defs/Item"}},
            "opt": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
    }
    out = _gemini_schema(schema)
    assert "additionalProperties" not in out
    assert "$defs" not in out
    assert out["properties"]["items"]["items"]["type"] == "object"
    assert out["properties"]["opt"]["type"] == "string"
    assert out["properties"]["opt"].get("nullable") is True
