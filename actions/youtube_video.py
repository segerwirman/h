#youtube_video.py — JARVIS MK50 Refreshed Hybrid
"""
REFRESHED YouTube Module — MK50 + Legacy Compatible
- Uses unified secrets_store for YouTube Data API v3 key (jarvis/youtube/data_api_v3)
- Uses MK50 Google OAuth (google_auth) when connected for full features
- Official API first, scraping fallback
- Playback: opens browser/system default (no embedded player needed)
- Summarize: transcript + Gemini
"""
import json
import re
import sys
import time
import subprocess
import shutil
from pathlib import Path
from datetime import datetime
from urllib.parse import quote_plus

try:
    import pyautogui
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import numpy as np
    _NUMPY = True
except ImportError:
    _NUMPY = False

try:
    import requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    _TRANSCRIPT_OK = True
except ImportError:
    _TRANSCRIPT_OK = False

from config import get_os, is_windows, is_mac, is_linux

def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = _get_base_dir()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_YT_VIDEO_FILTER = "EgIQAQ%3D%3D"
_YT_API = "https://www.googleapis.com/youtube/v3"

def _log(msg):
    print(f"[YouTube] {msg}")

# --- Key providers (MK50 unified) ---
def _get_youtube_api_key() -> str:
    """YouTube Data API v3 key from MK50 secrets_store"""
    try:
        sys.path.insert(0, str(BASE_DIR))
        from jarvis.core import secrets_store
        secrets_store.initialize()
        k = secrets_store.get("jarvis/youtube/data_api_v3")
        if k:
            return k.strip()
        # legacy fallback via oauth module
        try:
            from jarvis.integrations.comments import youtube_oauth
            lk = youtube_oauth.api_key()
            if lk:
                return lk.strip()
        except Exception:
            pass
    except Exception as e:
        _log(f"api key lookup failed: {e}")

    # fallback file api_keys.json (legacy)
    try:
        path = BASE_DIR / "config" / "api_keys.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if "youtube_api_key" in data:
                return data["youtube_api_key"]
    except Exception:
        pass
    return ""

def _get_gemini_key() -> str:
    """Gemini key for summarization — from llm module or secrets"""
    try:
        from jarvis.core import llm as core_llm
        k = core_llm.api_key()
        if k:
            return k
    except Exception:
        pass
    try:
        from jarvis.core import secrets_store
        k = secrets_store.get("jarvis/gemini/api_key") or secrets_store.get("GEMINI_API_KEY")
        if k:
            return k
    except Exception:
        pass
    try:
        path = BASE_DIR / "config" / "api_keys.json"
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
            return d.get("gemini_api_key", "")
    except Exception:
        pass
    return ""

def _open_url(url: str) -> None:
    try:
        if is_mac():
            subprocess.Popen(["open", url])
        elif is_linux():
            subprocess.Popen(["xdg-open", url])
        else:
            subprocess.Popen(["cmd", "/c", "start", "", url], shell=False)
    except Exception as e:
        _log(f"open_url failed: {e}")

