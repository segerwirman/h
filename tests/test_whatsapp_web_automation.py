"""WhatsApp Web automation safety and routing contracts."""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def contact_file(tmp_path, monkeypatch):
    from jarvis.integrations import whatsapp_web

    path = tmp_path / "contacts.json"
    path.write_text(
        json.dumps(
            {
                "contacts": [
                    {
                        "name": "Ibu",
                        "phone": "628123456789",
                        "allowed": True,
                    },
                    {
                        "name": "Belum Diizinkan",
                        "phone": "628987654321",
                        "allowed": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(whatsapp_web, "_contacts_path", lambda: path)
    return path


def test_contact_resolution_is_exact_and_allowlisted(contact_file):
    from jarvis.integrations.whatsapp_web import resolve_contact

    resolved = resolve_contact("ibu")
    assert resolved.name == "Ibu"
    assert resolved.phone == "628123456789"


def test_contact_resolution_tolerates_unique_stt_error(contact_file, monkeypatch):
    from jarvis.integrations import whatsapp_web

    real_get = whatsapp_web.config.get
    monkeypatch.setattr(
        whatsapp_web.config,
        "get",
        lambda path, default=None: (
            0.68
            if path == "whatsapp_web.contact_fuzzy_threshold"
            else real_get(path, default)
        ),
    )
    assert whatsapp_web.resolve_contact("ibuu").name == "Ibu"


def test_contact_resolution_rejects_unapproved_contact(contact_file):
    from jarvis.integrations.whatsapp_web import (
        WhatsAppError,
        resolve_contact,
    )

    with pytest.raises(WhatsAppError, match="belum diizinkan"):
        resolve_contact("Belum Diizinkan")


def test_direct_number_is_default_deny(contact_file, monkeypatch):
    from jarvis.integrations import whatsapp_web

    real_get = whatsapp_web.config.get
    monkeypatch.setattr(
        whatsapp_web.config,
        "get",
        lambda path, default=None: (
            False
            if path == "whatsapp_web.allow_direct_numbers"
            else real_get(path, default)
        ),
    )
    with pytest.raises(whatsapp_web.WhatsAppError, match="allowlist"):
        whatsapp_web.resolve_contact("628111111111")


def test_tools_require_confirmation_for_external_actions():
    from jarvis.agent.tools.whatsapp_web import (
        WhatsAppAnswer,
        WhatsAppCall,
        WhatsAppHangup,
        WhatsAppSendMessage,
    )

    assert WhatsAppCall().needs_confirmation(contact="Ibu")
    assert WhatsAppAnswer().needs_confirmation()
    assert WhatsAppSendMessage().needs_confirmation(
        contact="Ibu", message="Halo"
    )
    assert WhatsAppHangup().needs_confirmation() is False


def test_whatsapp_tool_shortlist_is_bounded(monkeypatch):
    from jarvis.agent import tool_selection

    monkeypatch.setattr(tool_selection.config, "get", lambda _p, d=None: d)
    WhatsAppTool = type(
        "WhatsAppTool",
        (),
        {"__module__": "jarvis.agent.tools.whatsapp_web"},
    )
    BrowserTool = type(
        "BrowserTool",
        (),
        {"__module__": "jarvis.agent.tools.browser"},
    )
    tools = {
        "whatsapp_call": WhatsAppTool(),
        "whatsapp_hangup": WhatsAppTool(),
        "browser_navigate": BrowserTool(),
    }

    selected = tool_selection.select_tool_names(
        "telepon Ibu lewat WhatsApp", tools
    )

    assert selected == ["whatsapp_call", "whatsapp_hangup"]


def test_plain_phone_request_uses_only_allowlisted_whatsapp_tools(monkeypatch):
    from jarvis.agent import tool_selection

    monkeypatch.setattr(tool_selection.config, "get", lambda _p, d=None: d)
    WhatsAppTool = type(
        "WhatsAppTool",
        (),
        {"__module__": "jarvis.agent.tools.whatsapp_web"},
    )
    tools = {"whatsapp_call": WhatsAppTool()}

    assert tool_selection.select_tool_names(
        "telepon dokter", tools
    ) == ["whatsapp_call"]


def test_hermes_config_can_no_longer_reactivate_runtime(monkeypatch):
    from jarvis.integrations.hermes import bridge

    monkeypatch.setattr(bridge.config, "get", lambda *_args: True)
    assert bridge.is_enabled() is False
