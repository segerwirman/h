"""Offline acceptance tests for deterministic, fail-closed social replies."""
from __future__ import annotations

from jarvis.integrations.comments.base import (
    CommentEvent,
    CommentManager,
    PlatformAdapter,
    PlatformCapabilities,
    ReplyResult,
)
from jarvis.integrations.comments.deterministic_reply import (
    DeterministicReplyPolicy,
    ReplyDisposition,
)


class _Clock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def record(self, **fields) -> None:
        self.events.append(dict(fields))


class _Adapter(PlatformAdapter):
    def __init__(self, name: str, *, manual: bool = False) -> None:
        self.name = name
        self.manual = manual
        self.sent: list[tuple[str, str]] = []

    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(True, True, self.manual, "offline fake")

    def send_reply(self, comment: CommentEvent, text: str) -> ReplyResult:
        self.sent.append((comment.comment_id, text))
        return ReplyResult(True, "sent", reply_id=f"reply-{comment.comment_id}")


def _comment(platform: str, comment_id: str, author_id: str, text: str = "halo"):
    return CommentEvent(
        platform=platform,
        comment_id=comment_id,
        author_id=author_id,
        author_name="Offline User",
        text=text,
        timestamp=1.0,
    )


def test_policy_uses_exact_faq_and_is_deterministic_without_randomness(monkeypatch):
    import random

    monkeypatch.setattr(
        random,
        "random",
        lambda: (_ for _ in ()).throw(AssertionError("random reply selection used")),
    )
    policy = DeterministicReplyPolicy(
        faq={"Jam buka?": "Kami buka pukul 09.00–17.00."},
    )

    exact = policy.classify("  JAM   BUKA?  ", platform="instagram")
    first = policy.classify("terima kasih", platform="instagram", author_id="a-1")
    second = policy.classify("terima kasih", platform="instagram", author_id="a-1")

    assert exact.disposition is ReplyDisposition.AUTO
    assert exact.reply == "Kami buka pukul 09.00–17.00."
    assert exact.reason == "faq_exact"
    assert first == second
    assert first.disposition is ReplyDisposition.AUTO
    assert 0 < len(first.reply) <= 280


def test_policy_sends_sensitive_negative_and_open_ended_text_to_human():
    policy = DeterministicReplyPolicy(
        faq={"berapa nomor kartu?": "jawaban yang tidak boleh lolos"},
    )

    sensitive = policy.classify("berapa nomor kartu?")
    negative = policy.classify("Produk ini buruk dan saya marah")
    open_ended = policy.classify("Menurut kamu bagaimana sebaiknya masalah ini diselesaikan?")
    unsupported = policy.classify("   ")

    assert sensitive.disposition is ReplyDisposition.MANUAL
    assert sensitive.reply == ""
    assert sensitive.reason == "sensitive"
    assert negative.disposition is ReplyDisposition.MANUAL
    assert open_ended.disposition is ReplyDisposition.DRAFT
    assert unsupported.disposition is ReplyDisposition.MANUAL


def test_policy_never_auto_replies_to_bounded_negated_acknowledgments():
    policy = DeterministicReplyPolicy()
    cases = {
        "Saya tidak suka produk ini": "negated_positive",
        "gak suka sama sekali": "negated_positive",
        "I do not love this": "negated_positive",
        "I cannot love this": "negated_positive",
        "I don't love this": "negated_positive",
        "I didn’t love this": "negated_positive",
        "I couldn’t love this": "negated_positive",
        "I won't love this": "negated_positive",
        "I wouldn’t love this": "negated_positive",
        "I haven't loved this": "negated_positive",
        "I haven't really at all loved this": "negated_positive",
        "I do not really at all love this": "negated_positive",
        "This isn't awesome": "negated_positive",
        "Saya tidak suka.": "negated_positive",
        "I never loved this": "negated_positive",
        "no thanks": "negated_thanks",
        "tidak terima kasih": "negated_thanks",
        "I don't love this, thanks": "negated_positive",
        "I do not love this, thanks": "negated_positive",
        "Thanks, but I do not love this": "negated_positive",
    }

    for text, reason in cases.items():
        decision = policy.classify(text, platform="instagram", author_id="a-1")
        assert decision.disposition is not ReplyDisposition.AUTO
        assert decision.reply == ""
        assert decision.reason == reason


def test_policy_matches_only_explicit_non_negated_acknowledgment_tokens():
    policy = DeterministicReplyPolicy()

    controls = {
        "Saya suka.": "positive",
        "Saya suka banget.": "positive",
        "Love it!": "positive",
        "Thanks!": "thanks",
        "Thank you very much!": "thanks",
        "Terima kasih banyak.": "thanks",
    }
    for text, reason in controls.items():
        decision = policy.classify(text, platform="instagram", author_id="a-1")
        assert decision.disposition is ReplyDisposition.AUTO
        assert decision.reason == reason

    unsupported = (
        "What a lovely day",
        "Thanks, it",
        "Thanks this",
        "Thanks so",
        "Thanks very",
        "Love produk",
        "Love saya",
        "Saya love this",
    )
    for text in unsupported:
        decision = policy.classify(text, platform="instagram", author_id="a-1")
        assert decision.disposition is ReplyDisposition.DRAFT
        assert decision.reply == ""


