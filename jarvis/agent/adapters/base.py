"""Adapter I/O agent (§5.1) — agent core tidak tahu bicara ke UI, Telegram,
atau cron. Semua metode async; implementasi wajib tidak pernah raise ke loop.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Adapter(ABC):
    name: str = "base"
    # cron/headless → clarify tidak boleh bertanya (spec §3.1.G)
    interactive: bool = True
    # Only the desktop UI adapter may grant confirmation for desktop-safe mutation.
    desktop_local: bool = False

    @abstractmethod
    async def send(self, content: str, **kwargs) -> None:
        """Kirim jawaban/hasil akhir ke user."""

    async def progress(self, text: str) -> None:
        """Update progres ringan (tool berjalan dsb.). Default: no-op."""

    async def ask(self, question: str,
                  options: list[str] | None = None) -> str | None:
        """Pertanyaan klarifikasi/konfirmasi. None = tidak terjawab."""
        return None

    async def send_image(self, path: str, caption: str = "") -> None:
        await self.send(f"[gambar] {path} {caption}".strip())

    async def native_action(self, action: str, **kwargs) -> bool:
        """Queue a local UI action when this adapter owns a desktop surface."""

        return False


class NullAdapter(Adapter):
    """Untuk cron/tes — mengumpulkan output, tidak pernah bertanya."""

    name = "cron"
    interactive = False

    def __init__(self):
        self.outputs: list[str] = []
        self.assumptions: list[str] = []

    async def send(self, content: str, **kwargs) -> None:
        self.outputs.append(content)

    async def ask(self, question: str,
                  options: list[str] | None = None) -> str | None:
        # catat asumsi, jangan blokir (spec: sesi cron tidak bertanya)
        self.assumptions.append(question)
        return None
