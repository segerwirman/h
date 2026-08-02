"""Fase 16B: gmail_safe — privacy-tiered unread summary, read-only, no body input.

Distinct from gmail.py (desktop full read/send). This tool fetches only unread
metadata via the Gmail read scope and returns a masked, redacted summary safe
for remote/voice delivery. It never sends, never reads a chosen message body,
and never exposes attachment metadata.
"""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.integrations import gmail_summary, google_api, google_auth


def available() -> bool:
    """Module gate: only discover when a Gmail read scope is granted."""
    return bool(google_auth.has_read_scope("gmail"))


def _fetch_unread_metadata(limit: int) -> list[dict]:
    """Fetch unread message metadata headers only (Subject/From/Date)."""
    read_scope = (google_auth.SCOPES["gmail"]["modify"]
                  if google_auth.SCOPES["gmail"]["modify"] in google_auth.token_scopes()
                  else google_auth.SCOPES["gmail"]["read"])
    svc = google_api.service("gmail", "v1", [read_scope])
    listing = svc.users().messages().list(
        userId="me", q="is:unread", maxResults=max(1, min(int(limit), 25))).execute()
    out: list[dict] = []
    for ref in listing.get("messages") or []:
        ident = ref.get("id")
        if not ident:
            continue
        message = svc.users().messages().get(
            userId="me", id=ident, format="metadata",
            metadataHeaders=["Subject", "From", "Date"]).execute()
        headers = {str(h.get("name", "")).lower(): str(h.get("value", ""))
                   for h in (message.get("payload") or {}).get("headers") or []}
        out.append({
            "from": headers.get("from", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
        })
    return out


class _NoParams(BaseModel):
    limit: int = Field(10, ge=1, le=25, description="Jumlah maksimum email diringkas")


class GmailSafeSummary(Tool):
    name = "gmail_safe_summary"
    description = (
        "Ringkasan email Gmail belum dibaca yang aman-privasi: pengirim disamarkan, "
        "email sensitif (OTP/reset password/pembayaran) disensor. Tidak mengirim, "
        "tidak membuka isi email, tidak mengekspos lampiran."
    )
    params_schema = _NoParams
    read_only = True
    timeout_s = 45

    def is_available(self) -> bool:
        return bool(google_auth.has_read_scope("gmail"))

    async def run(self, limit: int = 10, **_) -> ToolResult:
        try:
            messages = await asyncio.to_thread(_fetch_unread_metadata, limit)
        except Exception as exc:
            return ToolResult.fail(google_api.safe_error(exc))
        summary = gmail_summary.summarize_unread(messages, tier="default")
        speech = gmail_summary.briefing_text(summary)
        return ToolResult.success(summary, display=speech)


__all__ = ["GmailSafeSummary"]
