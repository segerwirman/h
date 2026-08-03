"""Phase 15B desktop-local metadata-only proposal sheet."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _queue():
    from jarvis.agent.remote_proposals import RemoteProposalQueue
    queue = RemoteProposalQueue(now=lambda: 10.0)
    result = queue.request(actor_id="telegram:42", session_id="chat:42", action="focus_mode_enable")
    return queue, result["proposal_id"]


def test_remote_proposal_sheet_renders_safe_summary_and_starts_hidden():
    _app()
    from jarvis.ui.remote_proposal_sheet import RemoteProposalSheet

    queue, rid = _queue()
    sheet = RemoteProposalSheet(queue)
    assert sheet.isHidden() is True
    assert sheet.present(rid, actor_id="telegram:42", session_id="chat:42") is True
    text = sheet.summary_text()
    assert "Aktifkan Focus Mode" in text
    for forbidden in ("telegram:42", "chat:42", "secret", "coordinate", "screenshot", "uia"):
        assert forbidden not in text.lower()


def test_remote_proposal_sheet_renders_safe_media_label_without_page_data():
    _app()
    from jarvis.agent.remote_proposals import RemoteProposalQueue
    from jarvis.ui.remote_proposal_sheet import RemoteProposalSheet

    queue = RemoteProposalQueue(now=lambda: 10.0)
    rid = queue.request(actor_id="telegram:42", session_id="chat:42", action="media_pause")["proposal_id"]
    sheet = RemoteProposalSheet(queue)
    assert sheet.present(rid, actor_id="telegram:42", session_id="chat:42") is True
    assert "Jeda media aktif" in sheet.summary_text()
    for forbidden in ("title", "url", "youtube", "telegram:42", "chat:42"):
        assert forbidden not in sheet.summary_text().lower()


def test_sheet_cancel_is_owned_locally_and_has_no_remote_callback():
    _app()
    from jarvis.ui.remote_proposal_sheet import RemoteProposalSheet

    queue, rid = _queue()
    sheet = RemoteProposalSheet(queue)
    assert sheet.present(rid, actor_id="telegram:42", session_id="chat:42") is True
    sheet._cancel()
    assert queue.get(rid, actor_id="telegram:42", session_id="chat:42").status == "cancelled"
    assert sheet.isHidden() is True


def test_sheet_approve_uses_injected_local_executor_once():
    _app()
    from jarvis.ui.remote_proposal_sheet import RemoteProposalSheet

    queue, rid = _queue()
    calls = []
    sheet = RemoteProposalSheet(queue, executor=lambda action: calls.append(action) or True)
    sheet.present(rid, actor_id="telegram:42", session_id="chat:42")
    sheet._approve()
    assert calls == ["focus_mode_enable"]
    assert queue.get(rid, actor_id="telegram:42", session_id="chat:42").status == "approved"


def test_sheet_source_has_no_transport_or_secret_surface():
    from jarvis.ui import remote_proposal_sheet
    source = open(remote_proposal_sheet.__file__, encoding="utf-8").read().lower()
    for forbidden in ("send_from_anywhere", "telegram", "requests", "webbrowser", "subprocess", "token", "secret", "screenshot", "coordinate"):
        assert forbidden not in source
