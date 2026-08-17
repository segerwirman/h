"""Consent-gated WhatsApp Web messaging and calling tools."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from jarvis.core import config, log, quiet
from jarvis.agent.base import Tool, ToolResult

_logger = log.get("agent.tools.whatsapp")

# Fase 16 — mode gerbang konfirmasi panggilan.
CALL_CONFIRM_MODES = ("always", "allowlisted_only", "never")


def available() -> bool:
    from jarvis.integrations.whatsapp_web import available as web_available

    return web_available()


def _call_confirmation_mode() -> str:
    """Mode gerbang panggilan; nilai tak dikenal jatuh ke ``always``.

    Gagal tertutup disengaja: salah ketik di config tidak boleh diam-diam
    menghapus konfirmasi untuk aksi eksternal.
    """
    try:
        value = config.get("whatsapp_web.call_confirmation", "always")
    except Exception:                                        # noqa: BLE001
        return "always"
    value = str(value or "").strip().casefold()
    return value if value in CALL_CONFIRM_MODES else "always"


def _is_allowlisted(contact: str) -> bool:
    """Apakah kontak ini sudah lolos allowlist manual?

    Memakai resolver YANG SAMA dengan yang mengeksekusi panggilan. Gerbang yang
    mencocokkan lebih ketat daripada eksekusi hanya akan bertanya untuk kontak
    yang toh tetap ditelepon.
    """
    name = " ".join(str(contact or "").split())
    if not name:
        return False
    try:
        from jarvis.integrations.whatsapp_web import resolve_contact

        return bool(resolve_contact(name).allowed)
    except Exception:                                        # noqa: BLE001
        return False


def _start_bridge() -> dict:
    """Seam bridge audio — dipisah agar dapat diuji tanpa perangkat nyata."""
    from jarvis.integrations.whatsapp_voice import start_bridge

    return start_bridge()


def _call_display(contact: str, state: str, audio: dict) -> str:
    """Satu kalimat keadaan panggilan + satu kalimat kemampuan bicara.

    Bentuk lama ("Memanggil X; virtual audio tidak siap") menyatukan dua fakta
    berbeda dalam satu klausa, sehingga model menyimpulkan salah satu dari dua
    arah yang sama-sama keliru: panggilannya gagal, atau audionya baik-baik
    saja. Keduanya dinyatakan terpisah dan eksplisit (S-1).
    """
    call_line = {
        "in_call": f"Panggilan WhatsApp ke {contact} tersambung.",
        "ringing": f"Panggilan WhatsApp ke {contact} berdering.",
    }.get(str(state), f"Panggilan WhatsApp ke {contact} dimulai.")
    if audio.get("active"):
        return f"{call_line} Jarvis bisa bicara di panggilan ini."
    reason = str(audio.get("error") or "audio bridge nonaktif").rstrip(".")
    return (f"{call_line} Jarvis TIDAK bisa bicara di panggilan ini "
            f"({reason}) — bicaralah sendiri.")


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
        "Mulai panggilan suara WhatsApp Web ke kontak allowlist. Kontak yang "
        "sudah di-allowlist langsung ditelepon; selain itu minta konfirmasi. "
        "Bila virtual-audio bridge siap, Jarvis berbicara langsung."
    )
    params_schema = _ContactParams
    requires_confirmation = True
    wants_context = True
    timeout_s = 75

    def needs_confirmation(self, **kwargs) -> bool:
        """Fase 16 — gerbang per-panggilan, bukan penghapusan gerbang.

        ``requires_confirmation`` tetap ``True``: mode ``always`` mengembalikan
        perilaku lama utuh, dan setiap jalur yang tidak mengenal mode ini tetap
        bertanya. Kontak allowlist sudah melewati satu gerbang manual ketika
        dimasukkan ke ``data/whatsapp_contacts.json`` — bertanya lagi setiap
        kali adalah gerbang kedua pada risiko yang sama.
        """
        mode = _call_confirmation_mode()
        if mode == "never":
            return False
        if mode == "allowlisted_only":
            return not _is_allowlisted(kwargs.get("contact", ""))
        return True

    def confirmation_text(self, **kwargs) -> str:
        return (
            f"Telepon {kwargs.get('contact', '?')} melalui WhatsApp sekarang?"
        )

    async def run(self, contact: str, _adapter=None, **_) -> ToolResult:
        from jarvis.integrations.whatsapp_web import WhatsAppWebService

        # Menghapus dialog boleh; menghapus kesempatan user MENYADARI bahwa
        # panggilan sedang berjalan tidak. Diumumkan sebelum dial, sehingga
        # tombol putus (whatsapp_hangup) masih satu langkah.
        skipped = not self.needs_confirmation(contact=contact)
        announcement = f"📞 Menelepon {contact} via WhatsApp" + (
            " (kontak allowlist — tanpa konfirmasi)" if skipped else "")
        if skipped:
            _logger.info("whatsapp.call.auto_approved",
                         mode=_call_confirmation_mode())
        if _adapter is not None:
            try:
                await _adapter.progress(announcement)
            except Exception as exc:                                # noqa: BLE001
                quiet.swallowed("agent.tools.whatsapp_web.progress_failed", exc)

        try:
            result = await asyncio.to_thread(
                WhatsAppWebService.get().start_call, contact
            )
            audio = await asyncio.to_thread(_start_bridge)
            payload = {**result, "audio_bridge": audio}
            return ToolResult.success(
                payload,
                display=_call_display(result.get("contact", contact),
                                      result.get("state", ""), audio),
            )
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
        from jarvis.integrations.whatsapp_web import WhatsAppWebService

        try:
            result = await asyncio.to_thread(
                WhatsAppWebService.get().answer_call
            )
            audio = await asyncio.to_thread(_start_bridge)
            return ToolResult.success(
                {**result, "audio_bridge": audio},
                display=_call_display("penelepon",
                                      result.get("state", "in_call"), audio),
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
