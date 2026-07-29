"""Named capability groups and safe defaults per Jarvis ingress surface."""
from __future__ import annotations

_TOOLSETS = {
    "voice-safe": frozenset({
        "session_search", "memory_search", "web_search", "web_extract",
        "browser_snapshot", "computer_screenshot", "list_running_apps",
    }),
    "desktop-control": frozenset({
        "open_app", "close_app", "list_running_apps",
        "camera_open", "camera_close", "vision_analyze",
        "computer_click", "computer_drag", "computer_key",
        "computer_screenshot", "computer_observe", "computer_scroll",
        "computer_type",
        "browser_navigate", "browser_snapshot", "browser_click",
        "browser_type", "browser_scroll", "browser_press", "browser_back",
        "browser_tabs", "browser_new_tab", "browser_switch_tab",
        "browser_close_tab", "browser_media",
    }),
    "research": frozenset({"web_search", "web_extract", "session_search"}),
    "developer": frozenset({
        "terminal", "execute_code",
        "file_read", "file_write", "file_patch", "file_search", "file_list",
        "process_list", "process_spawn", "process_kill",
        "prompt_list", "prompt_read", "prompt_save",
        "mcp_list", "mcp_connect", "mcp_call",
    }),
    "messaging": frozenset({
        "whatsapp_open", "whatsapp_status", "whatsapp_list_contacts",
        "whatsapp_send_message", "whatsapp_call", "whatsapp_answer",
        "whatsapp_hangup", "whatsapp_audio_devices",
    }),
    "automation": frozenset({
        "cron_create", "cron_list", "cron_update", "cron_delete",
        "cron_pause", "cron_resume", "cron_run",
        "todo_read", "todo_write",
        "task_start", "task_status", "task_result", "task_cancel",
    }),
    "admin": frozenset({"provider_settings", "gateway_control"}),
}

_SURFACE_TOOLSETS = {
    "voice": frozenset({"voice-safe"}),
    "telegram": frozenset({"messaging"}),
    "desktop": frozenset({
        "voice-safe", "desktop-control", "research", "developer",
        "messaging", "automation", "admin",
    }),
    "agent": frozenset(_TOOLSETS),
}


def allowed_for_surface(surface: str) -> frozenset[str]:
    return _SURFACE_TOOLSETS.get(str(surface or "").strip().lower(), frozenset())


def tool_allowed(tool_name: str, surface: str) -> bool:
    return any(str(tool_name) in _TOOLSETS[toolset]
               for toolset in allowed_for_surface(surface))
