"""Safe transport compatibility for Gemini Live input frames.

The frozen legacy voice loop owns scheduling and connection lifecycle.  This
adapter only normalizes what leaves that boundary — PCM metadata, the
realtime_input channel each frame travels on, and the role on client-content
turns — and records the last non-sensitive frame shape when the server rejects a
request.
"""
from __future__ import annotations

from jarvis.core import log
from jarvis.integrations import voice_live_lifecycle

_logger = log.get("voice.live_transport")
_PCM_16KHZ = "audio/pcm;rate=16000"
_PATCH_MARKER = "_jarvis_live_transport_installed"
_CONTENT_MARKER = "_jarvis_live_turn_role_installed"
_ROLE = "user"


def _normalise(message):
    """Return a Live-compatible PCM message without retaining audio content."""
    if not isinstance(message, dict):
        return message
    if message.get("mime_type") != "audio/pcm":
        return message
    return {**message, "mime_type": _PCM_16KHZ}


def _input_kwargs(message) -> dict:
    """Route a frame to a realtime_input channel the Live API still accepts.

    ``send_realtime_input(media=...)`` serialises to ``realtime_input.media_chunks``,
    which current Live models reject outright — the server closes the socket with
    1007 ("media_chunks is deprecated. Use audio, video, or text instead") on the
    first mic frame, so every session died a few ms after setup.  PCM therefore
    goes out on ``audio`` and frames on ``video``; anything unrecognised keeps the
    legacy field so this adapter never swallows a payload it does not understand.
    """
    if isinstance(message, dict):
        mime = str(message.get("mime_type") or "")
        if mime.startswith("audio/"):
            return {"audio": message}
        if mime.startswith("image/") or mime.startswith("video/"):
            return {"video": message}
    return {"media": message}


def _with_role(turns):
    """Return client-content turns carrying the role the Live API requires.

    Live models reject a turn that omits ``role`` with the same 1007 close, and
    the ``{"parts": [...]}`` shorthand is used by the frozen voice loop and by
    every notice/task bridge.  Completing the role here keeps those call sites
    untouched; a turn that already names a role is passed through as-is.
    """
    if isinstance(turns, dict):
        return turns if turns.get("role") else {**turns, "role": _ROLE}
    if isinstance(turns, (list, tuple)):
        return [_with_role(turn) for turn in turns]
    return turns


def _shape(message) -> dict[str, int | str]:
    """Describe a payload safely: metadata only, never audio bytes."""
    if not isinstance(message, dict):
        return {"message_type": type(message).__name__}
    data = message.get("data", b"")
    return {
        "message_type": "dict",
        "mime_type": str(message.get("mime_type", "")),
        "bytes": len(data) if isinstance(data, (bytes, bytearray, memoryview)) else 0,
    }


def _safe_error_fields(exc: BaseException) -> dict[str, object]:
    return voice_live_lifecycle.classify(exc).safe_fields()


def install_turn_role() -> bool:
    """Complete the turn role on every outbound Live client-content message.

    Patched on the SDK session rather than on the voice loop because the same
    role-less shorthand is sent from the frozen loop, its notice bridges, and the
    vision session — all of which hold their own session reference.
    """
    try:
        from google.genai import live as genai_live
    except Exception:  # SDK absent in trimmed installs — nothing to normalise
        return False

    session_cls = getattr(genai_live, "AsyncSession", None)
    original = getattr(session_cls, "send_client_content", None)
    if original is None or getattr(session_cls, _CONTENT_MARKER, False):
        return False

    async def send_client_content(self, *, turns=None, turn_complete: bool = True):
        await original(self, turns=_with_role(turns), turn_complete=turn_complete)

    session_cls.send_client_content = send_client_content
    setattr(session_cls, _CONTENT_MARKER, True)
    return True


def install(legacy_module) -> bool:
    """Install once; preserve legacy behaviour apart from PCM MIME correction."""
    live_cls = legacy_module.JarvisLive

    # The SDK can replace its session class across reconnects or reloads while
    # this transport marker correctly remains on the legacy live class.  Give
    # the fresh SDK class its own idempotent repair before returning early.
    install_turn_role()

    if getattr(live_cls, _PATCH_MARKER, False):
        return False

    receive_audio = live_cls._receive_audio

    async def send_realtime(self) -> None:
        while True:
            message = _normalise(await self.out_queue.get())
            self._voice_live_last_input = _shape(message)
            await self.session.send_realtime_input(**_input_kwargs(message))

    async def receive_with_context(self) -> None:
        try:
            await receive_audio(self)
        except Exception as exc:  # re-raise: legacy reconnect policy remains authoritative
            _logger.error(
                "voice.live_receive_rejected",
                **_safe_error_fields(exc),
                last_input=getattr(self, "_voice_live_last_input", None),
            )
            raise

    live_cls._send_realtime = send_realtime
    live_cls._receive_audio = receive_with_context
    setattr(live_cls, _PATCH_MARKER, True)
    _logger.info("voice.live_transport.installed")
    return True
