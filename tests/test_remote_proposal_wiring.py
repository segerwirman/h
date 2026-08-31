"""15B metadata-only Telegram-to-desktop wiring contract."""
from __future__ import annotations

from pathlib import Path


def test_telegram_ingress_stages_exact_phrase_and_returns_local_approval_notice():
    source = Path("jarvis/agent/adapters/telegram.py").read_text(encoding="utf-8")
    assert "remote_proposal_ingress.stage_text(" in source
    assert 'BUS.publish("remote_proposal.pending"' in source
    assert "Permintaan menunggu persetujuan desktop lokal." in source
    # Batas blok dipotong pada NAMA KODE, bukan kalimat komentar. Bentuk lama
    # memakai "# jawaban untuk pertanyaan clarify"; b0257ed (2026-08-27)
    # mengubah komentar itu menjadi "# Jawaban teks bebas untuk pertanyaan
    # clarify tetap terpisah dari", sehingga index() melempar ValueError —
    # bukan karena kontrak dilanggar, melainkan karena penanda teksnya hilang.
    # Diukur 2026-08-31: ketiga string kontrak masih ada, keempat pola terlarang
    # tetap absen pada blok dengan penanda baru.
    start = source.index("remote_proposal_ingress.stage_text(")
    block = source[start:source.index("self._clarification_lock", start)]
    for forbidden in ("dispatch.dispatch_async", "telegram_light.execute", "approve_local", "executor="):
        assert forbidden not in block


def test_window_owns_remote_proposal_sheet_and_narrow_focus_executor_only():
    source = Path("jarvis/ui/window.py").read_text(encoding="utf-8")
    assert 'BUS.subscribe("remote_proposal.pending", self._on_remote_proposal_pending, ui=True)' in source
    assert "RemoteProposalSheet(" in source
    executor = source[source.index("def _execute_remote_proposal"):source.index("def _on_remote_proposal_pending")]
    assert "focus_mode_enable" in executor and "focus_mode_disable" in executor
    assert "execute_proposal" in executor
    assert "BrowserMedia" in executor
    for forbidden in ("desktop_safe", "uia", "coordinate", "screenshot", "open_url", "subprocess"):
        assert forbidden not in executor.lower()


def test_remote_proposal_sheet_never_uses_actor_or_session_in_summary():
    source = Path("jarvis/ui/remote_proposal_sheet.py").read_text(encoding="utf-8")
    summary = source[source.index("def present"):source.index("def summary_text")]
    rendered = "\n".join(line for line in summary.splitlines()
                           if "self._summary.setText" in line)
    assert "actor_id" not in rendered
    assert "session_id" not in rendered
    assert "_ACTION_LABELS" in rendered
