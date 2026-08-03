"""Phase WA8 RED — customer-service case manager.

Typed cases (fixed set), field allowlist, disclosure policy per type,
stop/escalation rules; TIDAK ada free-form mission yang memperluas
authority.
"""
from __future__ import annotations


def test_open_requires_known_case_type():
    from jarvis.core.service_case import ServiceCase

    assert ServiceCase().open("free_form_mission", "x") is False
    assert ServiceCase().open("warranty", "x") is False     # belum didukung
    assert ServiceCase().open("service_hours", None) is True
    assert ServiceCase().open("appointment", None) is True
    assert ServiceCase().open("order_status", "ORD-123456") is True


def test_order_status_requires_non_secret_reference():
    from jarvis.core.service_case import ServiceCase

    case = ServiceCase()
    assert case.open("order_status", None) is False        # wajib reference
    assert case.open("order_status", "") is False
    assert case.open("order_status", "password123") is False   # secret marker
    assert case.open("order_status", "4111111111111111") is False  # digit run
    assert case.open("order_status", "ORD-123456") is True


def test_fields_are_allowlisted():
    from jarvis.core.service_case import ServiceCase

    case = ServiceCase()
    case.open("appointment", None)
    assert case.set_note("catatan singkat") is True
    assert case.set_note("x" * 301) is False             # over panjang
    assert case.set_note("berisi password admin") is False  # secret guard


def test_disclosure_policy_limits_what_can_be_disclosed():
    from jarvis.core.service_case import ServiceCase

    case = ServiceCase()
    case.open("service_hours", None)
    assert case.disclose("hours") is True
    assert case.disclose("appointment_availability") is False  # di luar policy
    assert case.disclose("order_status_update") is False
    assert case.disclose("payment_details") is False     # tidak pernah

    order = ServiceCase()
    order.open("order_status", "ORD-123456")
    assert order.disclose("order_status_update") is True
    assert order.disclose("hours") is False


def test_secret_or_payment_touch_escalates_and_stops():
    from jarvis.core.service_case import ServiceCase

    case = ServiceCase()
    case.open("order_status", "ORD-123456")
    # Menyentuh payment/secret → escalate dengan reason fixed + stop
    assert case.escalate_if_needed("tolong cek pembayaran kartu saya") is True
    assert case.status() == "escalated"
    assert case.disclose("order_status_update") is False  # stop: tidak disclose
    assert case.close() is False                          # sudah escalated


def test_escalation_uses_fixed_reasons():
    from jarvis.core.service_case import ServiceCase

    case = ServiceCase()
    case.open("service_hours", None)
    assert case.escalate_if_needed("jam buka hari ini?") is False  # aman
    assert case.status() == "open"
    assert case.escalate_if_needed("OTP saya 123456") is True
    assert case.reason() == "service_case_secret_touch"


def test_close_transitions_and_is_one_shot():
    from jarvis.core.service_case import ServiceCase

    case = ServiceCase()
    case.open("appointment", None)
    assert case.close() is True
    assert case.status() == "closed"
    assert case.close() is False


def test_result_is_metadata_only():
    from jarvis.core.service_case import ServiceCase

    case = ServiceCase()
    case.open("order_status", "ORD-123456")
    case.set_note("menunggu konfirmasi")
    result = case.result()
    assert result["case_type"] == "order_status"
    assert result["reference"] == "ORD-123456"
    assert result["status"] == "open"
    for forbidden in ("payment", "password", "raw", "path"):
        assert forbidden not in result, forbidden