def _extract_video_id(url: str) -> str | None:
    if not url:
        return None
    m = re.search(r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None

def _is_valid_youtube_url(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", url or ""))

def _ask_for_url(prompt_text: str = "YouTube video URL:") -> str | None:
    try:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk._default_root
        if root is None:
            root = tk.Tk()
            root.withdraw()
        url = simpledialog.askstring("J.A.R.V.I.S", prompt_text, parent=root)
        return url.strip() if url else None
    except Exception as e:
        _log(f"URL dialog failed: {e}")
        return None

# --- Official API helpers (preferred) ---
def _official_search_first(query: str) -> str | None:
    """Returns https://youtube.com/watch?v=... using official API if key present"""
    if not _REQUESTS_OK:
        return None
    key = _get_youtube_api_key()
    if not key or not query:
        return None
    try:
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": 1,
            "key": key,
            "safeSearch": "moderate",
            "videoEmbeddable": "true"
        }
        r = requests.get(f"{_YT_API}/search", params=params, timeout=12, headers=HEADERS)
        if r.status_code != 200:
            _log(f"official search HTTP {r.status_code}: {r.text[:200]}")
            return None
        data = r.json()
        items = data.get("items", [])
        if not items:
            return None
        vid = (items[0].get("id") or {}).get("videoId")
        if vid:
            return f"https://www.youtube.com/watch?v={vid}"
    except Exception as e:
        _log(f"official_search failed: {e}")
    return None

def _official_video_info(video_id: str) -> dict:
    if not _REQUESTS_OK:
        return {}
    key = _get_youtube_api_key()
    if not key or not video_id:
        return {}
    try:
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": video_id,
            "key": key
        }
        r = requests.get(f"{_YT_API}/videos", params=params, headers=HEADERS, timeout=12)
        if r.status_code != 200:
            return {}
        items = r.json().get("items", [])
        if not items:
            return {}
        it = items[0]
        snippet = it.get("snippet", {})
        stats = it.get("statistics", {})
        details = it.get("contentDetails", {})
        # Parse duration ISO8601 PT#M#S -> mm:ss
        def parse_iso(d):
            try:
                m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', d or "")
                if not m:
                    return d or ""
                h, mi, s = m.groups()
                h = int(h or 0); mi = int(mi or 0); s = int(s or 0)
                if h:
                    return f"{h}:{mi:02d}:{s:02d}"
                return f"{mi}:{s:02d}"
            except Exception:
                return d or ""
        info = {}
        if snippet.get("title"):
            info["title"] = snippet["title"]
        if snippet.get("channelTitle"):
            info["channel"] = snippet["channelTitle"]
        if stats.get("viewCount"):
            info["views"] = f"{int(stats['viewCount']):,}"
        if stats.get("likeCount"):
            info["likes"] = f"{int(stats['likeCount']):,} likes"
        if details.get("duration"):
            info["duration"] = parse_iso(details["duration"])
        if snippet.get("publishedAt"):
            info["published"] = snippet["publishedAt"][:10]
        return info
    except Exception as e:
        _log(f"official info failed: {e}")
        return {}

def _official_trending(region: str = "ID", max_results: int = 8) -> list[dict]:
    if not _REQUESTS_OK:
        return []
    key = _get_youtube_api_key()
    if not key:
        return []
    try:
        params = {
            "part": "snippet",
            "chart": "mostPopular",
            "regionCode": region.upper(),
            "maxResults": max_results,
            "key": key
        }
        r = requests.get(f"{_YT_API}/videos", params=params, headers=HEADERS, timeout=12)
        if r.status_code != 200:
            _log(f"trending API HTTP {r.status_code}")
            return []
        results = []
        for i, item in enumerate(r.json().get("items", [])):
            snippet = item.get("snippet", {})
            results.append({
                "rank": i+1,
                "title": snippet.get("title", "Untitled"),
                "channel": snippet.get("channelTitle", "Unknown")
            })
        return results
    except Exception as e:
        _log(f"official trending failed: {e}")
        return []

# --- Scraping fallback ---
def _scrape_first_video_url(query: str) -> str | None:
    if not _REQUESTS_OK:
        return None
    search_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp={_YT_VIDEO_FILTER}"
    try:
        r = requests.get(search_url, headers=HEADERS, timeout=10)
        html = r.text
        video_ids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html)
        seen = set()
        for vid in video_ids:
            if vid in seen:
                continue
            seen.add(vid)
            if f'/shorts/{vid}' in html:
                continue
            return f"https://www.youtube.com/watch?v={vid}"
    except Exception as e:
        _log(f"scrape_first failed: {e}")
    return None

