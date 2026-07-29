"""Relay.app adapter tests — models, store, webhook auth, client retries."""
import hashlib
import hmac
import json
import time
from unittest import mock

import pytest

from jarvis.integrations.relay.client import RelayClient, RelayClientError
from jarvis.integrations.relay.models import PayloadError, parse_event
from jarvis.integrations.relay.store import RelayStore
from jarvis.integrations.relay.webhook import (SIGNATURE_HEADER, TOKEN_HEADER,
                                               verify_request)

SECRET = "test-secret-123"


def body(**kw) -> bytes:
    base = {"event_id": "evt-1", "workflow": "laporan", "kind": "event",
            "data": {"x": 1}}
    base.update(kw)
    return json.dumps(base).encode()


# ── models ────────────────────────────────────────────────────────────────────

def test_parse_event_normal():
    e = parse_event(body())
    assert e.event_id == "evt-1"
    assert e.workflow == "laporan"
    assert e.data == {"x": 1}


def test_parse_event_flat_payload_and_generated_id():
    e = parse_event(json.dumps({"foo": "bar"}).encode())
    assert e.event_id.startswith("sha-")
    assert e.data == {"foo": "bar"}


def test_parse_event_invalid():
    with pytest.raises(PayloadError):
        parse_event(b"not json")
    with pytest.raises(PayloadError):
        parse_event(b'"just a string"')
    with pytest.raises(PayloadError):
        parse_event(json.dumps({"event_id": "e", "data": [1, 2]}).encode())


def test_parse_event_too_large():
    with pytest.raises(PayloadError):
        parse_event(b"x" * (300 * 1024))


# ── webhook auth (pure verify_request — no sockets needed) ───────────────────

def test_token_auth_ok():
    ok, reason = verify_request({TOKEN_HEADER: SECRET}, body(), SECRET, 0)
    assert ok, reason


def test_wrong_token_rejected():
    ok, reason = verify_request({TOKEN_HEADER: "wrong"}, body(), SECRET, 0)
    assert not ok and reason == "bad_token"


def test_missing_auth_rejected():
    ok, reason = verify_request({}, body(), SECRET, 0)
    assert not ok


def test_no_secret_configured_rejected():
    ok, reason = verify_request({TOKEN_HEADER: "x"}, body(), "", 0)
    assert not ok and reason == "no_secret_configured"


def test_hmac_signature_ok_and_bad():
    b = body()
    sig = "sha256=" + hmac.new(SECRET.encode(), b, hashlib.sha256).hexdigest()
    ok, _ = verify_request({SIGNATURE_HEADER: sig}, b, SECRET, 0)
    assert ok
    ok, reason = verify_request({SIGNATURE_HEADER: "sha256=deadbeef"}, b,
                                SECRET, 0)
    assert not ok and reason == "bad_signature"


def test_replay_window_rejects_old_event():
    old = body(timestamp=time.time() - 4000)
    ok, reason = verify_request({TOKEN_HEADER: SECRET}, old, SECRET, 300)
    assert not ok and reason == "replay_window"
    fresh = body(timestamp=time.time())
    ok, _ = verify_request({TOKEN_HEADER: SECRET}, fresh, SECRET, 300)
    assert ok


# ── store: dedup + bounds ─────────────────────────────────────────────────────

def test_store_dedup_and_recent(tmp_path):
    store = RelayStore(db_path=tmp_path / "relay.sqlite")
    e = parse_event(body())
    assert store.add(e) is True
    assert store.add(e) is False                    # duplicate event_id
    assert store.count() == 1
    assert store.recent(5)[0].event_id == "evt-1"
    assert store.workflows() == ["laporan"]
    assert store.by_workflow("laporan")[0].event_id == "evt-1"


def test_store_row_cap(tmp_path):
    store = RelayStore(db_path=tmp_path / "relay.sqlite", max_rows=3)
    for i in range(6):
        store.add(parse_event(body(event_id=f"evt-{i}")))
    assert store.count() == 3


# ── client: retries, 429, 500, timeout, no-token-in-logs ─────────────────────

