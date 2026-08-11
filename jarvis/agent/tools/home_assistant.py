"""Home Assistant (§3.1.N) — REST API + long-lived token.

Modul nonaktif otomatis bila HA_URL/HA_TOKEN kosong (gate ``available()``).
Cache daftar entity 5 menit.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

from pydantic import BaseModel, Field

from jarvis.core import secrets_store
from jarvis.agent.base import Tool, ToolResult

_cache: dict = {"entities": None, "ts": 0.0}


def _url() -> str:
    return os.environ.get("HA_URL", "").rstrip("/")


def _token() -> str:
    return os.environ.get("HA_TOKEN", "") \
        or (secrets_store.get("jarvis/home_assistant/token") or "")


def available() -> bool:
    return bool(_url() and _token())


def _headers() -> dict:
    return {"Authorization": f"Bearer {_token()}",
            "Content-Type": "application/json"}


def _get(path: str):
    import requests
    r = requests.get(f"{_url()}{path}", headers=_headers(), timeout=15)
    r.raise_for_status()
    return r.json()


def _post(path: str, payload: dict):
    import requests
    r = requests.post(f"{_url()}{path}", headers=_headers(),
                      json=payload, timeout=20)
    r.raise_for_status()
    return r.json()


class _ListParams(BaseModel):
    domain: str = Field("", description="Filter domain, mis. 'light'")


class HaListEntities(Tool):
    name = "ha_list_entities"
    description = "Daftar entity Home Assistant (id + state + nama)."
    params_schema = _ListParams
    read_only = True
    timeout_s = 30

    async def run(self, domain: str = "", **_) -> ToolResult:
        def _list():
            now = time.time()
            if _cache["entities"] is None or now - _cache["ts"] > 300:
                _cache["entities"] = _get("/api/states")
                _cache["ts"] = now
            return _cache["entities"]

        try:
            states = await asyncio.to_thread(_list)
        except Exception as e:                               # noqa: BLE001
            return ToolResult.fail(f"HA gagal: {str(e)[:150]}")
        rows = []
        for s in states:
            eid = s.get("entity_id", "")
            if domain and not eid.startswith(domain + "."):
                continue
            name = (s.get("attributes") or {}).get("friendly_name", "")
            rows.append(f"{eid}  = {s.get('state')}  ({name})")
        return ToolResult.success("\n".join(rows[:200]) or "(kosong)",
                                  display=f"{len(rows)} entity")


class _StateParams(BaseModel):
    entity_id: str = Field(description="mis. light.ruang_tamu")


class HaGetState(Tool):
    name = "ha_get_state"
    description = "State lengkap satu entity Home Assistant."
    params_schema = _StateParams
    read_only = True
    timeout_s = 20

    async def run(self, entity_id: str, **_) -> ToolResult:
        try:
            s = await asyncio.to_thread(_get, f"/api/states/{entity_id}")
        except Exception as e:                               # noqa: BLE001
            return ToolResult.fail(f"HA gagal: {str(e)[:150]}")
        return ToolResult.success(json.dumps(s, ensure_ascii=False)[:6000])


class _ServiceParams(BaseModel):
    domain: str = Field(description="mis. 'light'")
    service: str = Field(description="mis. 'turn_on'")
    entity_id: str = Field(description="Target entity")
    data: dict = Field(default_factory=dict, description="Data tambahan")


class HaCallService(Tool):
    name = "ha_call_service"
    description = ("Panggil service Home Assistant (nyalakan lampu, atur "
                   "suhu, dll.).")
    params_schema = _ServiceParams
    timeout_s = 30

    async def run(self, domain: str, service: str, entity_id: str,
                  data: dict | None = None, **_) -> ToolResult:
        payload = {"entity_id": entity_id, **(data or {})}
        try:
            await asyncio.to_thread(
                _post, f"/api/services/{domain}/{service}", payload)
        except Exception as e:                               # noqa: BLE001
            return ToolResult.fail(f"HA gagal: {str(e)[:150]}")
        return ToolResult.success(
            f"{domain}.{service} dipanggil untuk {entity_id}")