def _scrape_video_info(video_id: str) -> dict:
    if not _REQUESTS_OK:
        return {}
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        html = r.text
        info = {}
        for key, pattern in [
            ("title", r'"title":\{"runs":\[\{"text":"([^"]+)"'),
            ("channel", r'"ownerChannelName":"([^"]+)"'),
            ("views", r'"viewCount":"(\d+)"'),
            ("duration", r'"lengthSeconds":"(\d+)"'),
            ("likes", r'"label":"([0-9,]+ likes)"'),
        ]:
            m = re.search(pattern, html)
            if m:
                raw = m.group(1)
                if key == "views":
                    try:
                        info[key] = f"{int(raw):,}"
                    except:
                        info[key] = raw
                elif key == "duration":
                    try:
                        secs = int(raw)
                        info[key] = f"{secs // 60}:{secs % 60:02d}"
                    except:
                        info[key] = raw
                else:
                    info[key] = raw
        return info
    except Exception as e:
        _log(f"scrape info failed: {e}")
        return {}

def _scrape_trending(region: str = "TR", max_results: int = 8) -> list[dict]:
    if not _REQUESTS_OK:
        return []
    url = f"https://www.youtube.com/feed/trending?gl={region.upper()}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        html = r.text
        titles = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"\}\]', html)
        channels = re.findall(r'"ownerText":\{"runs":\[\{"text":"([^"]+)"', html)
        results, seen = [], set()
        for i, title in enumerate(titles):
            if title in seen or len(title) < 5:
                continue
            seen.add(title)
            channel = channels[i] if i < len(channels) else "Unknown"
            results.append({"rank": len(results)+1, "title": title, "channel": channel})
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        _log(f"trending scrape failed: {e}")
        return []

# --- Transcript + Summary ---
def _get_transcript(video_id: str) -> str | None:
    if not _TRANSCRIPT_OK:
        return None
    try:
        # Check new API version compatibility
        try:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            transcript = None
            lang_priority = ["en", "id", "en-US", "tr", "de", "fr", "es", "it", "pt", "ru", "ja", "ko", "ar", "zh"]
            try:
                transcript = transcript_list.find_manually_created_transcript(lang_priority)
            except Exception:
                pass
            if transcript is None:
                try:
                    transcript = transcript_list.find_generated_transcript(lang_priority)
                except Exception:
                    for t in transcript_list:
                        transcript = t
                        break
            if transcript is None:
                return None
            fetched = transcript.fetch()
            # handle both dict and object return types
            texts = []
            for entry in fetched:
                if isinstance(entry, dict):
                    texts.append(entry.get("text",""))
                else:
                    texts.append(getattr(entry, "text", str(entry)))
            return " ".join(texts)
        except AttributeError:
            # older/newer API: static get_transcript
            data = YouTubeTranscriptApi.get_transcript(video_id, languages=["en","id"])
            return " ".join([x["text"] for x in data])
    except Exception as e:
        _log(f"transcript failed: {e}")
        return None

def _summarize_with_gemini(transcript: str, video_url: str) -> str:
    key = _get_gemini_key()
    if not key:
        # fallback: simple extractive summary if gemini key missing
        snippet = transcript[:2000]
        return f"Transcript preview (Gemini key missing, raw snippet):\n\n{snippet}..."
    try:
        from google import genai as _genai
        from google.genai import types
        client = _genai.Client(api_key=key)
        max_chars = 80000
        truncated = transcript[:max_chars] + ("..." if len(transcript) > max_chars else "")
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"Please summarize this YouTube video transcript:\n\n{truncated}",
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are JARVIS, an AI assistant. "
                    "Summarize YouTube video transcripts clearly and concisely. "
                    "Structure: 1-sentence overview, then 3-5 key points. "
                    "Be direct. Address the user as 'sir'. "
                    "Match the language of the transcript."
                )
            )
        )
        return response.text.strip()
    except Exception as e:
        _log(f"Gemini summarize failed: {e}, trying fallback model")
        try:
            # fallback to older model name
            from google import genai as _genai
            from google.genai import types
            client = _genai.Client(api_key=key)
            resp = client.models.generate_content(
                model="gemini-1.5-flash",
                contents=f"Summarize this transcript:\n{transcript[:15000]}"
            )
            return resp.text.strip()
        except Exception as e2:
            return f"Summary generation failed: {e2}"

