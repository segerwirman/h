"""Thin YouTube Data API v3 helpers — read/reply for live chat AND video
comments, over plain ``requests`` (no extra SDK).

- Reading video comments (``commentThreads.list``) and resolving a live
  ``liveChatId`` (``videos.list``) need only an API key.
- Reading live-chat messages and posting ANY reply need an OAuth access token
  (``youtube.force-ssl`` scope) — see ``youtube_oauth``.

Each function returns a plain dict/list and raises nothing fatal: on error it
returns an ``{"error": ...}`` dict (or empty list) so callers stay robust.
"""
from __future__ import annotations

from jarvis.integrations.comments import youtube_oauth

_API = "https://www.googleapis.com/youtube/v3"


def _req():
    import requests
    return requests


def resolve_live_chat_id(video_id: str) -> str | None:
    """Active live-chat id for a live/premiere video id (needs API key)."""
    key = youtube_oauth.api_key()
    if not key or not video_id:
        return None
    try:
        r = _req().get(f"{_API}/videos", params={
            "part": "liveStreamingDetails", "id": video_id, "key": key}, timeout=10)
        r.raise_for_status()
        items = r.json().get("items", [])
        if items:
            return items[0].get("liveStreamingDetails", {}).get("activeLiveChatId")
    except Exception:
        return None
    return None


def read_live_chat(live_chat_id: str, page_token: str = "") -> dict:
    """Live-chat messages page. Needs OAuth. Returns
    {items:[{author,text,id}], next_page_token, poll_ms}."""
    token = youtube_oauth.access_token()
    if not token:
        return {"error": "not authorized (run scripts/youtube_oauth_setup.py)", "items": []}
    params = {"liveChatId": live_chat_id, "part": "snippet,authorDetails",
              "access_token": token}
    if page_token:
        params["pageToken"] = page_token
    try:
        r = _req().get(f"{_API}/liveChat/messages", params=params, timeout=10)
        r.raise_for_status()
        d = r.json()
        items = [{"id": it.get("id"),
                  "author": it.get("authorDetails", {}).get("displayName", ""),
                  "text": it.get("snippet", {}).get("displayMessage", "")}
                 for it in d.get("items", [])]
        return {"items": items, "next_page_token": d.get("nextPageToken", ""),
                "poll_ms": d.get("pollingIntervalMillis", 5000)}
    except Exception as e:
        return {"error": str(e)[:200], "items": []}


def reply_live_chat(live_chat_id: str, text: str) -> dict:
    token = youtube_oauth.access_token()
    if not token:
        return {"ok": False, "error": "not authorized"}
    try:
        r = _req().post(f"{_API}/liveChat/messages",
                        params={"part": "snippet", "access_token": token},
                        json={"snippet": {"liveChatId": live_chat_id,
                                          "type": "textMessageEvent",
                                          "textMessageDetails": {"messageText": text}}},
                        timeout=10)
        r.raise_for_status()
        return {"ok": True, "id": r.json().get("id", "")}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def read_video_comments(video_id: str, max_results: int = 20) -> list[dict]:
    """Top-level comment threads on a video (needs only API key)."""
    key = youtube_oauth.api_key()
    if not key or not video_id:
        return []
    try:
        r = _req().get(f"{_API}/commentThreads", params={
            "part": "snippet", "videoId": video_id, "order": "time",
            "maxResults": max(1, min(100, max_results)), "key": key,
            "textFormat": "plainText"}, timeout=10)
        r.raise_for_status()
        out = []
        for it in r.json().get("items", []):
            top = it.get("snippet", {}).get("topLevelComment", {})
            s = top.get("snippet", {})
            out.append({"comment_id": top.get("id", ""),
                        "author": s.get("authorDisplayName", ""),
                        "text": s.get("textDisplay", ""),
                        "likes": s.get("likeCount", 0)})
        return out
    except Exception:
        return []


def reply_video_comment(parent_comment_id: str, text: str) -> dict:
    """Reply to a top-level comment (needs OAuth)."""
    token = youtube_oauth.access_token()
    if not token:
        return {"ok": False, "error": "not authorized"}
    try:
        r = _req().post(f"{_API}/comments",
                        params={"part": "snippet", "access_token": token},
                        json={"snippet": {"parentId": parent_comment_id,
                                          "textOriginal": text}},
                        timeout=10)
        r.raise_for_status()
        return {"ok": True, "id": r.json().get("id", "")}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
