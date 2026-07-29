"""Gmail tools (§10.4) dengan gate read/send per scope."""
from __future__ import annotations

import asyncio
import base64
from email.header import decode_header, make_header
from email.message import EmailMessage

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.integrations import google_api, google_auth

READ_SCOPE = google_auth.SCOPES["gmail"]["read"]
SEND_SCOPE = google_auth.SCOPES["gmail"]["write"]
MODIFY_SCOPE = google_auth.SCOPES["gmail"]["modify"]


def available() -> bool:
    return (google_auth.has_read_scope("gmail")
            or google_auth.has_write_scope("gmail"))


def _read_scope() -> str:
    granted = google_auth.token_scopes()
    return MODIFY_SCOPE if MODIFY_SCOPE in granted else READ_SCOPE


def _service(scope: str | None = None):
    return google_api.service("gmail", "v1", [scope or _read_scope()])


def _headers(payload: dict) -> dict[str, str]:
    out = {}
    for item in payload.get("headers") or []:
        name = str(item.get("name") or "").lower()
        value = str(item.get("value") or "")
        try:
            value = str(make_header(decode_header(value)))
        except Exception:
            pass
        if name:
            out[name] = value
    return out


def _message_line(message: dict) -> str:
    hdr = _headers(message.get("payload") or {})
    return (f"{hdr.get('subject') or '(tanpa subjek)'} — dari "
            f"{hdr.get('from') or 'pengirim tidak dikenal'}")


def _decode_data(value: str) -> str:
    if not value:
        return ""
    try:
        value += "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _plain_body(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain":
        return _decode_data((payload.get("body") or {}).get("data", ""))
    for part in payload.get("parts") or []:
        text = _plain_body(part)
        if text:
            return text
    return ""


class _ListParams(BaseModel):
    query: str = Field("is:unread", description="Query pencarian Gmail")
    limit: int = Field(10, ge=1, le=50)


def _list_messages(query: str, limit: int) -> list[dict]:
    svc = _service()
    result = svc.users().messages().list(
        userId="me", q=query,
        maxResults=max(1, min(int(limit), 50))).execute()
    messages = []
    for ref in result.get("messages") or []:
        ident = ref.get("id")
        if not ident:
            continue
        messages.append(svc.users().messages().get(
            userId="me", id=ident, format="metadata",
            metadataHeaders=["Subject", "From", "Date"]).execute())
    return messages


class GmailList(Tool):
    name = "gmail_list"
    description = "Bacakan email Gmail, default email belum dibaca."
    params_schema = _ListParams
    read_only = True
    timeout_s = 45

    def is_available(self) -> bool:
        return google_auth.has_read_scope("gmail")

    async def run(self, query: str = "is:unread", limit: int = 10,
                  **_) -> ToolResult:
        try:
            messages = await asyncio.to_thread(
                _list_messages, query or "is:unread", limit)
        except Exception as exc:
            return ToolResult.fail(google_api.safe_error(exc))
        rows = [_message_line(item) for item in messages]
        if not rows:
            text = "Tidak ada email Gmail yang cocok."
        else:
            text = f"Ada {len(rows)} email: " + "; ".join(rows)
        return ToolResult.success(text, display=text,
                                  message_ids=[m.get("id") for m in messages])


class _ReadParams(BaseModel):
    message_id: str = Field(min_length=1)


class GmailRead(Tool):
    name = "gmail_read"
    description = "Baca satu email Gmail berdasarkan message_id."
    params_schema = _ReadParams
    read_only = True
    timeout_s = 30

    def is_available(self) -> bool:
        return google_auth.has_read_scope("gmail")

    async def run(self, message_id: str, **_) -> ToolResult:
        def work():
            return _service().users().messages().get(
                userId="me", id=message_id, format="full").execute()
        try:
            message = await asyncio.to_thread(work)
        except Exception as exc:
            return ToolResult.fail(google_api.safe_error(exc))
        payload = message.get("payload") or {}
        hdr = _headers(payload)
        body = _plain_body(payload).strip() or str(message.get("snippet") or "")
        text = (f"Subjek: {hdr.get('subject') or '(tanpa subjek)'}. "
                f"Dari: {hdr.get('from') or 'tidak diketahui'}. "
                f"Isi: {body[:6000]}")
        return ToolResult.success(text, display=text[:1200])


class _SendParams(BaseModel):
    to: str = Field(min_length=3, description="Alamat email tujuan")
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    cc: str = ""


class GmailSend(Tool):
    name = "gmail_send"
    description = "Kirim email Gmail; membutuhkan gmail.send dan konfirmasi."
    params_schema = _SendParams
    requires_confirmation = True
    timeout_s = 30

    def is_available(self) -> bool:
        return google_auth.has_write_scope("gmail")

    async def run(self, to: str, subject: str, body: str, cc: str = "",
                  **_) -> ToolResult:
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        if cc:
            message["Cc"] = cc
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

        def work():
            return _service(SEND_SCOPE).users().messages().send(
                userId="me", body={"raw": raw}).execute()
        try:
            sent = await asyncio.to_thread(work)
        except Exception as exc:
            return ToolResult.fail(google_api.safe_error(exc))
        text = f"Email '{subject}' berhasil dikirim ke {to}."
        return ToolResult.success(text, display=text,
                                  message_id=sent.get("id", ""))
