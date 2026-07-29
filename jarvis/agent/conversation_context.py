"""Bounded, in-memory continuity for immediate Jarvis follow-ups.

This is deliberately separate from durable memory and agent-session archival.
Only the latest user intent and safe spoken delivery are retained per logical
conversation. Raw display reports, tool output, and failure details never
enter this store.
"""
from __future__ import annotations

import re
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from jarvis.agent.interaction import ConversationDelivery

_FOLLOW_UPS = {
    "lanjutkan", "lanjut", "teruskan", "yang tadi", "buka hasilnya",
    "buka hasil", "buka itu", "buka tadi", "tampilkan hasilnya",
    "tampilkan hasil", "lihat hasilnya", "lihat hasil",
}
_URL_OR_PATH = re.compile(r"(?:https?://|www\.|[A-Za-z]:[\\/]|/[\w.-]+(?:/[\w.-]+)+)")
# Rujukan follow-up natural: "lanjutkan…", "hasil sebelumnya", "gunakan hasil",
# serta perintah membuka artefak yang baru dibuat: "buka/tampilkan/lihat …
# gambar/file/hasil/berkas … itu/tadi/tersebut/nya/barusan".
_FOLLOW_UP_RE = re.compile(
    r"^(?:lanjutkan|lanjut|teruskan)\b"
    r"|\b(?:hasil(?:nya)?\s+sebelumnya|gunakan\s+hasil)\b"
    r"|\b(?:buka|bukakan|tampilkan|tampilin|lihat|perlihatkan|"
    r"tunjukkan|tunjukan|show|open)\b"
    r"[^.\n]{0,40}?"
    r"\b(?:gambar|foto|image|file|berkas|hasil(?:nya)?|dokumen|itu|tadi|"
    r"tersebut|barusan|yang\s+tadi)\b",
    re.IGNORECASE,
)
# Rujukan artefak: perintah membuka sesuatu yang baru diproduksi JARVIS.
_ARTIFACT_REF_RE = re.compile(
    r"\b(?:buka|bukakan|tampilkan|tampilin|lihat|perlihatkan|tunjukkan|"
    r"tunjukan|show|open|putar|mainkan)\b",
    re.IGNORECASE,
)
_CONTEXT_MARKER = "\n\n[KONTEKS PERCAKAPAN LANGSUNG]"


@dataclass
class _ImmediateContext:
    last_intent: str = ""
    last_spoken: str = ""
    active_task: str = ""
    last_artifact: str = ""          # desktop-local path/URL artefak terakhir
    last_artifact_kind: str = ""     # "image" | "file" | "url" | ""
    recent_intents: deque[str] = field(default_factory=lambda: deque(maxlen=3))
    recent_template_ids: deque[str] = field(default_factory=lambda: deque(maxlen=4))


