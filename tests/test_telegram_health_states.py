"""Task 2 — Telegram conflict/error health states (offline, no network)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from jarvis.agent.adapters.telegram import (
    TelegramService,
    _is_conflict_error,
)


@pytest.fixture(autouse=True)
def _fresh_service():
    """Reset singleton state antar test (health state adalah per-instance)."""
    TelegramService._instance = None
    yield
    TelegramService._instance = None


def _svc() -> TelegramService:
    return TelegramService.get()


# ── _is_conflict_error: klasifikasi sanitasi ─────────────────────────────


def test_conflict_class_detected_directly():
    class Conflict(Exception):
        pass

    assert _is_conflict_error(Conflict("terminated by other getUpdates"))


def test_conflict_wrapped_in_cause_chain():
    class Conflict(Exception):
        pass

    class HTTPException(Exception):
        pass

    try:
        try:
            raise Conflict("terminated by other getUpdates request")
        except Conflict as inner:
            raise HTTPException("wrapped") from inner
    except HTTPException as outer:
        assert _is_conflict_error(outer)


def test_non_conflict_error_not_misclassified():
    assert not _is_conflict_error(ValueError("x"))
    assert not _is_conflict_error(RuntimeError("terminated by other"))


# ── health(): state agregat ──────────────────────────────────────────────


def test_health_initial_stopped():
    out = _svc().health()
    assert out["state"] == "stopped"


def test_health_connected_while_running():
    svc = _svc()
    svc.running = True
    svc._health_state = "connected"
    out = svc.health()
    assert out["state"] == "connected"
    svc.running = False


def test_health_conflict_survives_running_false():
    """Konflik: polling berhenti, tapi state tetap conflict (bukan stopped)."""
    svc = _svc()
    svc._health_state = "conflict"
    svc._health_detail = "getUpdates_conflict"
    svc.running = False
    out = svc.health()
    assert out["state"] == "conflict"
    assert out["detail"] == "getUpdates_conflict"
    # Sanitasi: detail tidak mengandung token/URL.
    assert "http" not in out["detail"]


def test_health_error_state_with_sanitized_detail():
    svc = _svc()
    svc._health_state = "error"
    svc._health_detail = "TimeoutError"
    svc.running = False
    out = svc.health()
    assert out["state"] == "error"
    assert out["detail"] == "TimeoutError"


def test_health_running_overrides_stale_stopped_state():
    """running=True tapi state belum ter-update → tampilkan connected."""
    svc = _svc()
    svc.running = True
    svc._health_state = "stopped"
    assert svc.health()["state"] == "connected"


def test_ptb_conflict_handler_updates_instance_and_stops_polling():
    """PTB callback adalah async dan menghentikan application instance aktif."""
    class Conflict(Exception):
        pass

    class FakeApp:
        def __init__(self):
            self.stop_calls = 0

        def stop_running(self):
            self.stop_calls += 1

    svc = _svc()
    svc._app = FakeApp()
    svc.running = True

    asyncio.run(svc._on_ptb_error(
        None, SimpleNamespace(error=Conflict("secret-bearing detail"))))

    assert svc.health() == {
        "state": "conflict",
        "detail": "getUpdates_conflict",
    }
    assert svc.running is False
    assert svc._app.stop_calls == 1
    assert "secret-bearing detail" not in str(svc.health())


def test_ptb_non_conflict_handler_sets_sanitized_error_without_stop():
    class FakeApp:
        def __init__(self):
            self.stop_calls = 0

        def stop_running(self):
            self.stop_calls += 1

    svc = _svc()
    svc._app = FakeApp()
    svc.running = True

    asyncio.run(svc._on_ptb_error(
        None, SimpleNamespace(error=TimeoutError("https://token.invalid"))))

    assert svc.health() == {"state": "error", "detail": "TimeoutError"}
    assert svc.running is True
    assert svc._app.stop_calls == 0


# ── lease integration: proses kedua → conflict, bukan polling ────────────


def test_main_returns_conflict_when_lease_held(tmp_path, monkeypatch):
    """_main() dengan lease terpegang proses lain: tidak polling, state conflict."""
    from jarvis.integrations import poller_lease

    svc = _svc()

    class HeldLease:
        @staticmethod
        def acquire_default(name="telegram"):
            return poller_lease.LeaseAcquireResult(False, None, "lease_held")

    monkeypatch.setattr("jarvis.integrations.poller_lease.acquire_default",
                        HeldLease.acquire_default)
    # _main() harus return sebelum import telegram/PTB — tanpa jaringan.
    svc._main()
    assert svc.running is False
    assert svc._health_state == "conflict"
    assert svc._health_detail == "lease_held_by_other_process"
    out = svc.health()
    assert out["state"] == "conflict"
    assert out["detail"] == "lease_held_by_other_process"


def test_main_releases_lease_on_success_path(tmp_path, monkeypatch):
    """Lease dirilis di finally bahkan bila run_polling sukses lalu stop."""
    from jarvis.integrations import poller_lease

    svc = _svc()
    released = []

    class FakeLease:
        def release(self):
            released.append(True)

    class AcquiredLease:
        @staticmethod
        def acquire_default(name="telegram"):
            return poller_lease.LeaseAcquireResult(True, FakeLease(),
                                                   "acquired")

    monkeypatch.setattr("jarvis.integrations.poller_lease.acquire_default",
                        AcquiredLease.acquire_default)

    # Ganti run_polling dengan fake yang langsung kembali (simulasi stop).
    class FakeApp:
        def __init__(self, *a, **kw):
            pass

        def add_handler(self, *a, **kw):
            pass

        def add_error_handler(self, *a, **kw):
            pass

        def run_polling(self, **kw):
            # Simulasi PTB loop berjalan lalu berhenti bersih.
            return

    import types as _types
    fake_telegram = _types.ModuleType("telegram")
    fake_error = _types.ModuleType("telegram.error")
    fake_ext = _types.ModuleType("telegram.ext")

    class FakeUpdate:
        ALL_TYPES = object()

    class FakeApplication:
        @staticmethod
        def builder():
            class B:
                def token(self, _t):
                    return self

                def post_init(self, _f):
                    return self

                def build(self):
                    return FakeApp()

            return B()

    # Stub semua handler class yang di-import _main().
    class _Stub:
        def __init__(self, *a, **kw):
            pass

    class FakeFilters:
        VOICE = object()
        COMMAND = object()
        TEXT = object()

        def __and__(self, other):
            return self

    class FakeDocument:
        ALL = object()

    class _F:
        """Filter stub yang mendukung ~ dan & (instance-nya sendiri)."""

        def __and__(self, other):
            return self

        def __invert__(self):
            return self

    class FakeFilterObj(_F):
        VOICE = _F()
        COMMAND = _F()
        TEXT = _F()
        Document = FakeDocument

    fake_filters = FakeFilterObj()

    for name in ("CommandHandler", "CallbackQueryHandler",
                 "MessageHandler"):
        setattr(fake_ext, name, _Stub)
    fake_ext.filters = fake_filters
    fake_ext.Application = FakeApplication
    fake_telegram.Update = FakeUpdate
    fake_telegram.ext = fake_ext
    fake_telegram.error = fake_error
    monkeypatch.setitem(__import__("sys").modules, "telegram", fake_telegram)
    monkeypatch.setitem(__import__("sys").modules, "telegram.ext", fake_ext)
    monkeypatch.setitem(__import__("sys").modules, "telegram.error",
                        fake_error)
    # Token yang sah agar _token() tidak gagal.
    monkeypatch.setattr(
        "jarvis.integrations.telegram_control.token", lambda: "1:test")

    svc._main()
    assert svc.running is False
    assert svc._health_state == "stopped"
    assert released == [True]


# ── telegram_control.status(): proyeksi runtime_state ────────────────────


def test_status_projects_runtime_state(monkeypatch):
    from jarvis.integrations import telegram_control

    class ConflictSvc:
        running = False

        def health(self):
            return {"state": "conflict",
                    "detail": "getUpdates_conflict"}

    class FakeService:
        _instance = None

        @classmethod
        def get(cls):
            return ConflictSvc()

    import jarvis.agent.adapters.telegram as tg_mod
    monkeypatch.setattr(tg_mod.TelegramService, "get",
                        classmethod(lambda cls: ConflictSvc()))

    status = telegram_control.status()
    assert status["runtime_state"] == "conflict"
    assert "CONFLICT" in str(status["state"])


def test_status_connected_unchanged(monkeypatch):
    from jarvis.integrations import telegram_control

    class OkSvc:
        running = True

        def health(self):
            return {"state": "connected"}

    import jarvis.agent.adapters.telegram as tg_mod
    monkeypatch.setattr(tg_mod.TelegramService, "get",
                        classmethod(lambda cls: OkSvc()))

    status = telegram_control.status()
    assert status["runtime_state"] == "connected"
    assert status["state"] == "Connected"


# ── OpsAPI.gateway_overview(): kunci runtime_state ────────────────────────


def test_ops_overview_includes_runtime_state(monkeypatch, tmp_path):
    import jarvis.integrations.telegram_control as tc
    from jarvis.ops.api import OpsAPI

    monkeypatch.setattr(
        tc, "status",
        lambda: {"state": "CONFLICT — proses lain mem-polling bot yang sama",
                 "configured": True, "running": False,
                 "runtime_state": "conflict"})

    class FakeGatewayManager:
        def health(self):
            return {"telegram": {"state": "conflict"}}

    api = OpsAPI(audit_path=tmp_path / "a.sqlite",
                 approvals_path=tmp_path / "b.sqlite",
                 manager=FakeGatewayManager())
    overview = api.gateway_overview("observer")
    assert overview is not None
    tg = overview.get("telegram", {})
    assert tg.get("runtime_state") == "conflict"
