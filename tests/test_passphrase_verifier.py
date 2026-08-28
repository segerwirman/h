"""Task 8 — local verifier and scoped communication authorization."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


class _Store:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.writes: list[tuple[str, str]] = []

    def get(self, key: str):
        return self.values.get(key)

    def set(self, key: str, value: str) -> bool:
        self.values[key] = value
        self.writes.append((key, value))
        return True


class _Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


class _Verifier:
    def __init__(self, ok=True, status="verified") -> None:
        self.ok = ok
        self.status = status
        self.received = None

    def verify(self, value):
        self.received = value
        return SimpleNamespace(ok=self.ok, status=self.status)


class _Tasks:
    def __init__(self) -> None:
        self.available = True

    def get(self, task_id):
        if task_id == "T-real" and self.available:
            return SimpleNamespace(active=True)
        return None


class _Mode:
    def __init__(self) -> None:
        self.calls = []
        self.revoked = []

    def issue_override(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(id="G-opaque")

    def revoke_grant(self, grant_id):
        self.revoked.append(grant_id)
        return True


def _derive(value: bytes, salt: bytes, iterations: int, dklen: int) -> bytes:
    seed = (value + salt + str(iterations).encode("ascii")) or b"x"
    return (seed * ((dklen // len(seed)) + 1))[:dklen]


def test_verifier_persists_kdf_record_only_and_round_trips(monkeypatch):
    import hmac
    from jarvis.core.communication_passphrase import PassphraseVerifier

    store = _Store()
    comparisons = []
    real_compare = hmac.compare_digest
    monkeypatch.setattr(
        "jarvis.core.communication_passphrase.hmac.compare_digest",
        lambda left, right: comparisons.append((left, right)) or real_compare(left, right),
    )
    verifier = PassphraseVerifier(
        store=store,
        random_bytes=lambda count: b"s" * count,
        derive_fn=_derive,
    )
    value = "local-only-value"

    assert verifier.set_passphrase(value) is True
    record = json.loads(store.writes[0][1])

    assert set(record) == {"algorithm", "salt", "iterations", "dklen", "verifier"}
    assert record["algorithm"] == "pbkdf2_sha256"
    assert value not in store.writes[0][1]
    assert verifier.configured() is True
    assert verifier.verify(value).status == "verified"
    assert verifier.verify("different-value").status == "denied"
    assert len(comparisons) == 2


def test_verifier_bounds_failures_with_process_local_lockout():
    from jarvis.core.communication_passphrase import PassphraseVerifier

    store = _Store()
    clock = _Clock()
    verifier = PassphraseVerifier(
        store=store,
        now_fn=clock,
        random_bytes=lambda count: b"s" * count,
        derive_fn=_derive,
        max_failures=2,
        failure_window_s=30,
        lockout_s=12,
    )
    assert verifier.set_passphrase("correct-value") is True

    assert verifier.verify("wrong-value-1").status == "denied"
    locked = verifier.verify("wrong-value-2")
    assert locked.status == "locked"
    assert locked.retry_after_s == 12
    assert verifier.verify("correct-value").status == "locked"

    clock.value += 13
    assert verifier.verify("correct-value").status == "verified"


def test_verifier_rejects_malformed_or_downgraded_record():
    from jarvis.core.communication_passphrase import PassphraseVerifier

    store = _Store()
    verifier = PassphraseVerifier(store=store, derive_fn=_derive)
    store.values["jarvis/communication/passphrase_verifier"] = json.dumps({
        "algorithm": "pbkdf2_sha256",
        "salt": "c2hvcnQ=",
        "iterations": 1,
        "dklen": 1,
        "verifier": "eA==",
    })

    assert verifier.configured() is False
    assert verifier.verify("some-value").status == "not_configured"


def test_authorizer_binds_real_task_trace_capabilities_and_generation_owner(monkeypatch):
    from jarvis.agent.communication_authorization import CommunicationAuthorizer

    raw = "local-only-value"
    verifier = _Verifier()
    mode = _Mode()
    tasks = _Tasks()
    authorizer = CommunicationAuthorizer(
        verifier=verifier,
        mode=mode,
        task_registry=tasks,
    )
    monkeypatch.setattr(
        authorizer,
        "_capabilities_authorizable",
        lambda _capabilities: True,
    )

    result = authorizer.authorize(
        raw,
        task_id="T-real",
        trace_id="trace-123",
        capability_ids={"web.web_search", "memory.memory_search"},
        ttl_s=45,
        uses=2,
    )

    assert result.ok is True
    assert result.status == "authorized"
    assert result.grant_id == "G-opaque"
    assert verifier.received == raw
    assert mode.calls == [{
        "task_id": "T-real",
        "trace_id": "trace-123",
        "capability_ids": frozenset({"web.web_search", "memory.memory_search"}),
        "ttl_s": 45.0,
        "uses": 2,
    }]
    assert raw not in repr(result)
    assert raw not in repr(mode.calls)


def test_authorizer_rejects_scope_before_secret_verification(monkeypatch):
    from jarvis.agent.communication_authorization import CommunicationAuthorizer

    verifier = _Verifier()
    authorizer = CommunicationAuthorizer(
        verifier=verifier,
        mode=_Mode(),
        task_registry=_Tasks(),
    )
    monkeypatch.setattr(
        authorizer,
        "_capabilities_authorizable",
        lambda _capabilities: True,
    )

    result = authorizer.authorize(
        "local-only-value",
        task_id="not-real",
        trace_id="trace-123",
        capability_ids={"web.web_search"},
        ttl_s=45,
    )

    assert result.status == "invalid_scope"
    assert verifier.received is None


@pytest.mark.parametrize("ttl,uses", [
    (0, 1), (301, 1), (float("inf"), 1), (45, 0), (45, 17),
])
def test_authorizer_bounds_ttl_and_uses(ttl, uses, monkeypatch):
    from jarvis.agent.communication_authorization import CommunicationAuthorizer

    verifier = _Verifier()
    mode = _Mode()
    authorizer = CommunicationAuthorizer(
        verifier=verifier,
        mode=mode,
        task_registry=_Tasks(),
    )
    monkeypatch.setattr(
        authorizer,
        "_capabilities_authorizable",
        lambda _capabilities: True,
    )
    result = authorizer.authorize(
        "local-only-value",
        task_id="T-real",
        trace_id="trace-123",
        capability_ids={"web.web_search"},
        ttl_s=ttl,
        uses=uses,
    )

    assert result.status == "invalid_scope"
    assert verifier.received is None
    assert mode.calls == []


def test_authorizer_revokes_if_task_ends_during_issue(monkeypatch):
    from jarvis.agent.communication_authorization import CommunicationAuthorizer

    tasks = _Tasks()

    class Mode(_Mode):
        def issue_override(self, **kwargs):
            result = super().issue_override(**kwargs)
            tasks.available = False
            return result

    mode = Mode()
    authorizer = CommunicationAuthorizer(
        verifier=_Verifier(),
        mode=mode,
        task_registry=tasks,
    )
    monkeypatch.setattr(
        authorizer,
        "_capabilities_authorizable",
        lambda _capabilities: True,
    )
    result = authorizer.authorize(
        "local-only-value",
        task_id="T-real",
        trace_id="trace-123",
        capability_ids={"web.web_search"},
        ttl_s=45,
    )

    assert result.status == "task_unavailable"
    assert mode.revoked == ["G-opaque"]


def test_authorizer_accepts_only_registered_non_dispatch_capabilities(monkeypatch):
    from jarvis.agent import capabilities
    from jarvis.agent.communication_authorization import CommunicationAuthorizer

    descriptors = [
        SimpleNamespace(
            id="local.test.work",
            tool_name="work",
            enabled=True,
        ),
        SimpleNamespace(
            id="local.task_tools.task_start",
            tool_name="task_start",
            enabled=True,
        ),
    ]
    monkeypatch.setattr(capabilities.REGISTRY, "descriptors", lambda: descriptors)

    assert CommunicationAuthorizer._capabilities_authorizable(
        frozenset({"local.test.work"})
    ) is True
    assert CommunicationAuthorizer._capabilities_authorizable(
        frozenset({"local.task_tools.task_start"})
    ) is False
    assert CommunicationAuthorizer._capabilities_authorizable(
        frozenset({"agent.dispatch"})
    ) is False
    assert CommunicationAuthorizer._capabilities_authorizable(
        frozenset({"unknown.capability"})
    ) is False


def test_task8_modules_do_not_publish_or_log_secret_material():
    root = Path(__file__).resolve().parents[1]
    sources = [
        root / "jarvis/core/communication_passphrase.py",
        root / "jarvis/agent/communication_authorization.py",
        root / "jarvis/ui/communication_auth_sheet.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in sources)

    assert "BUS.publish" not in combined
    assert "logger." not in combined
    assert "config.set" not in combined
    assert "ExecutionContext" not in combined
    assert "setText(llm.api_key" not in combined
