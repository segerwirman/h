"""Google Drive read/search tools (§10.4), tanpa menulis file lokal."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.integrations import google_api, google_auth

READ_SCOPE = google_auth.SCOPES["drive"]["read"]
_EXPORT_MIME = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
_TEXT_MIME = {
    "text/plain", "text/csv", "text/markdown", "text/html",
    "application/json", "application/xml", "text/xml",
}


def available() -> bool:
    return google_auth.has_read_scope("drive")


def _service():
    return google_api.service("drive", "v3", [READ_SCOPE])


def _escape_query(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


class _SearchParams(BaseModel):
    query: str = Field(min_length=1, description="Nama atau teks file")
    limit: int = Field(10, ge=1, le=100)


class GdriveSearch(Tool):
    name = "gdrive_search"
    description = "Cari file Google Drive berdasarkan nama atau isi teks."
    params_schema = _SearchParams
    read_only = True
    timeout_s = 30

    async def run(self, query: str, limit: int = 10, **_) -> ToolResult:
        escaped = _escape_query(query)

        def work():
            return _service().files().list(
                q=(f"trashed = false and (name contains '{escaped}' or "
                   f"fullText contains '{escaped}')"),
                pageSize=max(1, min(int(limit), 100)),
                orderBy="modifiedTime desc",
                fields=("nextPageToken,files(id,name,mimeType,modifiedTime,"
                        "webViewLink,size)"),
            ).execute()
        try:
            response = await asyncio.to_thread(work)
        except Exception as exc:
            return ToolResult.fail(google_api.safe_error(exc))
        rows = []
        for item in response.get("files") or []:
            rows.append(
                f"{item.get('name') or '(tanpa nama)'} "
                f"[{item.get('id') or '-'}] — {item.get('mimeType') or '-'}")
        text = "; ".join(rows) if rows else "Tidak ada file Google Drive yang cocok."
        return ToolResult.success(text, display=text)


class _ReadParams(BaseModel):
    file_id: str = Field(min_length=1)
    max_chars: int = Field(12000, ge=500, le=50000)


def _read_file(file_id: str, max_chars: int) -> tuple[dict, str]:
    svc = _service()
    meta = svc.files().get(
        fileId=file_id,
        fields="id,name,mimeType,modifiedTime,webViewLink,size").execute()
    mime = str(meta.get("mimeType") or "")
    if mime in _EXPORT_MIME:
        raw = svc.files().export_media(
            fileId=file_id, mimeType=_EXPORT_MIME[mime]).execute()
    elif mime in _TEXT_MIME or mime.startswith("text/"):
        raw = svc.files().get_media(fileId=file_id).execute()
    else:
        raise ValueError(
            f"format {mime or 'tidak dikenal'} tidak dapat diekspor sebagai teks")
    if isinstance(raw, str):
        text = raw
    else:
        text = bytes(raw or b"").decode("utf-8", errors="replace")
    return meta, text[:max_chars]


class GdriveRead(Tool):
    name = "gdrive_read"
    description = "Ekspor dan baca teks file Google Drive berdasarkan file_id."
    params_schema = _ReadParams
    read_only = True
    timeout_s = 45

    async def run(self, file_id: str, max_chars: int = 12000,
                  **_) -> ToolResult:
        try:
            meta, body = await asyncio.to_thread(
                _read_file, file_id, max_chars)
        except Exception as exc:
            return ToolResult.fail(google_api.safe_error(exc))
        text = f"{meta.get('name') or 'File Drive'}:\n{body.strip()}"
        return ToolResult.success(text, display=text[:1200],
                                  mime_type=meta.get("mimeType", ""))
