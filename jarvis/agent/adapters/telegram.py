"""Telegram Control native (MK50 §11) — kendali Jarvis dari mana saja.

KEAMANAN WAJIB: allowlist terenkripsi. Update dari user lain
diabaikan TOTAL (tanpa balasan — bot tidak membocorkan keberadaannya).
Token/ID hanya dari ``secrets_store``, tidak pernah di-log.

Bot berjalan di thread sendiri (python-telegram-bot v22, polling).
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from concurrent.futures import Future
from pathlib import Path

from jarvis.core import config, log
from jarvis.agent.adapters.base import Adapter
from jarvis.agent.router import Tier as ExecutionTier
from jarvis.agent.router import classify as classify_execution
from jarvis.integrations import telegram_control

_logger = log.get("agent.adapter.telegram")


def _token() -> str:
    return telegram_control.token()


def _allowed_ids() -> list[int]:
    return list(telegram_control.allowed_ids())


def enabled() -> bool:
    return telegram_control.enabled()


def polling_options() -> dict[str, object]:
    """Polling policy: preserve paired updates across a controlled restart."""
    return {
        "close_loop": False,
        "stop_signals": None,
        "allowed_updates": None,
        "drop_pending_updates": False,
    }


def command_menu() -> tuple[tuple[str, str], ...]:
    """Telegram's slash-command menu; descriptions stay accurate remotely."""
    return (
        ("start", "Mulai JARVIS"),
        ("help", "Bantuan dan batas remote"),
        ("status", "Status runtime dan tugas"),
        ("tools", "Tool remote yang tersedia"),
        ("stop", "Batalkan tugas (butuh desktop bila gateway aktif)"),
        ("todo", "Lihat todo tugas aktif"),
        ("memory", "Cari memori: /memory <query>"),
        ("cron", "Lihat jadwal"),
        ("screen", "Ambil screenshot desktop"),
        ("skills", "Daftar skill"),
        ("session", "Reset sesi percakapan"),
        ("confirm", "Setujui konfirmasi yang menunggu"),
    )


