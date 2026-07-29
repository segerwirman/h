import json
import sys
from pathlib import Path

from jarvis.core import secrets_store

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR    = get_base_dir()
CONFIG_DIR  = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"

def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def config_exists() -> bool:
    return bool(secrets_store.get("jarvis/llm/gemini"))

def save_api_keys(gemini_api_key: str) -> None:
    if not secrets_store.set("jarvis/llm/gemini", gemini_api_key.strip()):
        raise RuntimeError("Backend secret terenkripsi tidak tersedia")

def load_api_keys() -> dict:
    data: dict = {}
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Failed to load api_keys.json: {e}")
    data.pop("gemini_api_key", None)
    key = secrets_store.get("jarvis/llm/gemini")
    if key:
        data["gemini_api_key"] = key
    return data

def get_gemini_key() -> str | None:
    return secrets_store.get("jarvis/llm/gemini")

def is_configured() -> bool:
    key = get_gemini_key()
    return bool(key and len(key) > 15)
