"""Consent-gated WhatsApp Web messaging and calling tools."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult


def available() -> bool:
    from jarvis.integrations.whatsapp_web import available as web_available

    return web_available()


class _NoParams(BaseModel):
    pass


class _ContactParams(BaseModel):
    contact: str = Field(
        description=(
            "Nama persis kontak allowlist, atau nomor bila direct numbers "
            "diizinkan. Jangan menebak."
        )
    )


class _MessageParams(_ContactParams):
    message: str = Field(
        min_length=1,
        max_length=4000,
        description="Isi pesan yang akan dikirim.",
    )


class WhatsAppOpen(Tool):
    name = "whatsapp_open"
    description = (
        "Buka profil WhatsApp Web khusus Jarvis dan laporkan apakah sudah "
        "login. Jika login_required, minta user memindai QR."
    )
    params_schema = _NoParams
    timeout_s = 75

    async def run(self, **_) -> ToolResult:
        from jarvis.integrations.whatsapp_web import WhatsAppWebService

        try:
            result = await asyncio.to_thread(WhatsAppWebService.get().open)
            state = str(result.get("state", "unknown"))
            message = {
                "ready": "WhatsApp Web siap.",
                "login_required": (
                    "WhatsApp Web menunggu pemindaian QR di jendela Chrome."
                ),
            }.get(state, f"Status WhatsApp Web: {state}.")
            return ToolResult.success(result, display=message)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(str(exc))


class WhatsAppStatus(Tool):
    name = "whatsapp_status"
    description = (
        "Baca status WhatsApp Web dan audio bridge tanpa mengubah panggilan."
    )
    params_schema = _NoParams
    read_only = True
    timeout_s = 15

    async def run(self, **_) -> ToolResult:
        from jarvis.integrations.whatsapp_voice import bridge_status
        from jarvis.integrations.whatsapp_web import WhatsAppWebService

        try:
            web = await asyncio.to_thread(WhatsAppWebService.get().status)
            result = {"web": web, "audio_bridge": bridge_status()}
            return ToolResult.success(
                result,
                display=f"WhatsApp: {web.get('state', 'unknown')}",
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(str(exc))


class WhatsAppListContacts(Tool):
    name = "whatsapp_list_contacts"
    description = (
        "Daftar nama kontak WhatsApp yang sudah di-allowlist. Nomor lengkap "
        "tidak pernah diberikan kepada model."
    )
    params_schema = _NoParams
    read_only = True
    timeout_s = 10

    async def run(self, **_) -> ToolResult:
        from jarvis.integrations.whatsapp_web import load_contacts

        contacts = [
            item.safe_dict()
            for item in await asyncio.to_thread(load_contacts)
            if item.allowed
        ]
        return ToolResult.success(
            contacts,
            display=f"{len(contacts)} kontak WhatsApp diizinkan.",
        )


class WhatsAppAudioDevices(Tool):
    name = "whatsapp_audio_devices"
    description = (
        "Daftar perangkat audio input/output yang bisa dipilih untuk bridge "
        "panggilan WhatsApp. Gunakan untuk mendiagnosis kenapa Jarvis belum "
        "bisa mendengar/berbicara di panggilan."
    )
    params_schema = _NoParams
    read_only = True
    timeout_s = 15

    async def run(self, **_) -> ToolResult:
        from jarvis.integrations.whatsapp_voice import list_audio_devices

        devices = await asyncio.to_thread(list_audio_devices)
        return ToolResult.success(
            devices,
            display=(
                f"{len(devices.get('inputs', []))} input / "
                f"{len(devices.get('outputs', []))} output audio"
            ),
        )


class WhatsAppSendMessage(Tool):
    name = "whatsapp_send_message"
    description = (
        "Kirim satu pesan melalui WhatsApp Web kepada kontak allowlist. "
        "Tindakan eksternal: selalu minta konfirmasi."
    )
    params_schema = _MessageParams
    requires_confirmation = True
    timeout_s = 75

    def confirmation_text(self, **kwargs) -> str:
        contact = str(kwargs.get("contact", "") or "?")
        message = " ".join(str(kwargs.get("message", "") or "").split())
        if len(message) > 120:
            message = message[:120] + "…"
        return f"Kirim pesan WhatsApp ke {contact}: “{message}”?"

    async def run(self, contact: str, message: str, **_) -> ToolResult:
        from jarvis.integrations.whatsapp_web import WhatsAppWebService

        try:
            result = await asyncio.to_thread(
                WhatsAppWebService.get().send_message,
                contact,
                message,
            )
            return ToolResult.success(
                result,
                display=f"Pesan terkirim ke {result.get('contact', contact)}.",
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(str(exc))


class WhatsAppCall(Tool):
    name = "whatsapp_call"
    description = (
        "Mulai panggilan suara WhatsApp Web ke kontak allowlist. Selalu minta "
        "konfirmasi. Bila virtual-audio bridge siap, Jarvis berbicara langsung."
    )
    params_schema = _ContactParams
    requires_confirmation = True
    timeout_s = 75

    def confirmation_text(self, **kwargs) -> str:
        return (
            f"Telepon {kwargs.get('contact', '?')} melalui WhatsApp sekarang?"
        )

    async def run(self, contact: str, **_) -> ToolResult:
        from jarvis.integrations.whatsapp_voice import start_bridge
        from jarvis.integrations.whatsapp_web import WhatsAppWebService

        try:
            result = await asyncio.to_thread(
                WhatsAppWebService.get().start_call, contact
            )
            audio = await asyncio.to_thread(start_bridge)
            payload = {**result, "audio_bridge": audio}
            if audio.get("active"):
                display = (
                    f"Memanggil {result.get('contact', contact)}; "
                    "audio Jarvis aktif."
                )
            else:
                display = (
                    f"Memanggil {result.get('contact', contact)}; "
                    f"{audio.get('error', 'audio bridge nonaktif')}"
                )
            return ToolResult.success(payload, display=display)
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(str(exc))


class WhatsAppAnswer(Tool):
    name = "whatsapp_answer"
    description = (
        "Jawab panggilan WhatsApp yang sedang masuk. Selalu minta konfirmasi."
    )
    params_schema = _NoParams
    requires_confirmation = True
    timeout_s = 30

    def confirmation_text(self, **_) -> str:
        return "Jawab panggilan WhatsApp yang sedang masuk?"

    async def run(self, **_) -> ToolResult:
        from jarvis.integrations.whatsapp_voice import start_bridge
        from jarvis.integrations.whatsapp_web import WhatsAppWebService

        try:
            result = await asyncio.to_thread(
                WhatsAppWebService.get().answer_call
            )
            audio = await asyncio.to_thread(start_bridge)
            return ToolResult.success(
                {**result, "audio_bridge": audio},
                display=(
                    "Panggilan WhatsApp dijawab; "
                    + (
                        "audio Jarvis aktif."
                        if audio.get("active")
                        else audio.get("error", "audio bridge nonaktif.")
                    )
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult.fail(str(exc))


class WhatsAppHangup(Tool):
    name = "whatsapp_hangup"
    description = (
        "Akhiri panggilan WhatsApp aktif dan hentikan audio bridge. "
        "Tidak memerlukan konfirmasi tambahan."
    )
    params_schema = _NoParams
    timeout_s = 20

    async def run(self, **_) -> ToolResult:
        from jarvis.integrations.whatsapp_voice import stop_bridge
        from jarvis.integrations.whatsapp_web import WhatsAppWebService

        try:
            result = await asyncio.to_thread(
                WhatsAppWebService.get().hangup
            )
            await asyncio.to_thread(stop_bridge)
            return ToolResult.success(
                result,
                display=(
                    "Panggilan WhatsApp diakhiri."
                    if result.get("changed")
                    else "Tidak ada panggilan WhatsApp aktif."
                ),
            )
        except Exception as exc:  # noqa: BLE001
            await asyncio.to_thread(stop_bridge)
            return ToolResult.fail(str(exc))