class ConversationContextStore:
    """Small LRU of immediate, non-durable conversation state."""

    def __init__(self, max_sessions: int = 32) -> None:
        self._max_sessions = max(1, int(max_sessions))
        self._sessions: OrderedDict[str, _ImmediateContext] = OrderedDict()
        self._lock = threading.Lock()

    def remember_success(
        self,
        conversation_id: str,
        *,
        task: str,
        delivery: ConversationDelivery,
    ) -> None:
        """Keep only facts already approved for speech after a success."""

        key = _key(conversation_id)
        if not key:
            return
        spoken = _safe_spoken(delivery.speech_text)
        with self._lock:
            context = self._sessions.pop(key, _ImmediateContext())
            intent = _safe_task(task)[:800]
            context.last_intent = intent
            if intent and (not context.recent_intents or context.recent_intents[-1] != intent):
                context.recent_intents.append(intent)
            context.last_spoken = spoken[:600]
            context.active_task = ""
            if delivery.mode:
                context.recent_template_ids.append(str(delivery.mode)[:48])
            self._sessions[key] = context
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)

    def remember_artifact(
        self, conversation_id: str, *, path: str, kind: str = "file"
    ) -> None:
        """Ingat artefak terakhir yang JARVIS produksi (mis. gambar hasil
        image_generate) agar follow-up 'buka gambar itu' bisa membukanya.

        Ini SENGAJA tidak masuk blok konteks prompt/remote/ucapan — hanya
        dipakai lokal untuk membuka file yang baru dibuat. Isolasi privacy
        durable memory tetap terjaga.
        """
        key = _key(conversation_id)
        clean = str(path or "").strip()
        if not key or not clean:
            return
        with self._lock:
            context = self._sessions.pop(key, _ImmediateContext())
            context.last_artifact = clean[:600]
            context.last_artifact_kind = str(kind or "file")[:16]
            self._sessions[key] = context
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)

    def last_artifact(self, conversation_id: str) -> tuple[str, str]:
        """(path, kind) artefak terakhir untuk conversation ini; ('','') bila
        belum ada."""
        with self._lock:
            context = self._sessions.get(_key(conversation_id))
            if context is None or not context.last_artifact:
                return "", ""
            return context.last_artifact, context.last_artifact_kind

    def begin_task(self, conversation_id: str, task: str) -> None:
        """Track one bounded in-flight task; completion clears it atomically."""
        key = _key(conversation_id)
        task = str(task or "").strip()[:800]
        if not key or not task:
            return
        with self._lock:
            context = self._sessions.pop(key, _ImmediateContext())
            context.active_task = task
            self._sessions[key] = context
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)

    def active_task(self, conversation_id: str) -> str:
        with self._lock:
            context = self._sessions.get(_key(conversation_id))
            return context.active_task if context is not None else ""

    def augment(self, conversation_id: str, task: str) -> str:
        """Return a private context block only for exact, unambiguous references."""

        original = str(task or "").strip()
        if not _is_follow_up(original):
            self.begin_task(conversation_id, original)
            return original
        with self._lock:
            context = self._sessions.get(_key(conversation_id))
            if context is None or not context.last_intent or not context.last_spoken:
                return original
            self._sessions.move_to_end(_key(conversation_id))
            previous_task = context.last_intent
            previous_spoken = context.last_spoken
            recent = " | ".join(context.recent_intents)[:800]
        return (
            f"{original}\n\n[KONTEKS PERCAKAPAN LANGSUNG]\n"
            f"Tugas sebelumnya: {previous_task}\n"
            f"Riwayat tugas ringkas: {recent}\n"
            f"Hasil terakhir (brief aman): {previous_spoken}\n"
            "Gunakan konteks ini hanya untuk menyelesaikan rujukan pengguna."
        )

    def context_block(self, conversation_id: str) -> str:
        """Safe, compact block for optional naturalization only."""

        with self._lock:
            context = self._sessions.get(_key(conversation_id))
            if context is None or not context.last_spoken:
                return ""
            return (
                "Konteks percakapan langsung (jangan menambah fakta baru): "
                f"tugas terakhir={context.last_intent}; "
                f"brief terakhir={context.last_spoken}"
            )


def _key(value: object) -> str:
    return str(value or "").strip()[:96]


def _normalise_reference(value: str) -> str:
    return value.casefold().strip().rstrip(".?!")


def _is_follow_up(value: str) -> bool:
    return _normalise_reference(value) in _FOLLOW_UPS or bool(_FOLLOW_UP_RE.search(value))


def is_follow_up(value: str) -> bool:
    """Public: apakah teks user merujuk hasil/tugas sebelumnya."""
    return _is_follow_up(str(value or ""))


def is_artifact_reference(value: str) -> bool:
    """Apakah user meminta MEMBUKA artefak yang baru dibuat (bukan sekadar
    melanjutkan tugas). Contoh: 'buka gambar itu', 'tampilkan hasilnya',
    'lihat file tadi'. Dipakai UI untuk membuka file terakhir secara langsung.
    """
    text = str(value or "")
    if not _ARTIFACT_REF_RE.search(text):
        return False
    return bool(_FOLLOW_UP_RE.search(text)) or _normalise_reference(text) in _FOLLOW_UPS


def _safe_task(value: object) -> str:
    return str(value or "").split(_CONTEXT_MARKER, 1)[0].strip()


def _safe_spoken(value: object) -> str:
    text = " ".join(str(value or "").split())
    return _URL_OR_PATH.sub("", text).strip()


STORE = ConversationContextStore()
