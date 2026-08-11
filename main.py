import os
os.environ["PYTHONWARNINGS"] = "ignore"
import platform as _platform
import subprocess as _subprocess
import warnings
def _custom_showwarning(message, category, filename, lineno, file=None, line=None):
    pass # Completely ignore all warnings from being printed
warnings.showwarning = _custom_showwarning
warnings.filterwarnings("ignore")

# ── Nuclear: force CREATE_NO_WINDOW on EVERY subprocess call on Windows ───────
# This patches Popen itself, so no per-file flag is needed anywhere.
if _platform.system() == "Windows":
    _OrigPopen = _subprocess.Popen

    class _Popen(_OrigPopen):
        def __init__(self, args, **kw):
            kw["creationflags"] = kw.get("creationflags", 0) | _subprocess.CREATE_NO_WINDOW
            kw.pop("startupinfo", None)   # drop any stale/shared STARTUPINFO
            super().__init__(args, **kw)

    _subprocess.Popen = _Popen
# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import re
import threading
import time
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

import sounddevice as sd
from google import genai
from google.genai import types
# §38 (S-33) — hanya untuk TIPE. Modul `ui` berukuran 2.622 baris Qt dan
# memakan 4.566 ms untuk dimuat, padahal `JarvisUI` lama TIDAK PERNAH
# diinstansiasi di jalur `python -m jarvis.main`: UI barunya diserahkan
# dari luar ke `JarvisLive(ui)`. Import ini dulu duduk di jalur kesiapan
# suara, jadi suara Jarvis siap 4,5 detik lebih lambat setiap boot.
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
)

from actions.file_processor import file_processor
from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.weather_report    import weather_action
from actions.send_message      import send_message
from actions.reminder          import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor  import _capture_camera, _capture_screen
from actions.youtube_video     import youtube_video
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.code_helper       import code_helper
from actions.dev_agent         import dev_agent
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater
from actions.system_monitor    import SystemMonitor, get_system_status
from actions.proactive         import ProactiveEngine


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


# Structured pipeline observability (Fase 1-2). Optional: legacy standalone
# runs keep working even if the jarvis package is unavailable.
try:
    from jarvis.core import log as _jlog
    from jarvis.core.state import (Outcome, PipelineState,
                                   PipelineStateMachine)
    _slog = _jlog.get("voice")
    _HAS_PIPELINE = True
except Exception:
    _slog = None
    _HAS_PIPELINE = False

try:
    from jarvis.integrations import voice_notices as _voice_notices
except Exception:
    _voice_notices = None
# Every external stage is bounded — a hung tool or a silent model can no
# longer freeze the receive loop or leave the user without feedback.
TOOL_TIMEOUT_S     = float(os.environ.get("JARVIS_TOOL_TIMEOUT_S", "60"))
RESPONSE_TIMEOUT_S = float(os.environ.get("JARVIS_RESPONSE_TIMEOUT_S", "30"))
MAX_SPEAK_S        = float(os.environ.get("JARVIS_MAX_SPEAK_S", "120"))
VOICE_TOOL_FINAL_TIMEOUT_S = float(
    os.environ.get("JARVIS_VOICE_TOOL_FINAL_TIMEOUT_S", "2.5")
)
VOICE_L1_HOOK = None  # optional; None preserves the legacy voice path
VOICE_TEXT_ONLY_HOOK = None  # optional; None preserves legacy voice path


class _VoiceStopRequested(Exception):
    """Internal cooperative shutdown signal for the legacy voice loop."""

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-3.1-flash-live-preview"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:    
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()

TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool — never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": (
            "Searches the web. Use for ANY question about current facts, events, prices, "
            "or topics — always prefer this over guessing. "
            "Modes: 'search' (default), 'news' (latest headlines on a topic), "
            "'research' (deep comprehensive answer), 'price' (product cost lookup), "
            "'compare' (side-by-side comparison of items)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query or topic"},
                "mode":   {"type": "STRING", "description": "search | news | research | price | compare"},
                "items":  {"type": "ARRAY",  "items": {"type": "STRING"}, "description": "Items to compare (compare mode)"},
                "aspect": {"type": "STRING", "description": "Comparison aspect: price | specs | reviews | features"},
            },
            "required": ["query"]
        }
    },
    {
        "name": "system_status",
        "description": (
            "Returns real-time system metrics: CPU usage, RAM, GPU load, CPU temperature, "
            "uptime, and process count. Use when the user asks about computer performance, "
            "temperature, memory, or resource usage."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "weather_report",
        "description": "Gives the weather report to user",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures the screen or webcam image and lets you analyze it. "
            "MUST be called when user asks what is on screen, what you see, "
            "look at camera, analyze my screen, etc. "
            "You have NO visual ability without this tool. "
            "After the image is captured it is sent directly to you — describe what you see and answer the user's question. "
            "When using camera: the live view stays open until user says close it or calls close_camera."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "close_camera",
        "description": (
            "Closes the live camera view shown on screen. "
            "Call when user says: close camera, stop camera, turn off camera, "
            "kamerayı kapat, kapat, creepy, etc."
        ),
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, etc."}
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls any web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, screenshots, navigation, any web-based task. "
            "Always pass the 'browser' parameter when the user specifies a browser (e.g. 'open in Edge', "
            "'use Firefox', 'open Chrome'). Multiple browsers can run simultaneously."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | get_url | press | new_tab | close_tab | screenshot | back | forward | reload | switch | list_browsers | close | close_all"},
                "browser":     {"type": "STRING", "description": "Target browser: chrome | edge | firefox | opera | operagx | brave | vivaldi | safari. Omit to use the currently active browser."},
                "url":         {"type": "STRING", "description": "URL for go_to / new_tab action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "engine":      {"type": "STRING", "description": "Search engine: google | bing | duckduckgo | yandex (default: google)"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up | down for scroll"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount in pixels (default: 500)"},
                "key":         {"type": "STRING", "description": "Key name for press action (e.g. Enter, Escape, F5)"},
                "path":        {"type": "STRING", "description": "Save path for screenshot"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use browser_control or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "shutdown_jarvis",
        "description": (
            "Shuts down the assistant completely. "
            "Call this when the user expresses intent to end the conversation, "
            "close the assistant, say goodbye, or stop Jarvis. "
            "The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
    "name": "file_processor",
    "description": (
        "Processes any file that the user has uploaded or dropped onto the interface. "
        "Use this when the user refers to an uploaded file and wants an action on it. "
        "Supports: images (describe/ocr/resize/compress/convert), "
        "PDFs (summarize/extract_text/to_word), "
        "Word docs & text files (summarize/fix/reformat/translate), "
        "CSV/Excel (analyze/stats/filter/sort/convert), "
        "JSON/XML (validate/format/analyze), "
        "code files (explain/review/fix/optimize/run/document/test), "
        "audio (transcribe/trim/convert/info), "
        "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
        "archives (list/extract), "
        "presentations (summarize/extract_text). "
        "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
        "If the user's command is ambiguous, pick the most logical action for that file type."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": (
                    "What to do with the file. Examples by type:\n"
                    "image: describe | ocr | resize | compress | convert | info\n"
                    "pdf: summarize | extract_text | to_word | info\n"
                    "docx/txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                    "csv/excel: analyze | stats | filter | sort | convert | info\n"
                    "json: validate | format | analyze | to_csv\n"
                    "code: explain | review | fix | optimize | run | document | test\n"
                    "audio: transcribe | trim | convert | info\n"
                    "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                    "archive: list | extract\n"
                    "pptx: summarize | extract_text | analyze"
                )
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width":     {"type": "INTEGER", "description": "Target width for image resize"},
            "height":    {"type": "INTEGER", "description": "Target height for image resize"},
            "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
            "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
            "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
            "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
            "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": []
    }
},
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
]

# --- Plugin system ---


class JarvisLive:

    def __init__(self, ui: "JarvisUI"):
        self.ui             = ui
        self.session              = None
        self.audio_in_queue       = None
        self.out_queue            = None
        self._loop                = None
        self._is_speaking         = False
        self._speaking_lock       = threading.Lock()
        self._phone_active        = False   # True while phone mic is streaming; pauses PC mic
        self._pending_vision       = None    # (img_bytes, mime_type, question, angle) to inject after tool response
        self._vision_cam_active    = False   # True if camera was opened for vision → auto-close after response
        self._vision_close_pending = False   # True after vision injected; next turn_complete closes camera
        self._vision_last_time     = 0.0     # monotonic time of last screen_process call (cooldown guard)
        self._vision_busy          = False   # True while a vision capture/inject cycle is in flight
        self._interrupted          = False   # True while draining audio after user interrupt
        self.ui.on_text_command   = self._on_text_command
        self.ui.on_remote_clicked = self._make_remote_key
        self.ui.on_interrupt      = self.interrupt
        self._turn_done_event: asyncio.Event | None = None
        self._dashboard     = None
        self._briefing_sent    = False          # morning briefing fires once per process
        self._sys_monitor      = SystemMonitor()  # persistent cooldown state
        self._proactive        = ProactiveEngine()
        self._last_user_speech = time.monotonic()  # updated on every user utterance
        # Fase 1-2: correlation id + explicit outcomes + hang watchdogs
        self._sm = PipelineStateMachine() if _HAS_PIPELINE else None
        if self._sm:
            self._sm.start_monitor()
        self._turn_id          = ""
        self._awaiting_since   = None   # monotonic ts while a reply is due
        self._speaking_started = 0.0
        self._stop_requested = threading.Event()
        self._async_stop: asyncio.Event | None = None

    def request_stop(self) -> None:
        """Request cooperative shutdown from the canonical runtime supervisor."""
        stop = getattr(self, "_stop_requested", None)
        if stop is None:
            stop = threading.Event()
            self._stop_requested = stop
        stop.set()
        loop = getattr(self, "_loop", None)
        async_stop = getattr(self, "_async_stop", None)
        if loop is not None and async_stop is not None and loop.is_running():
            loop.call_soon_threadsafe(async_stop.set)

    # ── structured trace helpers (no-ops without the jarvis package) ─────────
    def _trace(self, event: str, **kw):
        if _slog is not None:
            _slog.info(event, request_id=self._turn_id, **kw)

    def _sm_to(self, state_name: str):
        if self._sm:
            self._sm.to(PipelineState(state_name))

    def _make_remote_key(self):
        """Called from Qt main thread when user presses Remote Control."""
        if self._dashboard is None:
            self.ui.write_log(
                "SYS: Dashboard unavailable. "
                "Run: pip install fastapi \"uvicorn[standard]\" cryptography"
            )
            return None
        key    = self._dashboard.new_key()
        url    = self._dashboard.get_url()
        manual = self._dashboard.get_manual_url()
        return url, key, f"{url}/auto-login?key={key}", manual

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            changed = self._is_speaking != value
            self._is_speaking = value
            if value and changed:
                self._speaking_started = time.monotonic()
        if value:
            self.ui.set_state("SPEAKING")
            self._sm_to("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")
            self._sm_to("LISTENING")

    def interrupt(self) -> None:
        """Stop JARVIS mid-speech: drain queued audio and open mic immediately."""
        self._interrupted = True
        q = self.audio_in_queue
        if q:
            drained = 0
            while True:
                try:
                    q.get_nowait()
                    drained += 1
                except Exception:
                    break
            if drained:
                print(f"[JARVIS] ✋ Interrupted — {drained} audio chunks discarded")
        self.set_speaking(False)
        if self._turn_done_event:
            self._turn_done_event.clear()
        self.ui.write_log("SYS: Interrupted — listening...")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
        )

    async def _run_tool(self, loop, fn):
        """Blocking tool in the executor, bounded by TOOL_TIMEOUT_S — a hung
        tool can no longer freeze the receive loop / whole voice pipeline."""
        return await asyncio.wait_for(loop.run_in_executor(None, fn),
                                      TOOL_TIMEOUT_S)

    def _dispatch_native_agent(
        self,
        task: str,
        *,
        telemetry: dict | None = None,
    ) -> tuple[bool, str]:
        """Thin MK50 handoff with ACK-before-work and a concrete report.

        This wraps ``jarvis.agent.dispatch``; it does not replace the registry,
        loop, skills, or memory subsystems. Completion is fed back through the
        running Live session so a background result is not silent.
        """
        task = str(task or "").strip()
        trace_context = telemetry if isinstance(telemetry, dict) else {}
        trace_context.setdefault(
            "request_id", str(getattr(self, "_turn_id", "") or "")
        )
        trace_context.setdefault("call_ids", [])
        trace_context.setdefault("call_names", [])
        trace_started = False

        def _trace_agent(event: str, **fields) -> None:
            trace = getattr(self, "_trace", None)
            if not callable(trace):
                return
            call_ids = list(dict.fromkeys(
                str(value) for value in trace_context.get("call_ids", [])
                if str(value or "")
            ))
            trace(
                event,
                voice_request_id=str(trace_context.get("request_id", "")),
                call_ids=call_ids,
                function_call_count=len(call_ids),
                **fields,
            )

        def _trace_started_once() -> None:
            nonlocal trace_started
            if trace_started:
                return
            trace_started = True
            _trace_agent("voice.agent_task.started")

        if not task:
            message = (
                "Transkripsi suara belum lengkap; tidak ada tindakan yang "
                "dijalankan. Silakan ulangi perintah."
            )
            self.ui.write_log(f"SYS: {message}")
            _trace_agent("voice.agent_task.outcome", outcome="rejected")
            return False, message

        try:
            from jarvis.agent import conversation_context
            from jarvis.agent import dispatch as agent_dispatch
            from jarvis.agent import delivery_lifecycle
            from jarvis.agent.interaction import unavailable_reason
            from jarvis.agent.adapters.ui import UIAdapter
        except Exception as exc:
            message = f"Agent native Jarvis tidak dapat dimuat: {str(exc)[:120]}"
            self.ui.write_log(f"ERR: {message}")
            return False, message

        conversation_id = "voice-live"
        task = conversation_context.STORE.augment(conversation_id, task)

        def _speak_brief(line: str) -> None:
            self.speak(str(line or ""))

        def _deliver_agent_result(line: str, *, ok: bool) -> None:
            notices = globals().get("_voice_notices")
            queued = bool(
                notices is not None
                and notices.remember_agent_result(task, line, ok=ok)
            )
            if not queued:
                _speak_brief(line)

        def _on_ack(ack: str) -> None:
            _trace_started_once()
            brief = str(ack or "")
            delivery_lifecycle.acknowledged("voice", brief)
            self.ui.write_log(f"Jarvis: {brief}")
            _speak_brief(brief)

        def _on_done(result: str) -> None:
            delivery = delivery_lifecycle.success(
                str(result or "Tugas selesai tanpa keluaran."), task,
                source="voice", naturalize=True,
            )
            conversation_context.STORE.remember_success(
                conversation_id, task=task, delivery=delivery
            )
            self.ui.write_log(f"Agent: {delivery.display_text[:600]}")
            _deliver_agent_result(delivery.speech_text, ok=True)
            _trace_started_once()
            _trace_agent("voice.agent_task.outcome", outcome="success")

        def _on_error(error: str) -> None:
            delivery = delivery_lifecycle.failure(error, task, source="voice")
            self.ui.write_log(f"ERR: Agent native gagal: "
                              f"{delivery.display_text[:300]}")
            _deliver_agent_result(delivery.speech_text, ok=False)
            _trace_started_once()
            _trace_agent("voice.agent_task.outcome", outcome="failed")

        adapter = None
        window = getattr(self.ui, "_win", None)
        if window is not None:
            adapter = UIAdapter(window)

        started = agent_dispatch.dispatch_async(
            task,
            adapter=adapter,
            on_ack=_on_ack,
            on_done=_on_done,
            on_error=_on_error,
        )
        if not started:
            delivery = delivery_lifecycle.failure(
                unavailable_reason(task), task, source="voice"
            )
            self.ui.write_log(f"SYS: {delivery.display_text}")
            _trace_agent("voice.agent_task.outcome", outcome="rejected")
            # VoiceToolGate akan menyampaikan notice ini setelah boundary
            # turn aman, saat output Gemini lama tidak lagi ditekan.
            return False, delivery.speech_text

        _trace_started_once()
        self.ui.set_state("THINKING")
        self.ui.write_log(f"SYS: Agent native mengerjakan — {task[:120]}")
        return True, "Tugas dialihkan satu kali ke agent native Jarvis."

    @staticmethod
    def _native_agent_tool_responses(calls, status: str):
        """Acknowledge suppressed Live tool calls without executing them."""
        return [
            types.FunctionResponse(
                id=fc.id,
                name=fc.name,
                response={"result": status, "routed_to": "native_agent"},
            )
            for fc in calls
        ]

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})
        t0 = time.monotonic()

        print(f"[JARVIS] 🔧 {name}  {args}")
        self._trace("tool.start", tool=name)
        self.ui.set_state("THINKING")
        self._sm_to("PROCESSING")

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "open_app":
                r = await self._run_tool(loop,lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."

            elif name == "weather_report":
                r = await self._run_tool(loop,lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."

            elif name == "browser_control":
                r = await self._run_tool(loop,lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "file_controller":
                r = await self._run_tool(loop,lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "send_message":
                r = await self._run_tool(loop,lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await self._run_tool(loop,lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."

            elif name == "youtube_video":
                r = await self._run_tool(loop,lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "screen_process":
                import time as _t_mod
                _now = _t_mod.monotonic()
                _cooldown = 4.0  # seconds — covers echo window after speaking ends
                if self._vision_busy or (_now - self._vision_last_time) < _cooldown:
                    _wait = max(0, _cooldown - (_now - self._vision_last_time))
                    print(f"[Vision] ⏳ Cooldown active ({_wait:.1f}s remaining) — ignoring duplicate call")
                    result = "Vision is still processing the previous request. I will not call this again."
                else:
                    self._vision_busy      = True
                    self._vision_last_time = _now
                    angle     = args.get("angle", "screen").lower()
                    user_text = args.get("text", "What do you see?")
                    if angle == "camera":
                        # Single camera owner: start the live stream and read its
                        # newest clean frame instead of opening a 2nd handle
                        # (the 2nd open was why JARVIS sometimes "couldn't see").
                        self.ui.start_camera_stream()
                        img_b = mime_t = None
                        if hasattr(self.ui, "get_camera_snapshot"):
                            img_b = await self._run_tool(
                                loop, lambda: self.ui.get_camera_snapshot(2.5))
                            if img_b:
                                mime_t = "image/jpeg"
                        if not img_b:                       # stream unavailable → fallback
                            img_b, mime_t = await self._run_tool(loop, _capture_camera)
                        self._vision_cam_active = True
                        print(f"[Vision] 📷 Camera: {len(img_b):,} bytes")
                        _stall = "camera"
                    else:
                        img_b, mime_t = await self._run_tool(loop,_capture_screen)
                        print(f"[Vision] 🖥️  Screen: {len(img_b):,} bytes")
                        _stall = "screen"
                    self._pending_vision = (img_b, mime_t, user_text, angle)
                    result = (
                        f"[VISION_ACTIVE] {_stall.capitalize()} captured. "
                        f"Immediately say ONE natural sentence in the user's language "
                        f"(e.g. 'Looking at your {_stall} now, sir' / "
                        f"'{'Kameraya' if _stall == 'camera' else 'Ekrana'} bakıyorum efendim'). "
                        f"Do NOT describe or guess content — the actual image arrives in the NEXT message."
                    )

            elif name == "close_camera":
                self.ui.stop_camera_stream()
                result = "Camera closed."

            elif name == "computer_settings":
                r = await self._run_tool(loop,lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "desktop_control":
                r = await self._run_tool(loop,lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "code_helper":
                r = await self._run_tool(loop,lambda: code_helper(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "dev_agent":
                r = await self._run_tool(loop,lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "web_search":
                r = await self._run_tool(loop,lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."
                # Mirror results to the on-screen content panel
                _mode = args.get("mode", "search")
                if r and not r.startswith("No results") and not r.startswith("Search failed"):
                    _query = args.get("query") or ", ".join(args.get("items", []))
                    _label = f"{_mode.upper()} — {_query[:38]}" if _query else _mode.upper()
                    self.ui.show_content(_label, r)
            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await self._run_tool(
                    loop,
                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "computer_control":
                r = await self._run_tool(loop,lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "game_updater":
                r = await self._run_tool(loop,lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "flight_finder":
                r = await self._run_tool(loop,lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "system_status":
                r = await self._run_tool(loop,get_system_status)
                result = str(r)

            elif name == "shutdown_jarvis":
                self.ui.write_log("SYS: Shutdown requested.")
                self.speak("Goodbye, sir.")
                def _shutdown():
                    import time, os
                    time.sleep(1)
                    os._exit(0)
                threading.Thread(target=_shutdown, daemon=True).start()

            else:
                result = f"Unknown tool: {name}"

        except (asyncio.TimeoutError, TimeoutError):
            result = (f"Tool '{name}' timed out after {TOOL_TIMEOUT_S:.0f} "
                      "seconds and was cancelled. Tell the user briefly.")
            self._trace("tool.timeout", tool=name,
                        elapsed_s=round(time.monotonic() - t0, 1))
            self.speak_error(name, f"timed out after {TOOL_TIMEOUT_S:.0f}s")
        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self._trace("tool.error", tool=name, exc_type=type(e).__name__,
                        error=str(e)[:120])
            self.speak_error(name, e)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        self._trace("tool.done", tool=name,
                    elapsed_s=round(time.monotonic() - t0, 2),
                    result=str(result)[:80])
        print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()

        def _safe_put(msg):
            # bounded queue: when the uplink stalls, drop the oldest chunk
            # instead of raising QueueFull into the event loop
            try:
                self.out_queue.put_nowait(msg)
            except asyncio.QueueFull:
                try:
                    self.out_queue.get_nowait()
                    self.out_queue.put_nowait(msg)
                except Exception:
                    pass

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            if not jarvis_speaking and not self.ui.muted and not self._phone_active:
                data = indata.tobytes()
                loop.call_soon_threadsafe(
                    _safe_put, {"data": data, "mime_type": "audio/pcm;rate=16000"}
                )

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                print("[JARVIS] 🎤 Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[JARVIS] ❌ Mic: {e}")
            raise

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        from jarvis.agent.router import Tier
        from jarvis.agent.voice_gate import FunctionCallHistory, VoiceToolGate

        out_buf, in_buf = [], []
        turn_had_audio = False
        history = getattr(self, "_voice_call_history", None)
        if history is None:
            history = FunctionCallHistory()
            self._voice_call_history = history
        voice_gate = VoiceToolGate(history=history)
        pending_tool_timeout = None
        agent_status = ""
        agent_notice = ""
        suppress_live_output = False
        voice_turn_complete_seen = False
        voice_action_cancelled = False
        l1_handled = False
        turn_action_started = False
        turn_completion_source = ""
        turn_tool_response_sent = False
        observed_call_ids = []
        observed_call_names = []
        active_agent_telemetry = None

        def _mark_live_healthy():
            tracker = getattr(self, "_voice_reconnect_backoff", None)
            if tracker is not None:
                self._conn_backoff = tracker.healthy()
            else:
                from jarvis.integrations import voice_live_lifecycle
                self._conn_backoff = voice_live_lifecycle.reset_backoff()

        def _cancel_tool_timeout():
            nonlocal pending_tool_timeout
            task, pending_tool_timeout = pending_tool_timeout, None
            if task is not None and task is not asyncio.current_task():
                task.cancel()

        def _reset_voice_turn(*, deliver_notice: bool = True):
            nonlocal agent_status, agent_notice, suppress_live_output
            nonlocal voice_turn_complete_seen, voice_action_cancelled, l1_handled
            nonlocal turn_action_started, turn_completion_source
            nonlocal turn_tool_response_sent, observed_call_ids
            nonlocal observed_call_names, active_agent_telemetry
            notice = agent_notice if deliver_notice else ""
            _cancel_tool_timeout()
            voice_gate.reset()
            agent_status = ""
            agent_notice = ""
            suppress_live_output = False
            voice_turn_complete_seen = False
            voice_action_cancelled = False
            l1_handled = False
            turn_action_started = False
            turn_completion_source = ""
            turn_tool_response_sent = False
            observed_call_ids = []
            observed_call_names = []
            active_agent_telemetry = None
            if notice:
                # The original heavy turn has reached a safe boundary, so the
                # Live response carrying this honest failure will not be
                # swallowed by suppress_live_output.
                self.speak(notice)

        def _remember_function_call(call) -> tuple[str, str]:
            call_id = str(getattr(call, "id", "") or "")
            function = str(getattr(call, "name", "") or "")
            if call_id and call_id not in observed_call_ids:
                observed_call_ids.append(call_id)
            if function and function not in observed_call_names:
                observed_call_names.append(function)
            if active_agent_telemetry is not None:
                linked_ids = active_agent_telemetry.setdefault("call_ids", [])
                linked_names = active_agent_telemetry.setdefault("call_names", [])
                newly_linked = bool(call_id and call_id not in linked_ids)
                if newly_linked:
                    linked_ids.append(call_id)
                if function and function not in linked_names:
                    linked_names.append(function)
                if newly_linked:
                    self._trace(
                        "voice.agent_task.linked",
                        voice_request_id=str(
                            active_agent_telemetry.get("request_id", "")
                        ),
                        call_id=call_id,
                        function=function,
                    )
            return call_id, function

        def _claim_heavy_route():
            nonlocal agent_status, agent_notice, suppress_live_output
            nonlocal turn_action_started, turn_completion_source
            nonlocal active_agent_telemetry
            if voice_action_cancelled:
                return
            route = voice_gate.route
            if route is None or route.tier < Tier.AGENT:
                return
            suppress_live_output = True
            self._awaiting_since = None
            task = voice_gate.claim_agent_task()
            if task:
                if active_agent_telemetry is None:
                    active_agent_telemetry = {
                        "request_id": str(self._turn_id or ""),
                        "call_ids": list(observed_call_ids),
                        "call_names": list(observed_call_names),
                    }
                started, agent_status = self._dispatch_native_agent(
                    task,
                    telemetry=active_agent_telemetry,
                )
                if started:
                    turn_action_started = True
                    turn_completion_source = "native_agent"
                if not started:
                    agent_notice = agent_status
                    _ensure_tool_timeout()
            elif not agent_status:
                agent_status = (
                    "Transkripsi suara tidak lengkap; tool Gemini ditekan "
                    "dan tidak ada tindakan yang dijalankan."
                )
                agent_notice = agent_status
                _ensure_tool_timeout()

        async def _flush_tool_batch(batch):
            nonlocal agent_status, l1_handled, turn_action_started
            nonlocal turn_completion_source, turn_tool_response_sent
            if batch is None:
                return False
            _cancel_tool_timeout()
            fn_responses = []
            fresh_calls = []
            delivery_records = []
            for fc in batch.calls:
                call_id = str(getattr(fc, "id", "") or "")
                function = str(getattr(fc, "name", "") or "")
                state = history.state(call_id)
                if state in {"result_cached", "delivered"}:
                    cached = history.result(call_id)
                    if cached is not None:
                        fn_responses.append(cached)
                        delivery_records.append(
                            (call_id, function, cached, "replayed_cached")
                        )
                    continue
                if state == "in_flight":
                    self._trace(
                        "voice.function_call.suppressed",
                        call_id=call_id,
                        function=function,
                        state=state,
                    )
                    continue
                if state == "unknown":
                    response = self._native_agent_tool_responses(
                        [fc],
                        "Outcome tindakan sebelumnya tidak diketahui; "
                        "Jarvis tidak mengulanginya secara otomatis.",
                    )[0]
                    fn_responses.append(response)
                    delivery_records.append(
                        (call_id, function, response, "unknown_previous_outcome")
                    )
                    continue
                if history.start(call_id):
                    fresh_calls.append(fc)
                    self._trace(
                        "voice.function_call.started",
                        call_id=call_id,
                        function=function,
                        state=history.state(call_id),
                    )

            if l1_handled and fresh_calls:
                fresh_disposition = "handled_l1"
                turn_action_started = True
                turn_completion_source = "local_l1"
                responses = self._native_agent_tool_responses(
                    fresh_calls,
                    "Aksi ditangani satu kali oleh jalur lokal L1; "
                    "tool Gemini tidak dijalankan.",
                )
            elif batch.route.tier >= Tier.AGENT and fresh_calls:
                fresh_disposition = "routed_to_native"
                _claim_heavy_route()
                responses = self._native_agent_tool_responses(
                    fresh_calls,
                    agent_status or "Tugas dialihkan ke agent native Jarvis.",
                )
            else:
                fresh_disposition = "executed"
                if fresh_calls:
                    turn_action_started = True
                    turn_completion_source = "legacy_tool"
                responses = []
                for fc in fresh_calls:
                    print(f"[JARVIS] 📞 {fc.name}")
                    responses.append(await self._execute_tool(fc))

            for fc, response in zip(fresh_calls, responses):
                call_id = str(getattr(fc, "id", "") or "")
                function = str(getattr(fc, "name", "") or "")
                history.store_result(call_id, response)
                delivery_records.append(
                    (call_id, function, response, fresh_disposition)
                )
            fn_responses.extend(responses)
            sent_responses = False
            if fn_responses and self.session:
                try:
                    await self.session.send_tool_response(
                        function_responses=fn_responses
                    )
                except Exception as exc:
                    for call_id, function, _response, disposition in delivery_records:
                        self._trace(
                            "voice.function_call.delivery_failed",
                            call_id=call_id,
                            function=function,
                            disposition=disposition,
                            state=history.state(call_id),
                            error_type=type(exc).__name__,
                        )
                    raise
                sent_responses = True
                turn_tool_response_sent = True
                for call_id, function, response, disposition in delivery_records:
                    history.mark_delivered(call_id, result=response)
                    self._trace(
                        "voice.function_call.disposition",
                        call_id=call_id,
                        function=function,
                        disposition=disposition,
                        state=history.state(call_id),
                    )
                _mark_live_healthy()
                # Native/L1 owns its own bounded lifecycle and callbacks. Only a
                # legacy light tool leaves Gemini owing a spoken answer.
                self._awaiting_since = (
                    time.monotonic()
                    if fresh_calls
                    and not l1_handled
                    and batch.route.tier < Tier.AGENT
                    else None
                )
                if l1_handled:
                    l1_handled = False
            if agent_notice:
                _ensure_tool_timeout()
            return sent_responses

        async def _tool_final_timeout():
            try:
                await asyncio.sleep(max(0.1, VOICE_TOOL_FINAL_TIMEOUT_S))
                if voice_action_cancelled:
                    _reset_voice_turn(deliver_notice=False)
                    return
                batch = voice_gate.timeout()
                _claim_heavy_route()
                if batch is not None:
                    self._trace("voice.route_timeout", pending=len(batch.calls))
                    await _flush_tool_batch(batch)
                if voice_turn_complete_seen or agent_notice:
                    _reset_voice_turn()
            except asyncio.CancelledError:
                return

        def _ensure_tool_timeout(*, restart: bool = False):
            nonlocal pending_tool_timeout
            if restart:
                _cancel_tool_timeout()
            if pending_tool_timeout is None or pending_tool_timeout.done():
                pending_tool_timeout = asyncio.create_task(
                    _tool_final_timeout(),
                    name="voice-tool-final-timeout",
                )

        try:
            while True:
                async for response in self.session.receive():
                    reset_voice_after_response = False
                    batch_sent = False

                    if response.data:
                        self._awaiting_since = None      # model is answering
                        if self._interrupted or suppress_live_output:
                            pass  # discard: interrupted
                        else:
                            if self._turn_done_event and self._turn_done_event.is_set():
                                self._turn_done_event.clear()
                            # Split into ~50 ms chunks so interrupt() stops audio within 50 ms
                            # (24000 Hz × 2 bytes/sample × 0.05 s = 2400 bytes per slice)
                            _audio_data = response.data
                            turn_had_audio = True
                            _SLICE = 2400
                            for _i in range(0, len(_audio_data), _SLICE):
                                self.audio_in_queue.put_nowait(_audio_data[_i : _i + _SLICE])

                    if response.server_content:
                        sc = response.server_content

                        if (not suppress_live_output
                                and sc.output_transcription
                                and sc.output_transcription.text):
                            txt = _clean_transcript(sc.output_transcription.text)
                            if txt and txt != (out_buf[-1] if out_buf else ""):
                                out_buf.append(txt)

                        transcription = sc.input_transcription
                        if transcription:
                            txt = _clean_transcript(transcription.text or "")
                            if txt:
                                if not in_buf:
                                    # a new voice command starts here — one
                                    # correlation id traces it end-to-end
                                    self._turn_id = (self._sm.begin_request()
                                                     if self._sm else "")
                                    self._sm_to("TRANSCRIBING")
                                    self._trace("turn.input_started")
                                in_buf.append(txt)
                                self._last_user_speech = time.monotonic()
                                self._awaiting_since = time.monotonic()
                            finished = transcription.finished is True
                            batch = voice_gate.add_transcription(
                                txt,
                                finished=finished,
                            )
                            if txt and not finished:
                                # A late/new utterance may start during the
                                # post-turn grace period. Measure the fallback
                                # from its latest chunk, never from an older
                                # model-only turn boundary.
                                _ensure_tool_timeout(restart=True)
                            if finished:
                                final_voice_text = voice_gate.text
                                l1_handled = bool(
                                    VOICE_L1_HOOK
                                    and await VOICE_L1_HOOK(self, voice_gate)
                                )
                                if l1_handled and voice_gate.route is None:
                                    voice_gate.add_transcription(
                                        final_voice_text,
                                        finished=True,
                                    )
                                if not l1_handled:
                                    _claim_heavy_route()
                                batch_sent = await _flush_tool_batch(batch)

                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            # If this turn_complete ends an interrupted response, clear the
                            # flag and skip all further processing for that turn.
                            if self._interrupted:
                                self._interrupted = False
                                in_buf  = []
                                out_buf = []
                                _reset_voice_turn(deliver_notice=False)
                                continue

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "user",
                                        "text": full_in,
                                        "ts": datetime.now().isoformat(),
                                    }))
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Jarvis: {full_out}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "jarvis",
                                        "text": full_out,
                                        "ts": datetime.now().isoformat(),
                                    }))
                            had_output_payload = bool(full_out or turn_had_audio)
                            if VOICE_TEXT_ONLY_HOOK and full_out:
                                await VOICE_TEXT_ONLY_HOOK(
                                    self, full_out, had_audio=turn_had_audio)
                            out_buf = []
                            turn_had_audio = False

                            # explicit per-turn outcome (Fase 1)
                            self._awaiting_since = None
                            if full_in or full_out:
                                if full_out:
                                    outcome = "success"
                                    completion = "model_output"
                                elif self._pending_vision:
                                    outcome = "success"      # tool turn
                                    completion = "vision_tool"
                                elif voice_action_cancelled:
                                    outcome = "cancelled"
                                    completion = "cancelled"
                                elif turn_action_started or turn_tool_response_sent:
                                    outcome = "success"
                                    completion = (
                                        "deferred_native_agent"
                                        if turn_completion_source == "native_agent"
                                        else (turn_completion_source or "tool_response")
                                    )
                                else:
                                    outcome = "unrecognized_speech"
                                    completion = "none"
                                self._trace("turn.outcome", outcome=outcome,
                                            had_input=bool(full_in),
                                            had_output=bool(full_out),
                                            completion=completion,
                                            function_call_ids=list(
                                                observed_call_ids
                                            ))
                                if self._sm and outcome == "success":
                                    self._sm.finish(Outcome.SUCCESS)

                            # Vision injection: model finished tool-response turn → now send the image
                            if self._pending_vision and self.session:
                                import base64 as _b64
                                img_b, mime_t, question, angle = self._pending_vision
                                self._pending_vision = None
                                b64 = _b64.b64encode(img_b).decode("ascii")
                                print(f"[Vision] 📤 {len(img_b):,} bytes (angle={angle}) → main session")
                                await self.session.send_client_content(
                                    turns={"parts": [
                                        {"inline_data": {"mime_type": mime_t, "data": b64}},
                                        {"text": question},
                                    ]},
                                    turn_complete=True,
                                )
                                # Mark next turn_complete behaviour depending on angle
                                if self._vision_cam_active:
                                    # Camera: keep busy until JARVIS finishes speaking the answer
                                    self._vision_cam_active    = False
                                    self._vision_close_pending = True
                                else:
                                    # Screen-only: no camera to close; release busy flag now
                                    self._vision_busy = False
                            elif self._vision_close_pending:
                                # This turn_complete IS the vision answer — release busy flag but KEEP camera open
                                self._vision_close_pending = False
                                self._vision_busy = False
                                # async def _cam_close():
                                #     await asyncio.sleep(2.0)
                                #     self.ui.stop_camera_stream()
                                # asyncio.create_task(_cam_close())

                            voice_turn_complete_seen = True
                            if had_output_payload:
                                _mark_live_healthy()
                            if _voice_notices is not None:
                                await _voice_notices.flush_at_turn_boundary(self)
                            if voice_gate.route is None:
                                # Input transcription is explicitly unordered
                                # relative to model turns. Keep even an empty

                                # final transcript or pending call may follow.
                                _ensure_tool_timeout()
                            else:
                                reset_voice_after_response = not l1_handled
                                if l1_handled:
                                    _ensure_tool_timeout()

                    if response.tool_call_cancellation:
                        requested_ids = tuple(dict.fromkeys(
                            str(value)
                            for value in (response.tool_call_cancellation.ids or [])
                            if str(value or "")
                        ))
                        cancelled = voice_gate.cancel(requested_ids)
                        for call_id in requested_ids:
                            self._trace(
                                "voice.function_call.cancelled",
                                call_id=call_id,
                                accepted=history.state(call_id) == "cancelled",
                                state=history.state(call_id),
                            )
                        if cancelled:
                            voice_action_cancelled = True
                            self._trace(
                                "voice.tool_cancelled",
                                count=cancelled,
                                call_ids=list(requested_ids),
                            )
                        if cancelled and voice_gate.pending_count == 0:
                            # Keep a short cleanup timer: final transcription
                            # and cancellation are independently ordered too.
                            _ensure_tool_timeout()

                    if response.tool_call:
                        self._awaiting_since = None
                        function_calls = tuple(
                            response.tool_call.function_calls or []
                        )
                        for function_call in function_calls:
                            call_id, function = _remember_function_call(
                                function_call
                            )
                            self._trace(
                                "voice.function_call.received",
                                call_id=call_id,
                                function=function,
                                id_present=bool(call_id),
                            )
                        batch = voice_gate.queue_calls(function_calls)
                        if batch is not None:
                            batch_sent = await _flush_tool_batch(batch)
                        elif voice_gate.pending_count:
                            # Do not execute a FunctionCall until the SDK's
                            # final input-transcription boundary arrives.
                            _ensure_tool_timeout()

                    if reset_voice_after_response:
                        if not l1_handled or batch_sent:
                            _reset_voice_turn()
                        else:
                            _ensure_tool_timeout()
                    elif (voice_turn_complete_seen
                          and voice_gate.route is not None
                          and voice_gate.pending_count == 0
                          and (not l1_handled or batch_sent)):
                        _reset_voice_turn()
        except Exception as e:
            from jarvis.integrations import voice_live_lifecycle
            failure = voice_live_lifecycle.classify(e)
            print(
                f"[JARVIS] ❌ Recv: {failure.leaf_type} "
                f"({failure.kind})"
            )
            raise
        finally:
            _cancel_tool_timeout()
            for call_id in tuple(history):
                if history.state(call_id) == "in_flight":
                    history.mark_unknown(call_id)

    async def _play_audio(self):
        print("[JARVIS] 🔊 Play started")

        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue
                self.set_speaking(True)
                try:
                    await asyncio.to_thread(stream.write, chunk)
                except (RuntimeError, asyncio.CancelledError):
                    break   # executor shutting down — exit cleanly
        except Exception as e:
            print(f"[JARVIS] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    # ── Watchdogs (Fase 1-2): no command may end in silence ────────────────────

    async def _response_watchdog(self):
        """Two guards:
        1. User spoke but no model reply within RESPONSE_TIMEOUT_S → tell the
           user, log outcome=timeout, reset to LISTENING.
        2. SPEAKING stuck past MAX_SPEAK_S with an empty audio queue → force
           the mic open again (TTS must never lock the listener permanently).
        """
        while True:
            await asyncio.sleep(2)

            aw = self._awaiting_since
            if aw is not None and time.monotonic() - aw > RESPONSE_TIMEOUT_S:
                self._awaiting_since = None
                self._trace("turn.outcome", outcome="timeout",
                            waited_s=round(time.monotonic() - aw, 1))
                if self._sm:
                    self._sm.finish(Outcome.TIMEOUT)
                self.ui.write_log(
                    "SYS: Perintah membutuhkan waktu terlalu lama dan "
                    "dibatalkan — silakan ulangi.")
                try:
                    self.speak(
                        "Maaf sir, perintah tadi membutuhkan waktu terlalu "
                        "lama dan saya batalkan. Silakan ulangi.")
                except Exception as e:
                    print(f"[Watchdog] speak failed: {e}")
                if not self.ui.muted:
                    self.ui.set_state("LISTENING")

            with self._speaking_lock:
                speaking = self._is_speaking
                started = self._speaking_started
            if (speaking and time.monotonic() - started > MAX_SPEAK_S
                    and self.audio_in_queue is not None
                    and self.audio_in_queue.empty()):
                self._trace("tts.watchdog_reset",
                            stuck_s=round(time.monotonic() - started, 1))
                self.ui.write_log("SYS: Status bicara macet — mikrofon "
                                  "dibuka kembali.")
                self.set_speaking(False)

    # ── Morning briefing ────────────────────────────────────────────────────────

    async def _send_startup_briefing(self) -> None:
        """
        Two-phase briefing for instant perceived response:
          Phase 1 — immediate greeting (no tools, no fetch) → Jarvis speaks in <2s
          Phase 2 — news fetched in background, injected after greeting finishes
        """
        await asyncio.sleep(0.3)
        if not self.session:
            return

        # ── memory ───────────────────────────────────────────────────────────
        memory   = load_memory()
        identity = memory.get("identity", {})

        def _val(k: str) -> str:
            e = identity.get(k, {})
            return (e.get("value", "") if isinstance(e, dict) else str(e)).strip()

        lang = _val("language")
        name = _val("name")

        from datetime import datetime
        time_str = datetime.now().strftime("%H:%M")

        # ── Phase 1: instant greeting — one simple sentence ──────────────────
        lang_clause = f" Respond in {lang}." if lang else ""
        name_clause = f" Address the user as {name}." if name else ""
        p1 = (
            f"Greet the user, mention it is {time_str}, and say you are fetching today's news headlines now. "
            f"One short sentence only. Do not call any tools.{lang_clause}{name_clause}"
        )

        await self.session.send_client_content(
            turns={"parts": [{"text": p1}]},
            turn_complete=True,
        )
        self.ui.write_log("SYS: Briefing phase 1 (greeting) sent.")

        # ── Phase 2: fetch news in background, deliver after greeting plays ───
        async def _guarded_news():
            try:
                await self._briefing_news_phase(lang)
            except Exception as e:
                print(f"[Briefing] Phase 2 error: {e}")
                self.ui.write_log(f"SYS: Briefing news phase failed: {e}")
        asyncio.create_task(_guarded_news())

    async def _briefing_news_phase(self, lang: str) -> None:
        """
        Sends phase-2 (news) to Gemini ~1.5 s after phase-1 is dispatched so
        Gemini starts working on it while phase-1 audio is still playing.
        """
        lang_str = f" Respond in {lang}." if lang else ""

        # 1.5 s is enough for Gemini to finish generating phase-1 audio on its
        # side (turn_complete) while the greeting is still being played locally.
        await asyncio.sleep(1.5)

        if not self.session:
            return

        p2 = (
            "[BRIEFING] Call web_search with mode='news' and query='top world news today' "
            "to find actual recent news articles with real event headlines (not just website names). "
            "After the search, say ONE specific news event from the results in one sentence, "
            f"then say the full list is displayed on screen.{lang_str}"
        )

        await self.session.send_client_content(
            turns={"parts": [{"text": p2}]},
            turn_complete=True,
        )
        self.ui.write_log("SYS: Briefing phase 2 (news) sent.")

    # ── System monitor ──────────────────────────────────────────────────────────

    async def _run_system_monitor(self) -> None:
        """Background task: voice alerts when metrics exceed thresholds."""
        while True:
            await asyncio.sleep(10)
            alert = await asyncio.to_thread(self._sys_monitor.check)
            if alert and self.session:
                try:
                    await self.session.send_client_content(
                        turns={"parts": [{"text": alert}]},
                        turn_complete=True,
                    )
                except Exception as e:
                    print(f"[Monitor] ⚠️ Could not send alert: {e}")

    # ── Proactive mode ──────────────────────────────────────────────────────────

    async def _run_proactive_mode(self) -> None:
        """
        Background task: periodically checks if the user has been silent long enough,
        then hands time + memory context to Gemini so it can decide what (if anything)
        to say proactively. No hardcoded rules — Gemini makes the call.
        """
        while True:
            await asyncio.sleep(60)   # evaluate once per minute

            if not self.session:
                continue

            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                continue

            if not self._proactive.should_trigger(self._last_user_speech):
                continue

            self._proactive.mark_triggered()

            try:
                memory = await asyncio.to_thread(load_memory)
                prompt = self._proactive.build_prompt(memory)
                await self.session.send_client_content(
                    turns={"parts": [{"text": prompt}]},
                    turn_complete=True,
                )
                self.ui.write_log("SYS: Proactive check-in.")
            except Exception as e:
                print(f"[Proactive] ⚠️ {e}")

    # ── Phone audio relay ────────────────────────────────────────────────────────

    async def _relay_phone_audio(self) -> None:
        """Forward phone mic PCM chunks from dashboard queue into the Gemini Live session."""
        q = self._dashboard._phone_audio_queue
        while True:
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # No audio for 1 s → phone mic inactive, give PC mic back
                self._phone_active = False
                continue
            self._phone_active = True   # phone is streaming — silence PC mic
            with self._speaking_lock:
                speaking = self._is_speaking
            if not speaking and not self.ui.muted:
                try:
                    self.out_queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass

    def _on_phone_connected(self) -> None:
        self.ui.write_log("SYS: Phone connected via Remote Dashboard.")
        self.ui.notify_phone_connected()

    # ── dashboard command relay ─────────────────────────────────────────────

    async def _process_dashboard_commands(self) -> None:
        while True:
            try:
                text = await asyncio.wait_for(
                    self._dashboard._command_queue.get(), timeout=0.5
                )
                if not text:
                    continue

                from jarvis.agent.router import Tier, classify

                route = classify(text, {"source": "dashboard"})
                if _slog is not None:
                    _slog.info(
                        "router.decision",
                        source="dashboard",
                        tier=int(route.tier),
                        lane=route.lane,
                        reason=route.reason,
                    )

                if route.tier >= Tier.AGENT:
                    # Dashboard text is authoritative here.  Heavy commands
                    # bypass Gemini Live and enter the existing native agent
                    # dispatcher; callbacks are marshalled back to this loop.
                    from jarvis.agent import dispatch as agent_dispatch
                    from jarvis.agent.interaction import (
                        render_failure, render_success, unavailable_reason,
                    )

                    loop = asyncio.get_running_loop()
                    self.ui.write_log(f"[Web]: {text}")

                    def _broadcast_agent(text_out: str) -> None:
                        def _schedule() -> None:
                            asyncio.create_task(self._dashboard.broadcast({
                                "type": "log",
                                "speaker": "jarvis",
                                "text": text_out,
                            }))

                        try:
                            loop.call_soon_threadsafe(_schedule)
                        except RuntimeError:
                            # App shutdown may close the dashboard loop while
                            # an already-running agent finishes in its worker.
                            pass

                    def _on_ack(ack: str) -> None:
                        # dispatch berjalan lewat to_thread di bawah, sehingga
                        # callback ini boleh menunggu broadcast benar-benar
                        # terkirim sebelum worker agent mulai.
                        future = asyncio.run_coroutine_threadsafe(
                            self._dashboard.broadcast({
                                "type": "log",
                                "speaker": "jarvis",
                                "text": ack,
                            }),
                            loop,
                        )
                        future.result(timeout=5)

                    def _on_done(result: str) -> None:
                        output = str(result or "Tugas selesai tanpa keluaran.")
                        self.ui.write_log(f"Agent: {output[:600]}")
                        _broadcast_agent(
                            render_success(output, text, limit=12_000))

                    def _on_error(error: str) -> None:
                        detail = str(error)[:400]
                        self.ui.write_log(f"ERR: Tugas berat gagal: {detail}")
                        _broadcast_agent(
                            render_failure(detail, text, limit=12_000))

                    started = await asyncio.to_thread(
                        agent_dispatch.dispatch_async,
                        text,
                        on_ack=_on_ack,
                        on_done=_on_done,
                        on_error=_on_error,
                    )
                    if not started:
                        unavailable = render_failure(
                            unavailable_reason(text), text,
                        )
                        self.ui.write_log(f"ERR: {unavailable}")
                        await self._dashboard.broadcast({
                            "type": "log",
                            "speaker": "jarvis",
                            "text": unavailable,
                        })
                    continue

                # Wait up to 8s for session to become ready after a wake
                for _ in range(80):
                    if self.session:
                        break
                    await asyncio.sleep(0.1)
                if self.session:
                    await self.session.send_client_content(
                        turns={"parts": [{"text": text}]},
                        turn_complete=True,
                    )
                    self.ui.write_log(f"[Web]: {text}")
                else:
                    print(f"[Dashboard] Dropped command (no session): {text}")
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"[Dashboard] Command error: {e}")
                await asyncio.sleep(0.5)

    # ── main loop ───────────────────────────────────────────────────────────

    async def _wait_for_stop(self) -> None:
        """Interrupt the active TaskGroup when the supervisor requests shutdown."""
        while not self._stop_requested.is_set():
            await asyncio.sleep(0.1)
        raise _VoiceStopRequested()

    async def run(self):
        self._loop = asyncio.get_event_loop()
        if getattr(self, "_stop_requested", None) is not None and self._stop_requested.is_set():
            return

        # Start dashboard (optional — needs: pip install fastapi "uvicorn[standard]" cryptography)
        try:
            from dashboard.server import DashboardServer
            self._dashboard = DashboardServer()
            self._dashboard.set_connect_callback(self._on_phone_connected)
            asyncio.create_task(self._dashboard.serve())
            # Runs for the whole lifetime, not just inside an active session
            asyncio.create_task(self._process_dashboard_commands())
        except Exception as e:
            print(f"[Dashboard] Disabled: {e}")
            self._dashboard = None

        from jarvis.integrations import voice_live_lifecycle

        connection = voice_live_lifecycle.ConnectionTracker()
        reconnect_backoff = voice_live_lifecycle.ReconnectBackoff()
        self._voice_reconnect_backoff = reconnect_backoff
        self._conn_backoff = reconnect_backoff.current
        attempt = 0
        while True:
            try:
                attempt += 1
                self._trace("voice.connect_attempt", attempt=attempt)
                print("[JARVIS] Connecting...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                # Fresh client on every reconnect — avoids stale HTTP session state
                client = genai.Client(
                    api_key=_get_api_key(),
                    http_options={"api_version": "v1beta"}
                )

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session          = session
                    self.audio_in_queue   = asyncio.Queue()
                    self.out_queue        = asyncio.Queue(maxsize=200)
                    self._turn_done_event = asyncio.Event()

                    # Reset transient state that must not carry over from a previous session
                    self._pending_vision       = None
                    self._vision_cam_active    = False
                    self._vision_close_pending = False
                    self._vision_busy          = False
                    self._vision_last_time     = 0.0
                    self._interrupted          = False
                    self._awaiting_since       = None
                    self._conn_backoff = reconnect_backoff.connected()

                    state = connection.connected()
                    print("[JARVIS] Connected.")
                    self._sm_to("LISTENING")
                    self.ui.set_state("LISTENING")
                    if state == "initial":
                        self.ui.write_log("SYS: JARVIS online.")
                    elif state == "restored":
                        self.ui.write_log("SYS: Koneksi suara dipulihkan.")
                        self._trace("voice.reconnect_restored", attempt=attempt)

                    if not self._briefing_sent:
                        self._briefing_sent = True
                        try:
                            from jarvis.integrations.relay.service import RelayService
                            relay_svc = RelayService.get()
                            if relay_svc.enabled:
                                recent = relay_svc.recent_events(limit=10)
                                if recent:
                                    greeting_prompt = (
                                        "Sistem baru saja booting. Ini adalah data terbaru yang masuk dari webhook (Relay.app):\n"
                                        + str(recent)
                                        + "\n\nBerikan briefing sapaan lisan (briefing pagi/sistem) yang merangkum email baru, jadwal kalender, statistik YouTube, dan Instagram tersebut secara natural dan profesional."
                                    )
                                    await session.send_client_content(
                                        turns={"parts": [{"text": greeting_prompt}]},
                                        turn_complete=True,
                                    )
                        except Exception as e:
                            print(f"[JARVIS] Failed to fetch boot briefing: {e}")

                    if self._dashboard:
                        await self._dashboard.broadcast({"type": "status", "state": "active"})

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._run_system_monitor())
                    tg.create_task(self._run_proactive_mode())
                    tg.create_task(self._response_watchdog())
                    tg.create_task(self._wait_for_stop())
                    if self._dashboard:
                        tg.create_task(self._relay_phone_audio())

                    # Morning briefing is now handled by jarvis/main.py (Modul 1)

                    #     self._briefing_sent = True
                    #     tg.create_task(self._send_startup_briefing())

            except KeyboardInterrupt:
                raise
            except SystemExit:
                raise
            except BaseException as e:
                if self._stop_requested.is_set():
                    break
                failure = voice_live_lifecycle.classify(e)
                safe = failure.safe_fields()
                print(f"[JARVIS] Error ({failure.leaf_type}, {failure.kind})")
                self._trace("session.error", **safe)
                self._sm_to("RECOVERING")
                connection.failed()

                if failure.auth_confirmed:
                    self.ui.write_log("ERR: API key invalid — please re-enter your key.")
                    self.ui.set_state("SLEEPING")
                    self.ui.prompt_reconfig()
                    ready = await voice_live_lifecycle.wait_until(
                        lambda: bool(getattr(self.ui._win, "_ready", False)),
                        self._stop_requested.is_set,
                    )
                    if not ready:
                        break
                    print("[JARVIS] New API key saved — reconnecting...")
                    self._conn_backoff = reconnect_backoff.healthy()
                    continue

                self._conn_backoff = reconnect_backoff.failed()
                self.ui.write_log(
                    f"SYS: Koneksi suara terputus ({failure.kind}); "
                    f"mencoba lagi dalam {self._conn_backoff}s."
                )
            finally:
                self.session = None

            self.set_speaking(False)
            self.ui.set_state("SLEEPING")
            self._sm_to("IDLE")

            if self._dashboard:
                await self._dashboard.broadcast({"type": "status", "state": "sleeping"})

            if self._stop_requested.is_set():
                break
            delay = self._conn_backoff
            self._trace("voice.reconnect_scheduled", delay_s=delay)
            print(f"[JARVIS] Reconnecting in {delay}s...")
            await asyncio.sleep(delay)

def main():
    # Jalur legacy (menjalankan main.py langsung) tidak didukung — lihat
    # readme. Ia tetap boleh bekerja, jadi UI lamanya diimpor DI SINI,
    # saat benar-benar dipakai, bukan saat modul ini dimuat.
    from ui import JarvisUI
    ui = JarvisUI("face.png")

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()

if __name__ == "__main__":
    main()
