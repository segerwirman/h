"""Native outbound messaging with explicit confirmation and bounded targets."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult


class _MessageParams(BaseModel):
    platform: str = Field(description="whatsapp | telegram")
    recipient: str = Field(description="Kontak WhatsApp allowlist atau Telegram chat ID")
    message: str = Field(min_length=1, max_length=4000, description="Isi pesan")


class MessageSend(Tool):
    """One native confirmation boundary for voice outbound messages."""

    name = "message_send"
    description = (
        "Kirim pesan melalui WhatsApp allowlist atau Telegram chat ID yang "
        "diizinkan. Selalu minta konfirmasi sebelum mengirim."
    )
    params_schema = _MessageParams
    requires_confirmation = True
    timeout_s = 75

    def confirmation_text(self, **kwargs) -> str:
        platform = str(kwargs.get("platform", "") or "?").strip().title()
        recipient = str(kwargs.get("recipient", "") or "?").strip()
        message = " ".join(str(kwargs.get("message", "") or "").split())
        if len(message) > 120:
            message = message[:120] + "…"
        return f"Kirim pesan {platform} ke {recipient}: “{message}”?"

    async def run(self, platform: str, recipient: str, message: str, **_) -> ToolResult:
        target = str(platform or "").strip().casefold()
        content = str(message or "").strip()
        if target == "whatsapp":
            from jarvis.integrations.whatsapp_web import WhatsAppWebService

            try:
                result = await asyncio.to_thread(
                    WhatsAppWebService.get().send_message, recipient, content
                )
            except Exception as exc:  # noqa: BLE001
                return ToolResult.fail(f"WhatsApp gagal: {type(exc).__name__}")
            return ToolResult.success(
                result,
                display=f"Pesan WhatsApp terkirim ke {result.get('contact', recipient)}.",
            )
        if target == "telegram":
            return await TelegramSendMessage().run(chat_id=recipient, message=content)
        return ToolResult.fail("platform messaging hanya whatsapp atau telegram")


class _TelegramParams(BaseModel):
    chat_id: str = Field(description="Telegram chat ID yang telah di-allowlist")
    message: str = Field(min_length=1, max_length=4000, description="Isi pesan")


class TelegramSendMessage(Tool):
    """Telegram egress confined to configured local allowlist."""

    name = "telegram_send_message"
    description = "Kirim pesan ke Telegram chat ID allowlist. Selalu minta konfirmasi."
    params_schema = _TelegramParams
    requires_confirmation = True
    timeout_s = 30

    def confirmation_text(self, **kwargs) -> str:
        return f"Kirim pesan Telegram ke {kwargs.get('chat_id', '?')}?"

    async def run(self, chat_id: str, message: str, **_) -> ToolResult:
        from jarvis.integrations import telegram_control

        try:
            target = int(str(chat_id).strip())
        except ValueError:
            return ToolResult.fail("Telegram chat ID harus angka")
        if target not in telegram_control.allowed_ids():
            return ToolResult.fail("Telegram target tidak ada dalam allowlist lokal")
        try:
            from jarvis.agent.adapters.telegram import TelegramService

            service = TelegramService.get()
            if not service.running:
                return ToolResult.fail("Telegram service belum berjalan")
            await asyncio.to_thread(service.send_text, target, str(message))
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(f"Telegram gagal: {type(exc).__name__}")
        return ToolResult.success(
            {"platform": "telegram", "chat_id": target},
            display="Pesan Telegram terkirim.",
        )


__all__ = ["MessageSend", "TelegramSendMessage"]