def _save_summary(content: str, video_url: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"youtube_summary_{ts}.txt"
    desktop = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    filepath = desktop / filename
    header = (
        f"JARVIS — YouTube Summary\n"
        f"{'─'*50}\n"
        f"URL    : {video_url}\n"
        f"Date   : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"{'─'*50}\n\n"
    )
    filepath.write_text(header + content, encoding="utf-8")
    try:
        if is_windows():
            subprocess.Popen(["notepad.exe", str(filepath)])
        elif is_mac():
            subprocess.Popen(["open", "-t", str(filepath)])
        else:
            subprocess.Popen(["xdg-open", str(filepath)])
    except Exception as e:
        _log(f"open editor failed: {e}")
    return str(filepath)

# --- Action handlers (MK50 refreshed) ---
def _handle_play(parameters: dict, player) -> str:
    query = parameters.get("query", "").strip()
    if not query:
        return "Please tell me what you'd like to watch, sir."

    if player:
        player.write_log(f"[YouTube] Searching: {query}")
    _log(f"Play request: {query}")

    # If query is already a URL -> direct open
    if _is_valid_youtube_url(query):
        _log(f"Direct URL detected, opening: {query}")
        _open_url(query)
        return f"Playing: {query}"

    # 1. Try official API first
    video_url = _official_search_first(query)
    if video_url:
        _log(f"Official API found: {video_url}")
        _open_url(video_url)
        return f"Playing: {query} (via YouTube Data API)"

    # 2. Fallback to scraping
    _log("Official API miss, trying scrape")
    video_url = _scrape_first_video_url(query)
    if video_url:
        _log(f"Scrape found: {video_url}")
        _open_url(video_url)
        return f"Playing: {query}"

    # 3. Fallback to search page
    _log("Scrape failed, opening search page")
    fallback_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp={_YT_VIDEO_FILTER}"
    _open_url(fallback_url)
    return f"Opened YouTube search for: {query} (manual selection required)"

def _handle_summarize(parameters: dict, player, speak) -> str:
    if not _TRANSCRIPT_OK:
        return "youtube-transcript-api is not installed. Run: pip install youtube-transcript-api"

    url = parameters.get("url", "").strip()
    if not url:
        url = _ask_for_url("Please paste the YouTube video URL:")
    if not url:
        return "No URL provided, sir. Summary cancelled."
    if not _is_valid_youtube_url(url):
        return "That doesn't appear to be a valid YouTube URL, sir."

    video_id = _extract_video_id(url)
    if not video_id:
        return "Could not extract video ID from that URL, sir."

    if player:
        player.write_log(f"[YouTube] Summarizing: {url}")
    if speak:
        speak("Fetching the transcript now, sir. One moment.")

    transcript = _get_transcript(video_id)
    if not transcript:
        return "I couldn't retrieve a transcript for that video, sir."

    if speak:
        speak("Transcript retrieved. Generating summary now.")

    try:
        summary = _summarize_with_gemini(transcript, url)
    except Exception as e:
        return f"Summary generation failed, sir: {e}"

    if speak:
        speak(summary)

    if parameters.get("save", False):
        saved_path = _save_summary(summary, url)
        return f"Summary complete and saved to Desktop: {saved_path}\n\n{summary}"

    return summary

def _handle_get_info(parameters: dict, player, speak) -> str:
    url = parameters.get("url", "").strip()
    if not url:
        url = _ask_for_url("Please paste the YouTube video URL:")
    if not url or not _is_valid_youtube_url(url):
        return "Please provide a valid YouTube URL, sir."

    video_id = _extract_video_id(url)
    if not video_id:
        return "Could not extract video ID, sir."

    if player:
        player.write_log(f"[YouTube] Getting info: {url}")

    # Try official first, then scrape
    info = _official_video_info(video_id)
    if not info:
        info = _scrape_video_info(video_id)

    if not info:
        return "Could not retrieve video information, sir."

    lines = [f"{k.capitalize()}: {v}" for k, v in info.items()]
    result = "\n".join(lines)

    if speak:
        speak(f"Here's the video info, sir. {result.replace(chr(10), '. ')}")

    return result

def _handle_trending(parameters: dict, player, speak) -> str:
    region = parameters.get("region", "ID").upper()
    if player:
        player.write_log(f"[YouTube] Trending: {region}")

    # Try official first
    trending = _official_trending(region=region, max_results=8)
    if not trending:
        trending = _scrape_trending(region=region, max_results=8)

    if not trending:
        return f"Could not fetch trending videos for region {region}, sir."

    lines = [f"Top trending videos in {region}:"]
    lines += [f"{v['rank']}. {v['title']} — {v['channel']}" for v in trending]
    result = "\n".join(lines)

    if speak:
        top3 = trending[:3]
        spoken = "Here are the top trending videos, sir. " + ". ".join(
            f"Number {v['rank']}: {v['title']} by {v['channel']}" for v in top3
        )
        speak(spoken)

    return result

def _handle_search(parameters: dict, player, speak) -> str:
    """New in MK50 refresh — search without playing, returns list"""
    query = parameters.get("query", "").strip()
    if not query:
        return "Please provide a search query, sir."
    limit = int(parameters.get("limit", 5))
    if player:
        player.write_log(f"[YouTube] Search: {query}")

    # Use official API
    key = _get_youtube_api_key()
    results = []
    if _REQUESTS_OK and key:
        try:
            params = {
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": min(limit, 10),
                "key": key
            }
            r = requests.get(f"{_YT_API}/search", params=params, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                for item in r.json().get("items", []):
                    snippet = item.get("snippet", {})
                    vid = (item.get("id") or {}).get("videoId","")
                    results.append(f"{snippet.get('title','')} — {snippet.get('channelTitle','')} (https://youtu.be/{vid})")
        except Exception as e:
            _log(f"search api failed: {e}")

    if not results:
        # fallback scrape list
        if _REQUESTS_OK:
            search_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}&sp={_YT_VIDEO_FILTER}"
            try:
                r = requests.get(search_url, headers=HEADERS, timeout=10)
                vids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', r.text)
                titles = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"\}\]', r.text)
                for i in range(min(limit, len(vids), len(titles))):
                    results.append(f"{titles[i]} (https://youtu.be/{vids[i]})")
            except Exception as e:
                _log(f"search scrape failed: {e}")

    if not results:
        return f"No results for '{query}', sir."

    text = f"Search results for '{query}':\n" + "\n".join([f"{i+1}. {r}" for i, r in enumerate(results)])
    if speak:
        speak(f"Found {len(results)} results for {query}, sir.")
    return text

_ACTION_MAP = {
    "play": _handle_play,
    "summarize": _handle_summarize,
    "get_info": _handle_get_info,
    "trending": _handle_trending,
    "search": _handle_search,  # new
}

def youtube_video(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    params = parameters or {}
    action = params.get("action", "play").lower().strip()

    if player:
        player.write_log(f"[YouTube] Action: {action} | MK50 Hybrid")
    _log(f"Action: {action} Params: {params}")

    handler = _ACTION_MAP.get(action)
    if handler is None:
        return f"Unknown YouTube action: '{action}'. Available: play, summarize, get_info, trending, search."

    try:
        if action == "play":
            return handler(params, player) or "Done."
        if action == "search":
            # search supports both 2-arg and 3-arg signatures for flexibility
            try:
                return handler(params, player, speak) or "Done."
            except TypeError:
                return handler(params, player) or "Done."
        return handler(params, player, speak) or "Done."
    except Exception as e:
        _log(f"Error in {action}: {e}")
        import traceback; traceback.print_exc()
        return f"YouTube {action} failed, sir: {e}"
