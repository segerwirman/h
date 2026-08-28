"""Optional virtual-audio bridge between WhatsApp Web and Gemini Live.

The bridge is default-off.  It requires two distinct virtual audio cables:

* ``remote_input_device`` captures the device selected as WhatsApp's speaker;
* ``remote_output_device`` is selected as WhatsApp's microphone.

Incoming call audio is placed directly on JarvisLive's Gemini uplink queue.
Jarvis audio is mirrored directly to WhatsApp's virtual microphone.  No
speaker-to-microphone acoustic loop is used, so echo and latency stay bounded.
"""
from __future__ import annotations

import atexit
import queue
import threading
import weakref

from jarvis.core import config, log

_logger = log.get("whatsapp.voice")
_legacy = None
_live_ref: weakref.ReferenceType | None = None


def _enter_communication_mode() -> int:
    from jarvis.agent.communication_mode import enter

    return enter()


def _exit_communication_mode() -> bool:
    from jarvis.agent.communication_mode import exit

    return exit()


def list_audio_devices() -> dict[str, list[dict[str, object]]]:
    """Return safe device metadata needed to configure the virtual bridge."""

    try:
        import sounddevice as sd

        devices = sd.query_devices()
    except Exception as exc:                                  # noqa: BLE001
        return {
            "inputs": [],
            "outputs": [],
            "error": [{
                "message": f"sounddevice tidak siap ({type(exc).__name__})"
            }],
        }
    inputs: list[dict[str, object]] = []
    outputs: list[dict[str, object]] = []
    for index, raw in enumerate(devices):
        entry = dict(raw)
        item = {
            "index": index,
            "name": str(entry.get("name", ""))[:160],
        }
        if int(entry.get("max_input_channels", 0) or 0) > 0:
            inputs.append({
                **item,
                "channels": int(entry.get("max_input_channels", 0)),
            })
        if int(entry.get("max_output_channels", 0) or 0) > 0:
            outputs.append({
                **item,
                "channels": int(entry.get("max_output_channels", 0)),
            })
    return {"inputs": inputs, "outputs": outputs}


def _live():
    return _live_ref() if _live_ref is not None else None


class _TapQueue:
    """Delegate asyncio.Queue while mirroring consumed output chunks."""

    def __init__(self, inner, bridge: "WhatsAppAudioBridge"):
        self._inner = inner
        self._bridge = bridge

    async def get(self):
        chunk = await self._inner.get()
        self._bridge.tap_output(chunk)
        if (
            self._bridge.active
            and not bool(
                config.get(
                    "whatsapp_web.audio_bridge.monitor_local_output", True
                )
            )
        ):
            return b"\0" * len(chunk)
        return chunk

    def __getattr__(self, name):
        return getattr(self._inner, name)


