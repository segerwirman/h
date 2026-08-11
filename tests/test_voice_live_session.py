"""Gemini Live reconnect classification and safe telemetry contracts."""
from __future__ import annotations

import asyncio

import pytest

from jarvis.integrations import voice_live_lifecycle as lifecycle


def _api_error(code: int, status: str, details: dict | None = None):
    errors = pytest.importorskip("google.genai.errors")
    payload = {
        "error": {
            "code": code,
            "status": status,
            "message": "bounded public message",
            "details": details or [],
        }
    }
    return errors.APIError(code, payload)


def test_nested_exception_group_finds_confirmed_auth_leaf():
    auth = _api_error(401, "UNAUTHENTICATED", {
        "api_key": "never-log-this-key",
    })
    grouped = ExceptionGroup(
        "outer contains secret and must not be logged",
        [ExceptionGroup("inner", [auth])],
    )

    failure = lifecycle.classify(grouped)

    assert failure.kind == "auth"
    assert failure.auth_confirmed is True
    assert failure.leaf_type == "APIError"
    assert failure.code == 401
    assert failure.status == "UNAUTHENTICATED"
    assert "never-log-this-key" not in repr(failure.safe_fields())
    assert "details" not in failure.safe_fields()


def test_permission_denied_is_not_treated_as_invalid_api_key():
    failure = lifecycle.classify(_api_error(403, "PERMISSION_DENIED"))

    assert failure.kind != "auth"
    assert failure.auth_confirmed is False


def test_server_and_network_failures_are_classified_separately():
    server = lifecycle.classify(_api_error(503, "UNAVAILABLE"))
    network = lifecycle.classify(ConnectionError("socket closed"))

    assert server.kind == "server"
    assert network.kind == "network"


def test_session_protocol_close_is_not_auth():
    failure = lifecycle.classify(RuntimeError(
        "websocket 1007 invalid frame payload data"
    ))

    assert failure.kind == "session"
    assert failure.auth_confirmed is False


def test_explicit_invalid_key_marker_on_leaf_is_auth_without_raw_message():
    failure = lifecycle.classify(RuntimeError(
        "API key not valid: secret-token-never-log"
    ))

    assert failure.kind == "auth"
    assert failure.auth_confirmed is True
    assert "secret-token-never-log" not in repr(failure.safe_fields())


def test_safe_status_is_bounded_and_sanitized():
    failure = lifecycle.classify(_api_error(
        500,
        "BAD\nSTATUS:" + "X" * 300,
    ))

    assert len(failure.status) <= lifecycle.MAX_STATUS_LENGTH
    assert "\n" not in failure.status


def test_backoff_is_bounded_and_resets_after_connection():
    assert lifecycle.next_backoff(0) == 3
    assert lifecycle.next_backoff(3) == 6
    assert lifecycle.next_backoff(60) == 60
    assert lifecycle.reset_backoff() == 3


def test_first_reconnect_uses_initial_delay_before_escalating():
    backoff = lifecycle.ReconnectBackoff()

    assert backoff.failed() == lifecycle.reset_backoff()
    assert backoff.failed() == lifecycle.next_backoff(
        lifecycle.reset_backoff()
    )


def test_short_accepted_sessions_keep_escalating_until_health_milestone():
    backoff = lifecycle.ReconnectBackoff()

    first = backoff.failed()
    backoff.connected()
    second = backoff.failed()
    backoff.connected()
    third = backoff.failed()

    assert (first, second, third) == (3, 6, 12)
    assert backoff.current == 12

    backoff.healthy()
    assert backoff.current == 3
    assert backoff.failed() == 3


def test_websocket_acceptance_alone_never_resets_backoff():
    backoff = lifecycle.ReconnectBackoff()
    assert backoff.failed() == 3
    assert backoff.failed() == 6

    for _ in range(3):
        backoff.connected()

    assert backoff.current == 6


def test_connection_tracker_distinguishes_initial_and_restored():
    tracker = lifecycle.ConnectionTracker()

    initial = tracker.connected()
    tracker.failed()
    restored = tracker.connected()
    steady = tracker.connected()

    assert initial == "initial"
    assert restored == "restored"
    assert steady == "connected"


def test_stop_aware_reconfiguration_wait_exits_without_ready_ui():
    stop = __import__("threading").Event()
    ready = False

    async def exercise():
        async def request_stop():
            await asyncio.sleep(0)
            stop.set()

        task = asyncio.create_task(request_stop())
        result = await lifecycle.wait_until(
            lambda: ready,
            stop.is_set,
            poll_s=0,
        )
        await task
        return result

    assert asyncio.run(exercise()) is False