class TelegramService:
    """Singleton — polling thread + jembatan kirim lintas-thread."""

    name = "telegram"
    _instance: "TelegramService | None" = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "TelegramService":
        with cls._lock:
            if cls._instance is None:
                cls._instance = TelegramService()
            return cls._instance

    def __init__(self, gateway_manager=None):
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._app = None
        self.running = False
        self._pending: dict[str, Future] = {}       # qid → Future jawaban
        self._pending_chat: dict[str, int] = {}     # qid → chat
        self._pending_confirm: dict[int, str] = {}  # chat → qid
        self._await_text: dict[int, Future] = {}    # chat → Future teks bebas
        self._chat_sessions: dict[int, str] = {}    # konteks logis adapter
        from jarvis.agent.remote_setup import get_setup_queue
        self._setup_queue = get_setup_queue()      # Fase 15S: runtime-owned singleton
        from jarvis.gateway.registry import GatewayRegistry
        self._gateway_registry = GatewayRegistry()
        self._gateway_manager = gateway_manager
        self._gateway_updates: dict[tuple[str, str], object] = {}

    def bind_gateway_manager(self, gateway_manager) -> None:
        self._gateway_manager = gateway_manager

    def health(self) -> dict[str, str]:
        return {"state": "connected" if self.running else "stopped"}

    def handle_gateway_inbound(self, inbound) -> None:
        """Resume normalized ingress only after GatewayManager accepts it."""
        key = (str(inbound.conversation_id), str(inbound.message_id))
        update = self._gateway_updates.pop(key, None)
        if update is None:
            return

        async def _run() -> None:
            await self._handle_task(update, inbound.text, inbound.execution_context())

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(lambda: loop.create_task(_run()))

    def _receive_gateway_text(self, update, text: str) -> bool:
        """Normalize a text-bearing Telegram update for the manager boundary."""
        if self._gateway_manager is None:
            return False
        chat_id = update.effective_chat.id
        message_id = getattr(update.message, "message_id", "") or \
            f"legacy-{id(update.message)}"
        actor_id = getattr(getattr(update, "effective_user", None), "id", "")
        key = (str(chat_id), str(message_id))
        self._gateway_updates[key] = update
        accepted = self._gateway_manager.receive(
            "telegram", str(message_id), str(chat_id), str(actor_id), str(text or ""))
        if not accepted:
            self._gateway_updates.pop(key, None)
        return accepted

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> bool:
        if not enabled():
            _logger.info("telegram.disabled",
                         reason="toggle/kredensial/allowlist belum siap")
            return False
        if self._thread is not None and self._thread.is_alive():
            return True
        self._thread = threading.Thread(target=self._main, daemon=True,
                                        name="agent-telegram")
        self._thread.start()
        return True

    def stop(self) -> None:
        app, loop = self._app, self._loop
        if app is not None and loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(app.stop_running)
            except Exception:                                # noqa: BLE001
                pass
        self.running = False
        thread = self._thread
        if (thread is not None and thread.is_alive()
                and thread is not threading.current_thread()):
            thread.join(timeout=8)
        if thread is not None and not thread.is_alive():
            self._thread = None

    def _main(self) -> None:
        loop: asyncio.AbstractEventLoop | None = None
        try:
            from telegram import Update
            from telegram.ext import (Application, CallbackQueryHandler,
                                      CommandHandler, MessageHandler,
                                      filters)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            app = (Application.builder().token(_token())
                   .post_init(self._register_command_menu).build())
            self._app = app

            app.add_handler(CommandHandler("start", self._cmd_start))
            app.add_handler(CommandHandler("help", self._cmd_help))
            app.add_handler(CommandHandler("status", self._cmd_status))
            app.add_handler(CommandHandler("tools", self._cmd_tools))
            app.add_handler(CommandHandler("stop", self._cmd_stop))
            app.add_handler(CommandHandler("todo", self._cmd_todo))
            app.add_handler(CommandHandler("memory", self._cmd_memory))
            app.add_handler(CommandHandler("cron", self._cmd_cron))
            app.add_handler(CommandHandler("screen", self._cmd_screen))
            app.add_handler(CommandHandler("skills", self._cmd_skills))
            app.add_handler(CommandHandler("session", self._cmd_session))
            app.add_handler(CommandHandler("confirm", self._cmd_confirm))
            app.add_handler(CallbackQueryHandler(self._on_callback))
            app.add_handler(MessageHandler(filters.VOICE, self._on_voice))
            app.add_handler(MessageHandler(filters.Document.ALL, self._on_document))
            app.add_handler(MessageHandler(
                filters.TEXT & ~filters.COMMAND, self._on_text))
            app.add_handler(MessageHandler(filters.COMMAND,
                                           self._on_unknown_command))

            self.running = True
            _logger.info("telegram.started")
            options = polling_options()
            options["allowed_updates"] = Update.ALL_TYPES
            app.run_polling(**options)
        except Exception as e:                               # noqa: BLE001
            _logger.error("telegram.crashed", error=type(e).__name__)
        finally:
            self.running = False
            self._app = None
            self._loop = None
            if loop is not None and not loop.is_running():
                try:
                    loop.close()
                except Exception:                            # noqa: BLE001
                    pass
            _logger.info("telegram.stopped")

    # ── keamanan: middleware pertama di SEMUA handler ─────────────────────

    def _authorized(self, update) -> bool:
        user = update.effective_user
        actor_id = str(user.id) if user is not None else ""
        if self._gateway_manager is not None:
            allowed = self._gateway_manager.allowed("telegram", actor_id)
        else:
            allowed = user is not None and user.id in _allowed_ids()
        if not allowed:
            uid = user.id if user else "?"
            _logger.warning("telegram.access_denied", user_id=uid)
            return False                     # diam total — jangan balas
        return True

    # ── util kirim lintas-thread ──────────────────────────────────────────

    def _submit(self, coro, timeout: float = 30):
        loop = self._loop
        if loop is None or not loop.is_running():
            raise RuntimeError("telegram loop tidak berjalan")
        return asyncio.run_coroutine_threadsafe(coro, loop) \
            .result(timeout=timeout)

    def send_text(self, chat_id: int, text: str) -> None:
        value = str(text or "")
        if len(value) <= 4000:
            self._submit(self._app.bot.send_message(chat_id, value or " "))
            return
        self.send_document(chat_id, self._markdown_file(value),
                           "Hasil lengkap dikirim sebagai Markdown.")

    def send_document(self, chat_id: int, path: str,
                      caption: str = "") -> None:
        with open(path, "rb") as fh:
            self._submit(self._app.bot.send_document(
                chat_id, fh, caption=caption[:1000]))

    @staticmethod
    def _markdown_file(text: str) -> str:
        from jarvis.agent.paths import generated_dir
        path = generated_dir() / f"telegram_{uuid.uuid4().hex[:12]}.md"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def edit_result(self, chat_id: int, message_id: int,
                    text: str) -> None:
        """Final T2 mengganti ACK yang sama; output panjang menjadi .md."""
        value = str(text or "")
        if len(value) <= 4000:
            self._submit(self._app.bot.edit_message_text(
                value or " ", chat_id=chat_id, message_id=message_id))
            return
        self._submit(self._app.bot.edit_message_text(
            "Selesai. Hasil lengkap dikirim sebagai berkas Markdown.",
            chat_id=chat_id, message_id=message_id))
        self.send_document(chat_id, self._markdown_file(value),
                           "Hasil tugas Jarvis")

    def send_photo(self, chat_id: int, path: str, caption: str = "") -> None:
        with open(path, "rb") as f:
            self._submit(self._app.bot.send_photo(chat_id, f,
                                                  caption=caption[:1000]))

    async def _reply_text(self, message, text: str) -> None:
        value = str(text or "")
        if len(value) <= 4000:
            await message.reply_text(value or " ")
            return
        path = self._markdown_file(value)
        with open(path, "rb") as fh:
            await message.reply_document(
                fh, caption="Hasil lengkap dikirim sebagai Markdown.")

    async def _reply_tool_media(self, message, result) -> None:
        """Deliver generated image files without treating arbitrary paths as media."""
        paths = result.meta.get("paths", []) if result.ok else []
        if not isinstance(paths, list):
            return
        for raw_path in paths[:2]:
            path = Path(str(raw_path))
            if not path.is_file() or path.suffix.lower() not in {
                ".png", ".jpg", ".jpeg", ".webp",
            }:
                continue
            try:
                with path.open("rb") as fh:
                    await message.reply_photo(fh)
            except Exception as exc:                         # noqa: BLE001
                _logger.warning("telegram.tool_media_failed",
                                error=type(exc).__name__)

    async def _register_command_menu(self, app) -> None:
        try:
            from telegram import BotCommand
            await app.bot.set_my_commands(
                [BotCommand(command, description)
                 for command, description in command_menu()]
            )
        except Exception as exc:                             # noqa: BLE001
            _logger.warning("telegram.command_menu_failed",
                            error=type(exc).__name__)

    # ── handlers ──────────────────────────────────────────────────────────

    async def _cmd_start(self, update, context) -> None:
        if not self._authorized(update):
            return
        await update.message.reply_text(
            "JARVIS agent siap. Kirim tugas sebagai teks bebas atau pakai "
            "/help untuk daftar perintah.")

    async def _cmd_help(self, update, context) -> None:
        if not self._authorized(update):
            return
        await self._reply_text(
            update.message,
            "JARVIS Telegram menerima teks bebas untuk riset web, pencarian "
            "video YouTube, dan generate satu gambar. Gunakan /tools untuk "
            "kapabilitas yang aktif; /status /todo /skills /memory <query> "
            "/cron /screen /session /confirm tersedia dari menu /. "
            "Kontrol desktop, terminal, file-write, kredensial, dan aksi akun "
            "tetap memerlukan kontrol/approval lokal demi keamanan.")

    async def _on_unknown_command(self, update, context) -> None:
        if not self._authorized(update):
            return
        await update.message.reply_text(
            "Perintah tidak dikenal. Ketik / untuk menu atau /help untuk bantuan.")

    async def _cmd_tools(self, update, context) -> None:
        if not self._authorized(update):
            return
        from jarvis.agent import registry
        from jarvis.gateway.base import InboundMessage

        actor_id = str(getattr(update.effective_user, "id", ""))
        chat_id = str(getattr(update.effective_chat, "id", ""))
        remote = InboundMessage("tools", "telegram", chat_id, actor_id)
        remote_context = remote.execution_context()
        tools = registry.all_tools()
        names = []
        from jarvis.agent.capabilities import REGISTRY as capabilities
        for name in capabilities.exposed_tool_names(remote_context):
            if name in tools:
                names.append(name)
        status = ("Tool remote aktif:\n• " + "\n• ".join(sorted(names))
                  if names else
                  "Tidak ada tool remote aktif. Periksa provider/API key dan "
                  "toggle grup tool di desktop.")
        await self._reply_text(update.message, status)

    async def _cmd_status(self, update, context) -> None:
        if not self._authorized(update):
            return
        from jarvis.agent import dispatch
        tasks = dispatch.active_tasks()
        lines = [f"Sesi aktif: {len(tasks)}"]
        lines += [f"• {t[:80]}" for t in tasks[:5]]
        try:
            import psutil
            lines.append(f"CPU {psutil.cpu_percent():.0f}% | "
                         f"RAM {psutil.virtual_memory().percent:.0f}%")
        except Exception:                                    # noqa: BLE001
            pass
        await self._reply_text(update.message, "\n".join(lines))

    async def _cmd_stop(self, update, context) -> None:
        if not self._authorized(update):
            return
        if self._gateway_manager is not None:
            await update.message.reply_text(
                "Perintah remote ini harus disetujui dari desktop lokal.")
            return
        from jarvis.agent import dispatch
        n = dispatch.cancel_all()
        await update.message.reply_text(f"{n} tugas dibatalkan.")

    async def _cmd_todo(self, update, context) -> None:
        if not self._authorized(update):
            return
        from jarvis.agent import dispatch
        todos = []
        with dispatch._active_lock:
            for h in dispatch._active.values():
                todos.extend(h.session.todos)
        if not todos:
            await update.message.reply_text("Todo kosong.")
            return
        icons = {"pending": "○", "in_progress": "◐", "completed": "●",
                 "blocked": "✕"}
        await self._reply_text(update.message, "\n".join(
            f"{icons.get(t['status'], '○')} {t['content']}" for t in todos))

    async def _cmd_memory(self, update, context) -> None:
        if not self._authorized(update):
            return
        query = " ".join(context.args or [])
        if not query:
            await update.message.reply_text("Pakai: /memory <kata kunci>")
            return
        actor_id = str(getattr(getattr(update, "effective_user", None), "id", "") or "")
        if not actor_id:
            await update.message.reply_text("Identitas Telegram tidak tersedia.")
            return
        from jarvis.agent.execution_context import ExecutionContext
        from jarvis.agent.memory_access import resolve
        try:
            memory_scope = resolve(ExecutionContext.create(
                source="telegram", actor_id=actor_id,
                session_id=str(getattr(update.effective_chat, "id", "") or ""),
                surface="remote", toolsets={"memory"},
            ))
        except PermissionError:
            await update.message.reply_text("Akses memori ditolak oleh policy.")
            return
        from jarvis.agent import memory_store
        rows = await asyncio.to_thread(
            memory_store.search, query, None, 6,
            scope=memory_scope.scope, owner=memory_scope.owner,
        )
        if not rows:
            await update.message.reply_text("Tidak ada memori relevan.")
            return
        await self._reply_text(update.message, "\n\n".join(
            f"[{r['type']}] {r['content'][:300]}" for r in rows))

    async def _cmd_cron(self, update, context) -> None:
        if not self._authorized(update):
            return
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        from jarvis.agent import cron
        jobs = await asyncio.to_thread(cron.list_jobs, False)
        if not jobs:
            await update.message.reply_text("Belum ada cron job.")
            return
        for j in jobs[:10]:
            state = "ON" if j["enabled"] else "OFF"
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "⏸ Pause" if j["enabled"] else "▶ Resume",
                    callback_data=f"cron:{'pause' if j['enabled'] else 'resume'}:{j['id']}"),
                InlineKeyboardButton("▶▶ Run",
                                     callback_data=f"cron:run:{j['id']}"),
            ]])
            await update.message.reply_text(
                f"{j['name']} [{state}] '{j['schedule']}'\n{j['task'][:120]}",
                reply_markup=kb)

    async def _cmd_screen(self, update, context) -> None:
        if not self._authorized(update):
            return
        def _shot() -> str:
            import mss
            import mss.tools
            from jarvis.agent.paths import generated_dir
            p = generated_dir() / f"tg_screen_{int(time.time())}.png"
            with mss.mss() as sct:
                img = sct.grab(sct.monitors[1])
                mss.tools.to_png(img.rgb, img.size, output=str(p))
            return str(p)
        try:
            path = await asyncio.to_thread(_shot)
            with open(path, "rb") as f:
                await update.message.reply_photo(f)
        except Exception as e:                               # noqa: BLE001
            await update.message.reply_text(
                f"Screenshot gagal ({type(e).__name__}).")

    async def _cmd_skills(self, update, context) -> None:
        if not self._authorized(update):
            return
        from jarvis.agent import skills
        metas = await asyncio.to_thread(skills.list_metadata)
        text = "\n".join(f"• {m['name']}: {m['description'][:80]}"
                         for m in metas) or "Belum ada skill."
        await self._reply_text(update.message, text)

    async def _cmd_session(self, update, context) -> None:
        if not self._authorized(update):
            return
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        chat_id = update.effective_chat.id
        current = self._session_id(chat_id)
        from jarvis.agent import session as session_mod
        rows = await asyncio.to_thread(session_mod.recent_sessions, 5)
        recent = "\n".join(
            f"[{r['id']}] {r.get('adapter')} turns={r.get('turn_count')} — "
            f"{(r.get('task') or '')[:60]}" for r in rows) or "Belum ada sesi."
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Reset session",
                                 callback_data=f"session:reset:{current}")]])
        await update.message.reply_text(
            f"Telegram session ID: {current}\n\nSesi agent terbaru:\n{recent[:3300]}",
            reply_markup=keyboard)

    async def _cmd_confirm(self, update, context) -> None:
        if not self._authorized(update):
            return
        chat_id = update.effective_chat.id
        qid = self._pending_confirm.pop(chat_id, None)
        fut = self._pending.pop(qid, None) if qid else None
        if qid:
            self._pending_chat.pop(qid, None)
        if fut is None or fut.done():
            await update.message.reply_text(
                "Tidak ada aksi yang sedang menunggu konfirmasi.")
            return
        fut.set_result("Lanjut")
        await update.message.reply_text("Konfirmasi diterima: Lanjut.")

    def _session_id(self, chat_id: int) -> str:
        return self._chat_sessions.setdefault(
            chat_id, f"tg-{uuid.uuid4().hex[:10]}")

    def _reset_session(self, chat_id: int) -> str:
        self._chat_sessions[chat_id] = f"tg-{uuid.uuid4().hex[:10]}"
        waiting = self._await_text.pop(chat_id, None)
        if waiting is not None and not waiting.done():
            waiting.set_result(None)
        for qid, pending_chat in list(self._pending_chat.items()):
            if pending_chat != chat_id:
                continue
            future = self._pending.pop(qid, None)
            self._pending_chat.pop(qid, None)
            if future is not None and not future.done():
                future.set_result(None)
        self._pending_confirm.pop(chat_id, None)
        return self._chat_sessions[chat_id]

    async def _on_callback(self, update, context) -> None:
        if not self._authorized(update):
            return
        q = update.callback_query
        data = q.data or ""
        await q.answer()
        if data.startswith("ask:"):
            _, qid, answer = data.split(":", 2)
            fut = self._pending.pop(qid, None)
            chat_id = self._pending_chat.pop(qid, None)
            if chat_id is not None and self._pending_confirm.get(chat_id) == qid:
                self._pending_confirm.pop(chat_id, None)
            if fut is not None and not fut.done():
                fut.set_result(answer)
            await q.edit_message_text(f"{q.message.text}\n→ {answer}")
            return
        if data.startswith("session:reset:"):
            _, _, expected = data.split(":", 2)
            chat_id = update.effective_chat.id
            current = self._session_id(chat_id)
            if expected != current:
                await q.edit_message_text(
                    f"Session sudah berubah. ID aktif: {current}")
                return
            new_id = self._reset_session(chat_id)
            await q.edit_message_text(
                f"Telegram session di-reset. ID baru: {new_id}")
            return
        if data.startswith("cron:"):
            from jarvis.agent import cron
            _, action, jid = data.split(":", 2)
            if action == "pause":
                cron.set_enabled(jid, False)
            elif action == "resume":
                cron.set_enabled(jid, True)
            elif action == "run":
                cron.run_job_now(jid)
            await q.edit_message_text(f"{q.message.text}\n→ {action} ok")

    async def _on_document(self, update, context) -> None:
        """Fase 15S: terima upload setup credential, stage, minta approval desktop."""
        if not self._authorized(update):
            return
        document = getattr(update.message, "document", None)
        if document is None:
            return
        filename = str(getattr(document, "file_name", "") or "")
        size = int(getattr(document, "file_size", 0) or 0)
        from jarvis.agent.remote_setup import attachment_allowed
        allowed, reason = attachment_allowed(filename, size)
        if not allowed:
            await update.message.reply_text(
                f"Berkas setup ditolak: {reason}. Kirim OAuth client JSON (.json).")
            return
        try:
            f = await document.get_file()
            payload = bytes(await f.download_as_bytearray())
        except Exception as exc:                              # noqa: BLE001
            await update.message.reply_text(
                f"Gagal menerima berkas ({type(exc).__name__}).")
            return
        actor_id = str(getattr(getattr(update, "effective_user", None), "id", "") or "")
        from jarvis.agent import remote_setup_ingress
        status = remote_setup_ingress.receive_setup_upload(
            self._setup_queue, provider="google_oauth_client",
            requester=f"telegram:{actor_id}", paired=True,
            filename=filename, payload=payload)
        del payload
        if not status.get("accepted"):
            await update.message.reply_text(
                f"Setup ditolak: {status.get('reason', 'tidak valid')}.")
            return
        self._present_setup_on_desktop(status["request_id"])
        await update.message.reply_text(
            "Berkas setup diterima dan menunggu persetujuan di desktop JARVIS. "
            f"Sidik berkas …{status.get('hash_suffix', '')}. "
            "Isi rahasia tidak ditampilkan di sini.")

    def _present_setup_on_desktop(self, request_id: str) -> None:
        """Publish request-id to the desktop approval sheet via the local BUS."""
        try:
            from jarvis.core.bus import BUS
            # BUS carries only the opaque request id; the window owns the
            # runtime queue and never accepts a caller-supplied object.
            BUS.publish("remote_setup.pending", request_id=str(request_id))
        except Exception as exc:                              # noqa: BLE001
            _logger.warning("remote_setup.present_failed", error=type(exc).__name__)

    async def _on_voice(self, update, context) -> None:
        if not self._authorized(update):
            return
        voice = update.message.voice
        max_bytes = int(config.get(
            "integrations.telegram.voice_max_bytes", 20 * 1024 * 1024))
        if int(getattr(voice, "file_size", 0) or 0) > max_bytes:
            await update.message.reply_text(
                f"Voice note terlalu besar (maksimal {max_bytes // 1024 // 1024} MB).")
            return
        path: Path | None = None
        try:
            f = await voice.get_file()
            from jarvis.agent.paths import data_dir
            path = data_dir() / f"tg_voice_{uuid.uuid4().hex[:12]}.ogg"
            await f.download_to_drive(str(path))
            from jarvis.agent.adapters.jarvis_voice import transcribe
            text = await asyncio.to_thread(transcribe, path)
        except Exception as exc:                             # noqa: BLE001
            await update.message.reply_text(
                f"Voice note gagal diproses ({type(exc).__name__}). "
                "Kirim teks atau periksa dependency STT Jarvis.")
            return
        finally:
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        if not text:
            await update.message.reply_text(
                "STT Jarvis tidak mendeteksi ucapan — kirim teks saja.")
            return
        await update.message.reply_text(f"🎙 \"{text}\"")
        if self._gateway_manager is not None:
            self._receive_gateway_text(update, text)
            return
        await self._handle_task(update, text)

    async def _on_text(self, update, context) -> None:
        if self._gateway_manager is not None:
            chat_id = update.effective_chat.id
            waiting = self._await_text.get(chat_id)
            if waiting is not None and not waiting.done():
                if self._authorized(update):
                    self._await_text.pop(chat_id, None)
                    waiting.set_result((update.message.text or "").strip())
                return
            self._receive_gateway_text(update, update.message.text or "")
            return
        if not self._authorized(update):
            return
        chat_id = update.effective_chat.id
        message_id = getattr(update.message, "message_id", "")
        # Telegram always supplies message_id. Compatibility fixtures/legacy
        # callers without one still receive a process-local idempotency key.
        if not message_id:
            message_id = f"legacy-{id(update.message)}"
        if not self._gateway_registry.accept_inbound("telegram", message_id, chat_id):
            return
        text = (update.message.text or "").strip()
        # 15B: exact allowlisted remote request becomes metadata-only local approval.
        from jarvis.agent import remote_proposal_ingress, remote_proposals
        proposal = remote_proposal_ingress.stage_text(
            remote_proposals.get_queue(), actor_id=f"telegram:{chat_id}",
            session_id=self._session_id(chat_id), text=text, paired=True)
        if proposal.get("accepted"):
            from jarvis.core.bus import BUS
            BUS.publish("remote_proposal.pending", proposal_id=proposal["proposal_id"],
                        actor_id=f"telegram:{chat_id}", session_id=self._session_id(chat_id))
            await self._reply_text(update.message, "Permintaan menunggu persetujuan desktop lokal.")
            return
        # jawaban untuk pertanyaan clarify yang menunggu?
        fut = self._await_text.pop(chat_id, None)
        if fut is not None and not fut.done():
            fut.set_result(text)
            return
        await self._handle_task(update, text)

    async def _handle_task(self, update, text: str, execution_context=None) -> None:
        chat_id = update.effective_chat.id
        from jarvis.agent import conversation_context
        conversation_id = self._session_id(chat_id)
        text = conversation_context.STORE.augment(conversation_id, text)
        route = classify_execution(text, {"source": "telegram"})
        _logger.info(
            "router.decision",
            source="telegram",
            tier=int(route.tier),
            lane=route.lane,
            reason=route.reason,
        )

        if route.tier in (ExecutionTier.REFLEX, ExecutionTier.SINGLE):
            # T0/T1 tetap satu aksi/tool dan tidak pernah masuk agent loop.
            from jarvis.agent.adapters import telegram_light
            result = await telegram_light.execute(
                text, route, context=execution_context)
            answer = result.for_llm(max_chars=24_000) if result.ok else (
                result.error or "Perintah ringan gagal tanpa detail.")
            if not result.ok:
                answer = f"⚠️ {answer}"
            await self._reply_text(update.message, answer)
            await self._reply_tool_media(update.message, result)
            if result.ok:
                from jarvis.agent import delivery_lifecycle
                delivery_lifecycle.success(
                    answer, text, source="telegram", conversation_id=conversation_id,
                )
            return

        from jarvis.agent import dispatch
        from jarvis.agent import delivery_lifecycle
        from jarvis.agent.interaction import unavailable_reason
        adapter = TelegramAdapter(self, chat_id)
        loop = asyncio.get_running_loop()
        task_scope = {"id": ""}

        def on_task(metadata) -> None:
            # Registry binding is the only point where the real task ID exists.
            # The safe title is remembered under that ID — never before it.
            task_scope["id"] = str(getattr(metadata, "id", "") or "")
            title = str(getattr(metadata, "title", "") or text)
            conversation_context.STORE.begin_task(
                conversation_id, task_id=task_scope["id"], task=title
            )

        def on_ack(ack: str):
            # dispatch dipanggil via to_thread, sehingga ACK dapat benar-benar
            # dikirim dan diikat sebagai progress sebelum worker agent mulai.
            delivery_lifecycle.acknowledged("telegram", ack)
            future = asyncio.run_coroutine_threadsafe(
                update.message.reply_text(ack), loop)
            progress = future.result(timeout=10)
            adapter.bind_progress_message(progress.message_id)
            return True

        def on_done(result: str) -> bool:
            try:
                delivery = delivery_lifecycle.success(
                    result, text, source="telegram",
                )
                conversation_context.STORE.remember_success(
                    conversation_id, task_id=task_scope["id"], task=text,
                    delivery=delivery,
                )
                return adapter.complete_progress(delivery.display_text)
            except Exception:                                # noqa: BLE001
                return False

        def on_error(err: str) -> bool:
            try:
                delivery = delivery_lifecycle.failure(err, text, source="telegram")
                conversation_context.STORE.fail_task(
                    conversation_id, task_id=task_scope["id"]
                )
                return adapter.complete_progress(f"⚠️ {delivery.display_text}")
            except Exception:                                # noqa: BLE001
                return False

        started = await asyncio.to_thread(
            dispatch.dispatch_async,
            text,
            adapter=adapter,
            on_ack=on_ack,
            on_done=on_done,
            on_error=on_error,
            on_task=on_task,
            context=execution_context,
            source="telegram",
        )
        if not started:
            delivery = delivery_lifecycle.failure(
                unavailable_reason(text), text, source="telegram"
            )
            await update.message.reply_text(f"⚠️ {delivery.display_text}")

    # ── dipakai TelegramAdapter (dari worker thread) ──────────────────────

    def ask_via_keyboard(self, chat_id: int, question: str,
                         options: list[str] | None,
                         timeout: float) -> str | None:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        qid = uuid.uuid4().hex[:8]
        fut: Future = Future()
        if options:
            self._pending[qid] = fut
            self._pending_chat[qid] = chat_id
            normalized = {str(option).strip().lower() for option in options}
            if "lanjut" in normalized and "batal" in normalized:
                previous = self._pending_confirm.get(chat_id)
                if previous and previous != qid:
                    old = self._pending.pop(previous, None)
                    self._pending_chat.pop(previous, None)
                    if old is not None and not old.done():
                        old.set_result(None)
                self._pending_confirm[chat_id] = qid
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    (("✅ " if str(o).strip().lower() == "lanjut" else
                      "❌ " if str(o).strip().lower() == "batal" else "")
                     + str(o))[:32],
                                     callback_data=f"ask:{qid}:{o[:24]}")
                for o in options[:3]]])
            self._submit(self._app.bot.send_message(
                chat_id, f"❓ {question[:3500]}", reply_markup=kb))
        else:
            self._await_text[chat_id] = fut
            self._submit(self._app.bot.send_message(
                chat_id, f"❓ {question[:3500]}\n(balas pesan ini)"))
        try:
            return fut.result(timeout=timeout)
        except Exception:                                    # noqa: BLE001
            self._pending.pop(qid, None)
            self._pending_chat.pop(qid, None)
            if self._pending_confirm.get(chat_id) == qid:
                self._pending_confirm.pop(chat_id, None)
            self._await_text.pop(chat_id, None)
            return None