class WhatsAppAudioBridge:
    _instance: "WhatsAppAudioBridge | None" = None
    _instance_lock = threading.Lock()

    @classmethod
    def get(cls) -> "WhatsAppAudioBridge":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._lock = threading.Lock()
        self._active = False
        self._input_stream = None
        self._output_stream = None
        self._output_queue: queue.Queue = queue.Queue(maxsize=240)
        self._output_thread: threading.Thread | None = None
        self._last_error = ""

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def status(self) -> dict:
        input_device = str(config.get(
            "whatsapp_web.audio_bridge.remote_input_device", "") or "").strip()
        output_device = str(config.get(
            "whatsapp_web.audio_bridge.remote_output_device", "") or "").strip()
        return {
            "enabled": bool(
                config.get("whatsapp_web.audio_bridge.enabled", False)
            ),
            "active": self.active,
            "error": self._last_error,
            "input_configured": bool(input_device),
            "output_configured": bool(output_device),
        }

    @staticmethod
    def _put_live_audio(instance, payload: bytes) -> None:
        out_queue = getattr(instance, "out_queue", None)
        if out_queue is None:
            return
        message = {
            "data": payload,
            "mime_type": "audio/pcm;rate=16000",
        }
        try:
            out_queue.put_nowait(message)
        except Exception:
            try:
                out_queue.get_nowait()
                out_queue.put_nowait(message)
            except Exception:
                pass

    def _capture_callback(self, indata, _frames, _time_info, status) -> None:
        if status:
            _logger.info("whatsapp.audio_input_status", status=str(status))
        instance = _live()
        loop = getattr(instance, "_loop", None) if instance is not None else None
        if (
            not self.active
            or instance is None
            or loop is None
            or not loop.is_running()
        ):
            return
        payload = bytes(indata)
        loop.call_soon_threadsafe(self._put_live_audio, instance, payload)

    def _output_worker(self) -> None:
        stream = self._output_stream
        while self.active and stream is not None:
            try:
                chunk = self._output_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if chunk is None:
                break
            try:
                stream.write(chunk)
            except Exception as exc:  # noqa: BLE001
                self._last_error = f"audio output gagal: {str(exc)[:120]}"
                _logger.warning(
                    "whatsapp.audio_output_failed", error=self._last_error
                )
                self.stop()
                break

    def start(self) -> dict:
        if self.active:
            return self.status()
        if not bool(
            config.get("whatsapp_web.audio_bridge.enabled", False)
        ):
            return {
                "enabled": False,
                "active": False,
                "error": (
                    "Audio bridge nonaktif; panggilan tersambung untuk "
                    "komunikasi manual."
                ),
            }
        instance = _live()
        if (
            instance is None
            or getattr(instance, "_loop", None) is None
            or getattr(instance, "out_queue", None) is None
        ):
            return {
                "enabled": True,
                "active": False,
                "error": "Gemini Live belum siap untuk audio panggilan.",
            }
        input_device = str(
            config.get(
                "whatsapp_web.audio_bridge.remote_input_device", ""
            )
            or ""
        ).strip()
        output_device = str(
            config.get(
                "whatsapp_web.audio_bridge.remote_output_device", ""
            )
            or ""
        ).strip()
        if not input_device or not output_device:
            return {
                "enabled": True,
                "active": False,
                "error": (
                    "Dua virtual audio device wajib dikonfigurasi untuk "
                    "percakapan Jarvis."
                ),
            }
        if input_device.casefold() == output_device.casefold():
            return {
                "enabled": True,
                "active": False,
                "error": (
                    "Perangkat input dan output virtual WhatsApp harus "
                    "berbeda."
                ),
            }
        while True:
            try:
                self._output_queue.get_nowait()
            except queue.Empty:
                break
        input_stream = None
        output_stream = None
        try:
            import sounddevice as sd

            input_stream = sd.RawInputStream(
                device=input_device,
                samplerate=16000,
                channels=1,
                dtype="int16",
                blocksize=1600,
                callback=self._capture_callback,
            )
            output_stream = sd.RawOutputStream(
                device=output_device,
                samplerate=24000,
                channels=1,
                dtype="int16",
                blocksize=1200,
            )
            input_stream.start()
            output_stream.start()
        except Exception as exc:  # noqa: BLE001
            for stream in (input_stream, output_stream):
                if stream is None:
                    continue
                try:
                    stream.close()
                except Exception:
                    pass
            self._last_error = f"virtual audio tidak siap: {str(exc)[:150]}"
            _logger.warning(
                "whatsapp.audio_start_failed", error=self._last_error
            )
            return {
                "enabled": True,
                "active": False,
                "error": self._last_error,
            }
        with self._lock:
            self._input_stream = input_stream
            self._output_stream = output_stream
            self._active = True
            self._last_error = ""
        instance._phone_active = True
        try:
            _enter_communication_mode()
            self._output_thread = threading.Thread(
                target=self._output_worker,
                daemon=True,
                name="jarvis-whatsapp-audio",
            )
            self._output_thread.start()
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"communication lock gagal: {type(exc).__name__}"
            _logger.warning(
                "whatsapp.communication_lock_failed",
                error=type(exc).__name__,
            )
            self.stop()
            return self.status()
        _logger.info("whatsapp.audio_started")
        return self.status()

    def tap_output(self, chunk: bytes) -> None:
        if not self.active or not chunk:
            return
        try:
            self._output_queue.put_nowait(bytes(chunk))
        except queue.Full:
            try:
                self._output_queue.get_nowait()
                self._output_queue.put_nowait(bytes(chunk))
            except Exception:
                pass

    def stop(self) -> dict:
        try:
            with self._lock:
                was_active = self._active
                self._active = False
                input_stream = self._input_stream
                output_stream = self._output_stream
                self._input_stream = None
                self._output_stream = None
            instance = _live()
            if instance is not None:
                instance._phone_active = False
            for stream in (input_stream, output_stream):
                if stream is None:
                    continue
                try:
                    stream.stop()
                except Exception:
                    pass
                try:
                    stream.close()
                except Exception:
                    pass
            thread = self._output_thread
            if thread and thread is not threading.current_thread():
                thread.join(timeout=2)
            self._output_thread = None
            while True:
                try:
                    self._output_queue.get_nowait()
                except queue.Empty:
                    break
            if was_active:
                _logger.info("whatsapp.audio_stopped")
            return self.status()
        finally:
            _exit_communication_mode()


def install(legacy_module) -> None:
    """Attach to the wrapped legacy pipeline without changing FROZEN files."""

    global _legacy
    _legacy = legacy_module
    cls = legacy_module.JarvisLive

    original_init = cls.__init__
    if not getattr(original_init, "_jarvis_whatsapp_voice", False):
        def wrapped_init(self, *args, **kwargs):
            global _live_ref
            original_init(self, *args, **kwargs)
            _live_ref = weakref.ref(self)

        wrapped_init._jarvis_whatsapp_voice = True
        cls.__init__ = wrapped_init

    original_play = cls._play_audio
    if not getattr(original_play, "_jarvis_whatsapp_voice", False):
        async def wrapped_play(self):
            inner = self.audio_in_queue
            proxy = _TapQueue(inner, WhatsAppAudioBridge.get())
            self.audio_in_queue = proxy
            try:
                return await original_play(self)
            finally:
                if self.audio_in_queue is proxy:
                    self.audio_in_queue = inner

        wrapped_play._jarvis_whatsapp_voice = True
        cls._play_audio = wrapped_play


def start_bridge() -> dict:
    return WhatsAppAudioBridge.get().start()


def stop_bridge() -> dict:
    return WhatsAppAudioBridge.get().stop()


def bridge_status() -> dict:
    return WhatsAppAudioBridge.get().status()


def _shutdown_existing() -> None:
    with WhatsAppAudioBridge._instance_lock:
        current = WhatsAppAudioBridge._instance
    if current is not None:
        current.stop()


atexit.register(_shutdown_existing)


__all__ = [
    "WhatsAppAudioBridge",
    "bridge_status",
    "install",
    "list_audio_devices",
    "start_bridge",
    "stop_bridge",
]
