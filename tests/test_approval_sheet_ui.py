"""WA2-lanjutan RED — approval sheet UI (offscreen).

Sheet approval lokal: menampilkan metadata proposal (facade_name/status/
proposal_id), tombol Approve/Reject → signal; TANPA menerima args/secret.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_APP_REF = None


def _app():
    global _APP_REF
    if _APP_REF is None:
        from PyQt6.QtWidgets import QApplication

        _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


def _sheet():
    _app()
    from jarvis.ui.approval_sheet import ApprovalSheet

    return ApprovalSheet()


def test_sheet_starts_empty():
    sheet = _sheet()
    assert sheet.is_empty() is True


def test_sheet_shows_proposal_metadata_only():
    sheet = _sheet()
    sheet.set_proposal({"proposal_id": 7, "facade_name": "check_order_status",
                        "status": "awaiting_approval"})
    assert sheet.is_empty() is False
    assert sheet.facade_name() == "check_order_status"
    assert sheet.proposal_id() == 7
    # Sheet TIDAK menyimpan args/secret
    assert sheet.raw_payload() is None


def test_approve_button_emits_signal_with_proposal_id():
    _app()
    from jarvis.ui.approval_sheet import ApprovalSheet

    sheet = ApprovalSheet()
    sheet.set_proposal({"proposal_id": 42, "facade_name": "book_reservation",
                        "status": "awaiting_approval"})
    received = []
    sheet.approved.connect(lambda pid: received.append(pid))
    sheet._approve_button.click()
    assert received == [42]


def test_reject_button_emits_signal_with_proposal_id():
    _app()
    from jarvis.ui.approval_sheet import ApprovalSheet

    sheet = ApprovalSheet()
    sheet.set_proposal({"proposal_id": 42, "facade_name": "book_reservation",
                        "status": "awaiting_approval"})
    received = []
    sheet.rejected.connect(lambda pid: received.append(pid))
    sheet._reject_button.click()
    assert received == [42]


def test_clear_empties_sheet():
    sheet = _sheet()
    sheet.set_proposal({"proposal_id": 1, "facade_name": "start_countdown",
                        "status": "awaiting_approval"})
    sheet.clear()
    assert sheet.is_empty() is True
