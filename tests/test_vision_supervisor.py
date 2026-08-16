"""W3 — VisionSupervisor: deteksi objek realtime → laporan/telegram bounded.

Unit test memakai fake bus, fake sender, dan fake clock — tidak ada kamera,
tidak ada jaringan, tidak ada Telegram sungguhan di sini. Bukti live tetap
acceptance manual terpisah.
"""
from __future__ import annotations

import time

import pytest

from jarvis.integrations.vision_supervisor import VisionSupervisor

DEFAULTS = {
    "vision_supervisor.enabled": True,
    "vision_supervisor.min_interval_s": 30.0,
    "vision_supervisor.poll_s": 0.01,
    "vision_supervisor.include_photo": True,
    "vision_supervisor.require_armed": True,
    "vision_supervisor.max_names": 12,
}


class FakeBus:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def subscribe(self, topic: str, handler, ui: bool = False) -> None:
        self.handlers[topic] = handler

    def publish(self, topic: str, **data) -> None:
        fn = self.handlers.get(topic)
        if fn is not None:
            fn(data)


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.value = start

    def now(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@pytest.fixture
def make_supervisor(monkeypatch):
    from jarvis.core import config as core_config

    created: list[VisionSupervisor] = []

    def _make(*, overrides: dict | None = None):
        cfg = dict(DEFAULTS)
        if overrides:
            cfg.update(overrides)
        monkeypatch.setattr(
            core_config, "get",
            lambda key, default=None: cfg.get(key, default),
        )
        bus = FakeBus()
        sent_text: list[str] = []
        sent_photo: list[tuple[str, str]] = []
        clock = FakeClock()
        sv = VisionSupervisor(
            bus=bus,
            send_text=lambda text: sent_text.append(text) or True,
            send_photo=lambda path, caption: sent_photo.append((path, caption)) or True,
            now=clock.now,
        )
        sv.start()
        created.append(sv)
        return sv, bus, sent_text, sent_photo, clock

    yield _make
    for instance in created:
        try:
            instance.stop()
        except Exception:  # noqa: BLE001, S110 - cleanup tidak boleh menggagalkan test
            pass


def _event(bus: FakeBus, objects: list[dict]) -> None:
    bus.publish("vision.object", objects=objects)


def test_disabled_sends_nothing(make_supervisor):
    sv, bus, sent_text, sent_photo, clock = make_supervisor(
        overrides={"vision_supervisor.enabled": False})
    _event(bus, [{"name": "person", "conf": 0.9}])
    bus.publish("vision.status", armed=True, alive=True)
    clock.advance(60)
    sv._tick()
    assert sent_text == []
    assert sent_photo == []


def test_require_armed_blocks_reports_when_not_armed(make_supervisor):
    sv, bus, sent_text, sent_photo, clock = make_supervisor()
    bus.publish("vision.status", armed=False, alive=True)
    _event(bus, [{"name": "person", "conf": 0.9}])
    clock.advance(60)
    sv._tick()
    assert sent_text == []


def test_armed_burst_coalesces_to_one_aggregated_report(make_supervisor):
    sv, bus, sent_text, sent_photo, clock = make_supervisor()
    bus.publish("vision.status", armed=True, alive=True)
    _event(bus, [{"name": "person", "conf": 0.9}, {"name": "person", "conf": 0.8}])
    clock.advance(1)
    _event(bus, [{"name": "laptop", "conf": 0.7}])
    clock.advance(60)
    sv._tick()
    assert len(sent_text) == 1
    assert "person x2" in sent_text[0]
    assert "laptop x1" in sent_text[0]


def test_interval_respected_no_resend_before_window(make_supervisor):
    sv, bus, sent_text, sent_photo, clock = make_supervisor()
    bus.publish("vision.status", armed=True, alive=True)
    _event(bus, [{"name": "person", "conf": 0.9}])
    clock.advance(60)
    sv._tick()
    assert len(sent_text) == 1
    # objek baru muncul dalam jendela 30 detik yang sama → tidak ada kiriman baru
    _event(bus, [{"name": "chair", "conf": 0.6}])
    clock.advance(10)
    sv._tick()
    assert len(sent_text) == 1
    # lewat jendela + buffer terisi lagi → kiriman berikutnya
    clock.advance(25)
    sv._tick()
    assert len(sent_text) == 2


def test_photo_sent_when_include_photo_and_frame_available(make_supervisor):
    sv, bus, sent_text, sent_photo, clock = make_supervisor()
    bus.publish("vision.status", armed=True, alive=True)
    bus.publish("vision.frame", jpeg=b"\xff\xd8fakejpeg")
    _event(bus, [{"name": "person", "conf": 0.9}])
    clock.advance(60)
    sv._tick()
    assert sent_text and sent_photo
    path, caption = sent_photo[0]
    assert path.endswith(".jpg")
    assert "person x1" in caption


def test_photo_skipped_when_disabled(make_supervisor):
    sv, bus, sent_text, sent_photo, clock = make_supervisor(
        overrides={"vision_supervisor.include_photo": False})
    bus.publish("vision.status", armed=True, alive=True)
    bus.publish("vision.frame", jpeg=b"\xff\xd8fakejpeg")
    _event(bus, [{"name": "person", "conf": 0.9}])
    clock.advance(60)
    sv._tick()
    assert sent_text and sent_photo == []


def test_empty_or_unknown_objects_do_not_send(make_supervisor):
    sv, bus, sent_text, sent_photo, clock = make_supervisor()
    bus.publish("vision.status", armed=True, alive=True)
    _event(bus, [])
    _event(bus, [{"name": "  ", "conf": 0.9}])
    clock.advance(60)
    sv._tick()
    assert sent_text == []


def test_stop_stops_the_sender_thread(make_supervisor):
    sv, bus, sent_text, sent_photo, clock = make_supervisor()
    sv.stop()
    deadline = time.monotonic() + 2
    while sv._thread is not None and sv._thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert sv._thread is None or not sv._thread.is_alive()
