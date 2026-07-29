"""Unit tests for the bounded Phase 2 ACK/report lifecycle helper."""
from __future__ import annotations

from jarvis.agent import interaction, interactive_dispatch


def test_language_aware_ack_uses_persona_without_mixing():
    assert interaction.detect_language("tolong riset dan buat laporan") == "id"
    assert interaction.detect_language("please research and create a report") == "en"
    assert interaction.persona_address().casefold() == "sir"

    ack_id = interaction.render_ack(
        "tolong riset dan buat laporan",
        legacy_ack="",
        address="sir",
        chooser=lambda choices: choices[0],
    )
    ack_en = interaction.render_ack(
        "please research and create a report",
        legacy_ack="",
        address="sir",
        chooser=lambda choices: choices[0],
    )

    assert "sir" in ack_id.casefold()
    assert any(
        marker in ack_id.casefold() for marker in ("baik", "siap", "segera")
    )
    assert "right away" not in ack_id.casefold()
    assert "sir" in ack_en.casefold()
    assert "right away" in ack_en.casefold()
    assert "baik" not in ack_en.casefold()


def test_ack_templates_vary_and_legacy_phrase_remains_effective(
    monkeypatch, tmp_path
):
    persona = tmp_path / "prompt.txt"
    persona.write_text(
        'ADDRESS: When speaking, always say "commander".\n',
        encoding="utf-8",
    )
    real_get = interaction.config.get

    def fake_get(path, default=None):
        values = {
            "agent.persona_file": str(persona),
            "agent.ack_phrase": "Baik khusus.",
            "agent.interaction.ack_templates.id": [
                "Template pertama, {address}.",
                "Template kedua, {address}.",
            ],
        }
        return values.get(path, real_get(path, default))

    monkeypatch.setattr(interaction.config, "get", fake_get)
    monkeypatch.setattr(
        interaction.config, "resolve_path", lambda path: persona
    )

    legacy = interaction.render_ack(
        "tolong kerjakan ini", chooser=lambda choices: choices[0]
    )
    variant = interaction.render_ack(
        "tolong kerjakan ini", chooser=lambda choices: choices[-1]
    )

    assert legacy == "Baik khusus, commander."
    assert variant == "Template kedua, commander."
    assert legacy != variant


def test_success_report_is_concrete_sanitized_and_bounded():
    report = interaction.render_success(
        "**Video terbaru Deddy Corbuzier**\n"
        "sudah diputar dari channel resmi.",
        "buka dan putar video terbaru",
        address="sir",
        limit=90,
    )

    assert "Deddy Corbuzier" in report
    assert "channel resmi" in report
    assert "**" not in report
    assert "\n" not in report
    assert "sir" in report.casefold()
    assert len(report) <= 90


def test_empty_or_generic_success_never_claims_a_verified_result():
    empty_id = interaction.render_success(
        "", "tolong buat laporan", address="sir"
    )
    generic_en = interaction.render_success(
        "Done.", "please build the report", address="sir"
    )

    assert "tanpa hasil yang dapat diverifikasi" in empty_id.casefold()
    assert "without a verifiable result" in generic_en.casefold()


def test_failure_report_is_honest_and_language_aware():
    report_id = interaction.render_failure(
        "akses file ditolak", "tolong perbaiki file", address="sir"
    )
    report_en = interaction.render_failure(
        "permission denied", "please fix this file", address="sir"
    )

    assert report_id.startswith("Maaf, sir.")
    assert "akses file ditolak" in report_id
    assert report_en.startswith("Sorry, sir.")
    assert "permission denied" in report_en
    assert "Maaf" not in report_en


def test_wrapper_delegates_ack_before_work_and_reports_success(
    monkeypatch
):
    events = []
    callbacks = {}

    def primitive(task, **kwargs):
        events.append(("primitive", task))
        callbacks.update(kwargs)
        kwargs["on_ack"]("Baik, sedang saya kerjakan.")
        events.append(("work", task))
        kwargs["on_done"]("Video terbaru sudah diputar.")
        return True

    monkeypatch.setattr(
        interactive_dispatch.dispatch, "dispatch_async", primitive
    )

    started = interactive_dispatch.start(
        "buka dan putar video terbaru",
        on_ack=lambda raw, report: events.append(("ack", raw, report)),
        on_done=lambda raw, report: events.append(("done", raw, report)),
        on_error=lambda raw, report: events.append(("error", raw, report)),
        adapter="adapter",
        timeout_s=12,
        allowed_tools=["browser_navigate"],
        address="sir",
        chooser=lambda choices: choices[0],
    )

    assert started is True
    assert [event[0] for event in events] == [
        "primitive", "ack", "work", "done"
    ]
    assert callbacks["adapter"] == "adapter"
    assert callbacks["timeout_s"] == 12
    assert callbacks["allowed_tools"] == ["browser_navigate"]
    assert events[-1][1] == "Video terbaru sudah diputar."
    assert "Video terbaru sudah diputar" in events[-1][2]


def test_wrapper_emits_only_one_terminal_failure(monkeypatch):
    events = []

    def primitive(_task, **kwargs):
        kwargs["on_ack"]("Right away.")
        kwargs["on_error"]("permission denied")
        kwargs["on_error"]("second failure")
        kwargs["on_done"]("must be ignored")
        return True

    monkeypatch.setattr(
        interactive_dispatch.dispatch, "dispatch_async", primitive
    )

    started = interactive_dispatch.start(
        "please fix this file",
        on_ack=lambda raw, report: events.append(("ack", raw, report)),
        on_done=lambda raw, report: events.append(("done", raw, report)),
        on_error=lambda raw, report: events.append(("error", raw, report)),
        address="sir",
    )

    assert started is True
    assert [event[0] for event in events] == ["ack", "error"]
    assert events[1][1] == "permission denied"
    assert "permission denied" in events[1][2]


def test_wrapper_unavailable_has_no_false_ack_and_one_honest_report(
    monkeypatch
):
    events = []
    monkeypatch.setattr(
        interactive_dispatch.dispatch,
        "dispatch_async",
        lambda _task, **_kwargs: False,
    )

    started = interactive_dispatch.start(
        "tolong analisis repo ini",
        on_ack=lambda raw, report: events.append(("ack", raw, report)),
        on_done=lambda raw, report: events.append(("done", raw, report)),
        on_error=lambda raw, report: events.append(("error", raw, report)),
        address="sir",
    )

    assert started is False
    assert [event[0] for event in events] == ["error"]
    assert "belum siap" in events[0][1].casefold()
    assert "gagal" in events[0][2].casefold()


def test_external_callbacks_and_primitive_errors_never_escape(monkeypatch):
    def callback_raises(_raw, _report):
        raise RuntimeError("delivery failed")

    def successful_primitive(_task, **kwargs):
        kwargs["on_ack"]("Baik.")
        kwargs["on_done"]("Laporan tersimpan.")
        return True

    monkeypatch.setattr(
        interactive_dispatch.dispatch,
        "dispatch_async",
        successful_primitive,
    )
    assert interactive_dispatch.start(
        "tolong buat laporan",
        on_ack=callback_raises,
        on_done=callback_raises,
        on_error=callback_raises,
        address="sir",
    ) is True

    monkeypatch.setattr(
        interactive_dispatch.dispatch,
        "dispatch_async",
        lambda _task, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("primitive crashed")
        ),
    )
    errors = []
    assert interactive_dispatch.start(
        "tolong buat laporan",
        on_error=lambda raw, report: errors.append((raw, report)),
        address="sir",
    ) is False
    assert len(errors) == 1
    assert "primitive crashed" in errors[0][0]
