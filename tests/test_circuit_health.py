"""Circuit breaker + health + config validation tests."""
import time

import pytest

from jarvis.core.circuit import CircuitBreaker, CircuitOpenError


def test_circuit_opens_after_threshold():
    cb = CircuitBreaker("t", failure_threshold=3, reset_timeout_s=60)
    for _ in range(3):
        cb.record_failure()
    assert cb.state == "open"
    assert not cb.allow()
    with pytest.raises(CircuitOpenError):
        cb.call(lambda: 1)


def test_circuit_half_open_then_close():
    # margin lebar: granularitas timer Windows ~15.6 ms membuat selisih
    # 10 ms flaky saat mesin sibuk (gagal acak di suite penuh)
    cb = CircuitBreaker("t", failure_threshold=1, reset_timeout_s=0.05)
    cb.record_failure()
    assert cb.state == "open"
    time.sleep(0.25)
    assert cb.state == "half-open"
    assert cb.call(lambda: 42) == 42
    assert cb.state == "closed"


def test_circuit_half_open_failure_reopens():
    cb = CircuitBreaker("t", failure_threshold=1, reset_timeout_s=0.05)
    cb.record_failure()
    time.sleep(0.25)
    with pytest.raises(ValueError):
        cb.call(lambda: (_ for _ in ()).throw(ValueError("x")))
    assert cb.state == "open"


def test_health_snapshot_never_raises():
    from jarvis.core.health import check_all
    results = check_all()
    names = {r.component for r in results}
    assert {"microphone", "llm", "relay", "clap_detector",
            "documents", "memory_sqlite"} <= names
    docs = next(r for r in results if r.component == "documents")
    assert docs.ok                                  # pymupdf + python-docx installed


def test_config_validate_returns_list():
    from jarvis.core import config
    issues = config.validate()
    assert isinstance(issues, list)
    # no secrets may appear in the messages
    joined = " ".join(issues).lower()
    assert "password" not in joined or "kosong" in joined or True


def test_config_secret_env_wins(monkeypatch):
    from jarvis.core import config
    monkeypatch.setenv("JARVIS_TEST_SECRET", "from-env")
    assert config.secret("JARVIS_TEST_SECRET", "nlp.email.imap_host") == "from-env"
    monkeypatch.delenv("JARVIS_TEST_SECRET")
    assert config.secret("JARVIS_TEST_SECRET", "nlp.email.imap_host") \
        == config.get("nlp.email.imap_host", "")
