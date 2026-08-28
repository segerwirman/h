"""Task 8 — offscreen desktop-local communication authorization sheet."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_APP_REF = None


class _Authorizer:
    def __init__(self, result=None) -> None:
        self.result = result or SimpleNamespace(
            ok=True,
            status="authorized",
            grant_id="G-opaque",
        )
        self.calls = []

    def authorize(self, value, **scope):
        self.calls.append((value, scope))
        return self.result


def _app():
    global _APP_REF
    if _APP_REF is None:
        from PyQt6.QtWidgets import QApplication
        _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


def _scope():
    from jarvis.ui.communication_auth_sheet import AuthorizationScope
    return AuthorizationScope(
        task_id="T-real",
        trace_id="trace-123",
        capability_ids=frozenset({"web.web_search"}),
        ttl_s=45,
        uses=1,
    )


def test_sheet_field_is_password_and_always_empty_on_present():
    _app()
    from PyQt6.QtWidgets import QLineEdit
    from jarvis.ui.communication_auth_sheet import CommunicationAuthorizationSheet

    sheet = CommunicationAuthorizationSheet(authorizer=_Authorizer())
    sheet._entry.setText("stale-local-value")

    assert sheet.present(_scope(), 900, 700) is True
    assert sheet._entry.text() == ""
    assert sheet._entry.echoMode() is QLineEdit.EchoMode.Password

    sheet.hide()


def test_success_clears_before_authorizer_returns_and_emits_no_raw_text():
    _app()
    from jarvis.ui.communication_auth_sheet import CommunicationAuthorizationSheet

    observations = []

    class Authorizer(_Authorizer):
        def authorize(self, value, **scope):
            observations.append(sheet._entry.text())
            return super().authorize(value, **scope)

    authorizer = Authorizer()
    sheet = CommunicationAuthorizationSheet(authorizer=authorizer)
    emitted = []
    sheet.resolved.connect(lambda *args: emitted.append(args))
    sheet.present(_scope(), 900, 700)
    raw = "local-only-value"
    sheet._entry.setText(raw)

    sheet._authorize_button.click()

    assert observations == [""]
    assert sheet._entry.text() == ""
    assert authorizer.calls[0][0] == raw
    assert emitted == [(True, "G-opaque")]
    assert raw not in repr(emitted)
    assert sheet.isHidden() is True


def test_failure_clears_and_emits_fixed_status_only():
    _app()
    from jarvis.ui.communication_auth_sheet import CommunicationAuthorizationSheet

    authorizer = _Authorizer(SimpleNamespace(
        ok=False,
        status="denied",
        grant_id="",
    ))
    sheet = CommunicationAuthorizationSheet(authorizer=authorizer)
    emitted = []
    sheet.resolved.connect(lambda *args: emitted.append(args))
    sheet.present(_scope(), 900, 700)
    raw = "wrong-local-value"
    sheet._entry.setText(raw)

    sheet._authorize_button.click()

    assert sheet._entry.text() == ""
    assert emitted == [(False, "")]
    assert raw not in sheet._status.text()
    assert raw not in repr(emitted)
    assert sheet.isVisible() is True
    sheet.hide()


def test_cancel_and_close_clear_entry_and_scope():
    _app()
    from jarvis.ui.communication_auth_sheet import CommunicationAuthorizationSheet

    sheet = CommunicationAuthorizationSheet(authorizer=_Authorizer())
    emitted = []
    sheet.resolved.connect(lambda *args: emitted.append(args))
    sheet.present(_scope(), 900, 700)
    sheet._entry.setText("local-only-value")

    sheet._cancel_button.click()

    assert sheet._entry.text() == ""
    assert sheet._scope is None
    assert emitted == [(False, "")]

    sheet.present(_scope(), 900, 700)
    sheet._entry.setText("local-only-value")
    sheet.close()
    assert sheet._entry.text() == ""
    assert sheet._scope is None


def test_sheet_rejects_invalid_scope_without_opening():
    _app()
    from jarvis.ui.communication_auth_sheet import (
        AuthorizationScope,
        CommunicationAuthorizationSheet,
    )

    sheet = CommunicationAuthorizationSheet(authorizer=_Authorizer())
    invalid = AuthorizationScope(
        task_id="",
        trace_id="trace-123",
        capability_ids=frozenset({"web.web_search"}),
        ttl_s=45,
    )

    assert sheet.present(invalid, 900, 700) is False
    assert sheet._scope is None
    assert sheet.isHidden() is True
