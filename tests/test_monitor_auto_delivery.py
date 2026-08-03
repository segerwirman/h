"""17C automatic delivery is bounded to monitor results only."""
from __future__ import annotations


def source():
    from jarvis.monitoring.sources import MonitorSource
    return MonitorSource.create("News", "https://example.org/feed", "rss", rate_limit_s=60)


def _result(status="new_items"):
    return {"status": status, "source": "News", "items": [{"title": "Update", "url": "https://example.org/u", "published": "today", "hash": "h"}]}


def test_on_change_delivers_only_bounded_digest_to_telegram():
    from jarvis.monitoring.auto_delivery import MonitorDeliveryCoordinator
    sent = []
    coordinator = MonitorDeliveryCoordinator(
        scheduler=object(), store=object(), telegram_send=sent.append,
    )
    assert coordinator.deliver_result("on_change", _result()) == {"delivered": True, "target": "telegram"}
    assert len(sent) == 1 and "Update" in sent[0]
    assert "hash" not in sent[0] and "source" not in sent[0]


def test_no_change_never_sends_on_change():
    from jarvis.monitoring.auto_delivery import MonitorDeliveryCoordinator
    sent = []
    coordinator = MonitorDeliveryCoordinator(scheduler=object(), store=object(), telegram_send=sent.append)
    assert coordinator.deliver_result("on_change", _result("no_change")) == {"delivered": False, "reason": "no_new_items"}
    assert sent == []


def test_desktop_only_uses_desktop_callback_not_telegram():
    from jarvis.monitoring.auto_delivery import MonitorDeliveryCoordinator
    telegram, desktop = [], []
    coordinator = MonitorDeliveryCoordinator(scheduler=object(), store=object(), telegram_send=telegram.append, desktop_show=desktop.append)
    assert coordinator.deliver_result("desktop_only", _result()) == {"delivered": True, "target": "desktop"}
    assert telegram == [] and len(desktop) == 1


def test_on_request_renders_latest_but_never_sends_automatically():
    from jarvis.monitoring.auto_delivery import MonitorDeliveryCoordinator
    sent = []
    class Store:
        def latest(self, name):
            assert name == "News"
            return _result()["items"]
    coordinator = MonitorDeliveryCoordinator(scheduler=object(), store=Store(), telegram_send=sent.append)
    output = coordinator.on_request(source())
    assert output["ok"] is True and "Update" in output["content"]
    assert sent == []


def test_daily_digest_uses_latest_when_no_change():
    from jarvis.monitoring.auto_delivery import MonitorDeliveryCoordinator
    sent = []
    class Store:
        def latest(self, name): return _result()["items"]
    coordinator = MonitorDeliveryCoordinator(scheduler=object(), store=Store(), telegram_send=sent.append)
    assert coordinator.deliver_result("daily_digest", _result("no_change")) == {"delivered": True, "target": "telegram"}
    assert len(sent) == 1


def test_invalid_delivery_payload_or_mode_fails_closed():
    from jarvis.monitoring.auto_delivery import MonitorDeliveryCoordinator
    c = MonitorDeliveryCoordinator(scheduler=object(), store=object())
    assert c.deliver_result("shell", _result()) == {"delivered": False, "reason": "monitor_delivery_mode_rejected"}
    assert c.deliver_result("on_change", {"status": "new_items", "source": "News", "items": [{"body": "secret"}]}) == {"delivered": False, "reason": "monitor_delivery_payload_rejected"}


def test_run_due_wires_scheduler_result_through_registered_delivery_mode():
    from jarvis.monitoring.auto_delivery import MonitorDeliveryCoordinator
    sent = []
    class Scheduler:
        def tick_detailed(self):
            return [{"job": {"id": "job-1"}, "result": _result()}]
    coordinator = MonitorDeliveryCoordinator(scheduler=Scheduler(), store=object(), telegram_send=sent.append)
    coordinator.bind_job({"id": "job-1"}, "on_change")
    assert coordinator.run_due() == [{"delivered": True, "target": "telegram"}]
    assert len(sent) == 1 and "Update" in sent[0]


def test_real_monitor_scheduler_to_telegram_delivery_pipeline():
    from jarvis.monitoring.auto_delivery import MonitorDeliveryCoordinator
    from jarvis.monitoring.scheduler import MonitorScheduler
    sent = []
    scheduler = MonitorScheduler(
        store=object(), scan=lambda source, store: _result(),
        now=lambda: 100.0, next_run=lambda schedule, now: 100.0,
    )
    job = scheduler.create_monitor_job(source(), "* * * * *")
    coordinator = MonitorDeliveryCoordinator(scheduler=scheduler, store=object(), telegram_send=sent.append)
    coordinator.bind_job(job, "on_change")
    assert coordinator.run_due() == [{"delivered": True, "target": "telegram"}]
    assert sent and "Update" in sent[0]


def test_sink_exception_fails_closed_without_raw_exception():
    from jarvis.monitoring.auto_delivery import MonitorDeliveryCoordinator
    def broken(_: str):
        raise RuntimeError("private endpoint detail")
    coordinator = MonitorDeliveryCoordinator(scheduler=object(), store=object(), telegram_send=broken)
    assert coordinator.deliver_result("on_change", _result()) == {
        "delivered": False, "reason": "monitor_delivery_target_unavailable",
    }


def test_default_sinks_use_whitelist_telegram_and_desktop_notify(monkeypatch):
    from jarvis.monitoring import auto_delivery
    sent, desktop = [], []
    monkeypatch.setattr(auto_delivery, "_default_telegram_send", lambda text: sent.append(text) or True)
    monkeypatch.setattr(auto_delivery, "_default_desktop_show", lambda text: desktop.append(text) or True)
    coordinator = auto_delivery.MonitorDeliveryCoordinator(scheduler=object(), store=object())
    assert coordinator.deliver_result("on_change", _result()) == {"delivered": True, "target": "telegram"}
    assert coordinator.deliver_result("desktop_only", _result()) == {"delivered": True, "target": "desktop"}
    assert len(sent) == 1 and len(desktop) == 1
