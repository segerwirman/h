# YouTube Data API v3 — setup & usage

YouTube Data reads and authenticated comment/live-chat operations use the
single MK50 Google Cloud connection. A separate YouTube OAuth token is no
longer created or read.

## Configure Google Cloud

1. Create/select a Google Cloud project and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen. Add the Google account that owns the
   channel as a test user while the app is in Testing.
3. Create an OAuth client ID with application type **Desktop app**.
4. Open Jarvis **Settings → Google Cloud**, enter that client ID/client secret,
   and choose **Save OAuth client**. These values are stored through the
   encrypted `secrets_store`, never in `config.yaml`.
5. Enable **YouTube Data — read**. Enable **YouTube — comments/write** only if
   replies or live-chat sending are required. Save, then choose **Connect
   Google** and grant the requested scopes.

Google installed-app authorization requests the combined scope set for all
currently enabled Google APIs. After changing an API or write toggle, connect
again so the token has the new scope set. Restart/reconnect the voice session
so its Gemini Live tool schema is rebuilt.

## Optional public API key

Legacy public comment reads can still use a YouTube Data API key. Store it as
secret name `jarvis/youtube/data_api_v3` through Jarvis's secret migration or
secure secret-store tooling. Do not put the key in `config.yaml`.

## Quick tests

Run from the project root after connecting Google:

```powershell
python -m scripts.youtube_oauth_setup test-video <VIDEO_ID>
python -m scripts.youtube_oauth_setup test-live <LIVE_VIDEO_ID>
python -m scripts.youtube_oauth_setup reply-video <COMMENT_ID> "Thanks!"
```

The former `authorize` command exits with a clear instruction to use Settings;
it cannot create a second token.

To enable the built-in live-comment monitor, keep the default safe draft mode:

```yaml
live_comments:
  default_reply_mode: draft
  platforms:
    youtube:
      enabled: true
      live_chat_id: "<LIVE_CHAT_ID>"
```

All authenticated operations check the actual granted YouTube scope and the
write toggle. Missing credentials, disabled APIs, or insufficient scope return
an explicit unavailable/error result instead of crashing or pretending to post.