def test_policy_never_auto_replies_to_acknowledgments_mixed_with_requests():
    policy = DeterministicReplyPolicy()
    cases = (
        "Thanks?",
        "Love it?",
        "Thanks?!",
        "Thanks, but where is my refund?",
        "Thanks, can you explain what happened?",
        "I love it, but how do I return it?",
        "Thanks, please explain what happened.",
        "I love it, but please help with a return.",
        "Awesome, but could you help me?",
        "Thanks, my order is missing.",
        "Thanks, refund status.",
        "Love it, return instructions.",
        "Thanks, send details.",
        "Love it, share details.",
        "Thanks, contact me.",
        "Thanks, check my account.",
        "Thanks, cancel it.",
        "Awesome, fix it.",
        "Terima kasih, hubungi saya.",
        "Thanks, archive it.",
        "Thanks, delete my account.",
        "Thanks, forward the receipt.",
        "Love it, replace mine.",
        "Awesome, close the ticket.",
        "Terima kasih, hapus akun saya.",
        "Terima kasih, tolong periksa pesanan saya.",
    )

    for text in cases:
        decision = policy.classify(text, platform="instagram", author_id="a-1")
        assert decision.disposition is ReplyDisposition.DRAFT
        assert decision.reply == ""
        assert decision.reason == "mixed_request"


def test_platform_manual_approval_forces_draft_even_when_auto_is_active():
    clock = _Clock()
    audit = _Audit()
    adapter = _Adapter("instagram", manual=True)
    manager = CommentManager(
        [adapter],
        clock=clock,
        audit=audit,
        activation_ttl_s=30,
        author_cooldown_s=0,
    )
    assert manager.enable_auto_reply("instagram") is True
    comment = _comment("instagram", "c-1", "u-1")

    automatic = manager.reply(comment, "Halo juga!")
    confirmed = manager.reply(comment, "Halo juga!", confirmed=True)

    assert automatic.ok is False
    assert "manual approval" in automatic.detail
    assert confirmed.ok is True
    assert adapter.sent == [("c-1", "Halo juga!")]
    assert any(event.get("event") == "reply_manual_required" for event in audit.events)


def test_auto_activation_expires_once_and_reverts_to_draft():
    clock = _Clock()
    audit = _Audit()
    adapter = _Adapter("facebook")
    manager = CommentManager(
        [adapter],
        clock=clock,
        audit=audit,
        activation_ttl_s=10,
        author_cooldown_s=0,
    )
    assert manager.enable_auto_reply("facebook") is True
    assert manager.reply(_comment("facebook", "c-1", "u-1"), "Halo!").ok is True

    clock.value += 11
    expired = manager.reply(_comment("facebook", "c-2", "u-2"), "Halo!")
    manager.reply_mode("facebook")

    assert expired.ok is False
    assert "draft" in expired.detail
    assert adapter.sent == [("c-1", "Halo!")]
    expiry_events = [e for e in audit.events if e.get("event") == "auto_reply_expired"]
    assert len(expiry_events) == 1


def test_global_and_platform_kill_switches_stop_sends_immediately():
    adapter = _Adapter("youtube")
    audit = _Audit()
    manager = CommentManager(
        [adapter],
        audit=audit,
        activation_ttl_s=30,
        author_cooldown_s=0,
    )
    manager.enable_auto_reply("youtube")

    manager.set_global_kill_switch(True)
    global_block = manager.reply(
        _comment("youtube", "c-1", "u-1"),
        "Halo!",
        confirmed=True,
    )
    manager.set_global_kill_switch(False)
    manager.set_platform_kill_switch("youtube", True)
    platform_block = manager.reply(_comment("youtube", "c-2", "u-2"), "Halo!")

    assert global_block.ok is False
    assert platform_block.ok is False
    assert "kill switch" in global_block.detail
    assert "kill switch" in platform_block.detail
    assert adapter.sent == []


def test_rate_buckets_are_per_platform_and_author_cooldown_is_scoped():
    clock = _Clock()
    facebook = _Adapter("facebook")
    instagram = _Adapter("instagram")
    manager = CommentManager(
        [facebook, instagram],
        clock=clock,
        activation_ttl_s=60,
        max_replies_per_min=1,
        author_cooldown_s=30,
    )
    manager.enable_auto_reply("facebook")
    manager.enable_auto_reply("instagram")

    fb_first = manager.reply(_comment("facebook", "f-1", "same-author"), "Halo!")
    ig_first = manager.reply(_comment("instagram", "i-1", "same-author"), "Halo!")
    fb_same_author = manager.reply(
        _comment("facebook", "f-2", "same-author"),
        "Halo lagi!",
    )

    assert fb_first.ok is True
    assert ig_first.ok is True, "bucket/cooldown platform lain tidak boleh ikut habis"
    assert fb_same_author.ok is False
    assert "cooldown" in fb_same_author.detail
    assert facebook.sent == [("f-1", "Halo!")]
    assert instagram.sent == [("i-1", "Halo!")]