class TelegramAdapter(Adapter):
    """Adapter satu sesi agent yang terikat ke satu chat."""

    name = "telegram"
    interactive = True

    def __init__(self, service: TelegramService, chat_id: int):
        self._svc = service
        self.chat_id = chat_id
        self._progress_msg_id: int | None = None
        self._last_edit = 0.0

    def bind_progress_message(self, message_id: int) -> None:
        self._progress_msg_id = message_id

    def finish_progress(self) -> None:
        self._progress_msg_id = None

    def complete_progress(self, content: str) -> bool:
        """Edit ACK menjadi hasil final; fallback jujur bila edit gagal.

        Returns an honest delivery receipt: True only when the final text was
        accepted by the transport (edit or fallback send). False keeps the
        registry the completion-speech owner, so a lost Telegram delivery is
        never mistaken for an audible/visible success.
        """
        message_id = self._progress_msg_id
        self._progress_msg_id = None
        try:
            if message_id is None:
                self._svc.send_text(self.chat_id, content)
            else:
                self._svc.edit_result(self.chat_id, message_id, content)
            return True
        except Exception:                                    # noqa: BLE001
            try:
                self._svc.send_text(self.chat_id, content)
                return True
            except Exception:                                # noqa: BLE001
                return False

    async def send(self, content: str, **kwargs) -> None:
        # jawaban akhir dikirim oleh callback on_done (hindari dobel);
        # send() dipakai untuk pesan perantara penting saja
        pass

    async def progress(self, text: str) -> None:
        # edit pesan yang sama, throttle ~3 s — jangan spam chat (§5.4)
        if self._progress_msg_id is None:
            return
        now = time.monotonic()
        if now - self._last_edit < 3.0:
            return
        self._last_edit = now
        try:
            await asyncio.to_thread(
                self._svc._submit,
                self._svc._app.bot.edit_message_text(
                    f"⚙️ {text[:300]}", chat_id=self.chat_id,
                    message_id=self._progress_msg_id))
        except Exception:                                    # noqa: BLE001
            pass

    async def ask(self, question: str,
                  options: list[str] | None = None) -> str | None:
        timeout = float(config.get("agent.confirm_timeout_s", 300))
        return await asyncio.to_thread(
            self._svc.ask_via_keyboard, self.chat_id, question,
            options, timeout)

    async def send_image(self, path: str, caption: str = "") -> None:
        try:
            await asyncio.to_thread(self._svc.send_photo, self.chat_id,
                                    path, caption)
        except Exception:                                    # noqa: BLE001
            pass


def send_from_anywhere(text: str) -> bool:
    """Kirim notifikasi (mis. hasil cron) ke chat pertama di whitelist."""
    svc = TelegramService.get()
    if not svc.running:
        return False
    ids = _allowed_ids()
    chat = ids[0] if ids else 0
    if not chat:
        return False
    try:
        svc.send_text(chat, text)
        return True
    except Exception as e:                                   # noqa: BLE001
        _logger.warning("telegram.notify_failed", error=type(e).__name__)
        return False
