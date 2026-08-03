"""28-lanjutan RED — actor binding.

Paired remote actor identity binding ke proposal; larangan eksplisit
remote menerima UIA refs/transcript/audio/path. Murni lokal; tanpa
provider/network/file.
"""
from __future__ import annotations

_FORBIDDEN = {
    "uia_ref", "uia_reference", "transcript", "audio", "path", "screenshot",
    "coordinate", "raw_html", "cookie", "header", "ocr",
}


def _binding():
    import jarvis.core.actor_binding as ab

    return ab, ab.ActorBinding()


def test_actor_register_valid_and_duplicate_rejected():
    ab, binding = _binding()
    assert binding.register("actor-001", "Eric Bot") is True
    assert binding.register("actor-001", "Eric Bot Lagi") is False  # duplicate
    assert binding.register("", "X") is False
    assert binding.register("actor-002", "") is False
    assert binding.register("actor-003", "password bot") is False  # secret
    assert binding.register("a" * 65, "X") is False               # terlalu panjang


def test_bind_proposal_one_shot_and_known_actor_only():
    ab, binding = _binding()
    binding.register("actor-001", "Eric Bot")
    assert binding.bind_proposal("prop-100", "actor-001") is True
    assert binding.bind_proposal("prop-100", "actor-001") is False  # one-shot
    assert binding.bind_proposal("prop-101", "actor-999") is False  # tak dikenal
    assert binding.bind_proposal("prop-101", "actor-001") is True
    assert binding.bound_actor("prop-100") == "actor-001"
    assert binding.bound_actor("prop-999") is None


def test_payload_guard_forbids_sensitive_types():
    ab, binding = _binding()
    blocked = [
        {"uia_ref": "uia-123"},
        {"transcript": "percakapan"},
        {"audio": "clip.wav"},
        {"path": "C:/Users/me/secret"},
        {"screenshot": True},
        {"coordinate": [10, 20]},
        {"raw_html": "<html>"},
        {"cookie": "session=abc"},
        {"header": "Authorization: Bearer x"},
        {"ocr": "hasil scan"},
    ]
    for payload in blocked:
        result = binding.check_payload(payload)
        assert result["ok"] is False, payload
        assert result["reason"] == "actor_payload_forbidden", payload
    # Metadata aman
    assert binding.check_payload(
        {"facade_name": "TIMER", "status": "awaiting_approval"})["ok"] is True
    assert binding.check_payload({})["ok"] is True


def test_approval_side_verifies_bound_actor():
    ab, binding = _binding()
    binding.register("actor-001", "Eric Bot")
    binding.bind_proposal("prop-100", "actor-001")
    # Hanya actor terikat yang valid untuk proposal itu
    assert binding.actor_owns("prop-100", "actor-001") is True
    assert binding.actor_owns("prop-100", "actor-002") is False
    assert binding.actor_owns("prop-999", "actor-001") is False


def test_known_actors_metadata_only():
    ab, binding = _binding()
    binding.register("actor-001", "Eric Bot")
    text = str(binding.known_actors())
    assert "actor-001" in text
    for forbidden in ("password", "token=", "payload"):
        assert forbidden not in text, forbidden


def test_no_live_authority_via_static_contract():
    from pathlib import Path

    source = Path("jarvis/core/actor_binding.py").read_text(encoding="utf-8")
    for forbidden in ("import whatsapp", "requests", "socket", "http",
                      "subprocess", "selenium", "playwright", "write_bytes",
                      "open("):
        assert forbidden not in source, forbidden
