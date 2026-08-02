"""A51b: SetupQueue atomic staging key + autonomous TTL expiry.

Regression: concurrent first-use of the staging key could mint two different
keys (ciphertext unreadable), and expired staging was only pruned when another
queue operation happened. Fix: module-level lock around get-or-create, and a
daemon sweeper thread that prunes on its own schedule.
"""
import json
import threading
import time


def _valid_oauth_installed() -> bytes:
    return json.dumps({
        "installed": {
            "client_id": "abc.apps.googleusercontent.com",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_secret": "SECRET-VALUE-DO-NOT-LEAK",
        }
    }).encode()


def test_staging_key_concurrent_first_use_is_single_shared_key(monkeypatch):
    from jarvis.agent import remote_setup
    from jarvis.core import secrets_store

    store = {}
    original_set = secrets_store.set
    gate = threading.Barrier(2)

    def blocked_get(name):
        value = store.get(name)
        try:
            gate.wait(timeout=2)
        except threading.BrokenBarrierError:
            pass
        return value

    def fake_set(name, value):
        store[name] = value
        original_set(name, value)

    monkeypatch.setattr(secrets_store, "get", blocked_get)
    monkeypatch.setattr(secrets_store, "set", fake_set)

    results = []

    def worker():
        results.append(remote_setup._staging_key())

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 2
    assert results[0] == results[1], "concurrent first-use harus menghasilkan satu key"
    assert len(store) == 1, "key hanya boleh ditulis sekali"


def test_staging_expires_autonomously_without_queue_operation():
    from jarvis.agent import remote_setup

    queue = remote_setup.SetupQueue(ttl_s=0.2)
    try:
        request = queue.stage(
            provider="google_oauth_client", requester="telegram:123",
            filename="client_secret.json", payload=_valid_oauth_installed(),
        )
        # no queue method called: the sweeper must prune on its own
        deadline = time.monotonic() + 3.0
        while request.id in queue._items and time.monotonic() < deadline:
            time.sleep(0.05)
        assert request.id not in queue._items, \
            "staging harus dibersihkan sweeper tanpa operasi queue lain"
        assert queue.get(request.id) is None
    finally:
        queue.close()
