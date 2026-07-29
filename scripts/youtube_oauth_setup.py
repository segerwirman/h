"""YouTube Data API v3 quick test commands.

Prereqs (see docs/YOUTUBE_API_SETUP.md):
  pip install google-auth-oauthlib
  A Google Cloud "OAuth client ID" of type *Desktop app*, downloaded as
  client_secret.json.

Usage (run from the project root):
  python -m scripts.youtube_oauth_setup test-video   <VIDEO_ID>
  python -m scripts.youtube_oauth_setup test-live     <VIDEO_ID>
  python -m scripts.youtube_oauth_setup reply-video   <COMMENT_ID> "your reply"

OAuth tidak lagi dibuat oleh skrip terpisah. Hubungkan satu Google OAuth lewat
Settings > Google Cloud, aktifkan YouTube dan opsi write bila perlu.
"""
from __future__ import annotations

import sys

from jarvis.integrations.comments import youtube_api


def _need(args, n) -> bool:
    if len(args) < n:
        print(__doc__)
        return True
    return False


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "authorize":
        print("Perintah authorize terpisah sudah dihentikan. Gunakan "
              "Settings > Google Cloud agar Calendar, YouTube, Gmail, dan "
              "Drive berbagi satu OAuth terenkripsi.")
        return 1
    if cmd == "test-video":
        if _need(argv, 2):
            return 1
        for c in youtube_api.read_video_comments(argv[1], max_results=10):
            print(f"- [{c['comment_id']}] {c['author']}: {c['text'][:100]}")
        return 0
    if cmd == "test-live":
        if _need(argv, 2):
            return 1
        chat_id = youtube_api.resolve_live_chat_id(argv[1])
        if not chat_id:
            print("No active live chat for that video (API key set? video live?).")
            return 1
        print("liveChatId:", chat_id)
        for m in youtube_api.read_live_chat(chat_id).get("items", []):
            print(f"- {m['author']}: {m['text'][:100]}")
        return 0
    if cmd == "reply-video":
        if _need(argv, 3):
            return 1
        print(youtube_api.reply_video_comment(argv[1], argv[2]))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