class FakeResponse:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def make_client(responses, **kw):
    session = mock.Mock()
    session.get.side_effect = responses
    kw.setdefault("base_url", "https://example.test")
    kw.setdefault("token", "tok-abc")
    kw.setdefault("timeout_s", 1)
    kw.setdefault("max_retries", 2)
    return RelayClient(session=session, **kw), session


def test_client_success():
    c, s = make_client([FakeResponse(200, {"items": [1, 2]})])
    assert c.get_json("/x") == {"items": [1, 2]}
    # Authorization header sent but never logged
    _, kwargs = s.get.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer tok-abc"


def test_client_not_configured():
    c = RelayClient(base_url="", session=mock.Mock())
    with pytest.raises(RelayClientError) as ei:
        c.get_json("/x")
    assert ei.value.code == "not_configured"


def test_client_unauthorized():
    c, _ = make_client([FakeResponse(401)])
    with pytest.raises(RelayClientError) as ei:
        c.get_json("/x")
    assert ei.value.code == "unauthorized"


def test_client_retry_then_success(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    c, s = make_client([FakeResponse(500), FakeResponse(200, {"ok": True})])
    assert c.get_json("/x") == {"ok": True}
    assert s.get.call_count == 2


def test_client_429_respects_retry_after(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
    c, _ = make_client([FakeResponse(429, headers={"Retry-After": "3"}),
                        FakeResponse(200, {"ok": 1})])
    assert c.get_json("/x") == {"ok": 1}
    assert 3.0 in sleeps


def test_client_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    c, s = make_client([FakeResponse(500)] * 5)
    with pytest.raises(RelayClientError):
        c.get_json("/x")
    assert s.get.call_count == 3                    # 1 + 2 retries


def test_client_timeout_exhausts(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    c, _ = make_client([TimeoutError("t")] * 5)
    with pytest.raises(RelayClientError) as ei:
        c.get_json("/x")
    assert ei.value.code == "network_error"


def test_client_circuit_opens(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    c, _ = make_client([FakeResponse(500)] * 50)
    for _ in range(4):
        with pytest.raises(RelayClientError):
            c.get_json("/x")
    with pytest.raises(RelayClientError) as ei:
        c.get_json("/x")
    assert ei.value.code == "circuit_open"


def test_client_pagination():
    c, _ = make_client([
        FakeResponse(200, {"items": [1, 2], "next_cursor": "c2"}),
        FakeResponse(200, {"items": [3], "next_cursor": None}),
    ])
    assert c.get_paginated("/x") == [1, 2, 3]


def test_client_empty_response():
    c, _ = make_client([FakeResponse(200, {"items": []})])
    assert c.get_paginated("/x") == []


def test_secret_not_in_log_messages():
    """Failure paths must not leak the token into the raised message."""
    c, _ = make_client([FakeResponse(401)])
    try:
        c.get_json("/x")
    except RelayClientError as e:
        assert "tok-abc" not in str(e)


# ── end-to-end webhook over real HTTP (loopback) ─────────────────────────────

def test_webhook_end_to_end(tmp_path):
    import urllib.request
    from jarvis.integrations.relay.webhook import WebhookReceiver
    store = RelayStore(db_path=tmp_path / "wh.sqlite")
    wh = WebhookReceiver(store=store, host="127.0.0.1", port=0,
                         path="/relay/webhook", secret=SECRET)
    # port=0 → pick free port
    assert wh.start()
    port = wh._server.server_address[1]
    url = f"http://127.0.0.1:{port}/relay/webhook"
    try:
        req = urllib.request.Request(url, data=body(),
                                     headers={TOKEN_HEADER: SECRET,
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            assert json.loads(r.read())["ok"] is True
        # duplicate → still 200, flagged
        with urllib.request.urlopen(req) as r:
            assert json.loads(r.read())["duplicate"] is True
        # bad token → 401
        bad = urllib.request.Request(url, data=body(),
                                     headers={TOKEN_HEADER: "nope"})
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(bad)
        assert ei.value.code == 401
        # health endpoint
        with urllib.request.urlopen(url + "/health") as r:
            assert json.loads(r.read())["ok"] is True
        assert store.count() == 1
    finally:
        wh.stop()
