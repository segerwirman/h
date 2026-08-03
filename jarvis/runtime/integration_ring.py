"""Phase 26 — cross-integration live ring (offline proof ring).

Satu alur deterministik yang memakai seluruh rangkaian inti WA0→WA9
BERSAMA-SAMA, tanpa kredensial, tanpa jaringan/live provider. Hasil
metadata-only per step; ring berjalan apa pun status gate (jujur).
Proof ring — BUKAN live-proven. Tanpa import SDK/network/file.
"""
from __future__ import annotations

from jarvis.integrations.whatsapp_readiness import (
    readiness as _readiness,
)
from jarvis.integrations.whatsapp_rollout import WhatsAppRolloutPolicy
from jarvis.core.countdown_timer import CountdownTimer
from jarvis.core.call_session import CallSession
from jarvis.core.call_audio import CallAudioProof
from jarvis.core.call_dialogue import CallDialogue, LOCAL, REMOTE
from jarvis.core.call_memory import CallMemoryStore
from jarvis.core.calendar_proposal import CalendarProposal
from jarvis.core.reservation_gate import ReservationCommitmentGate
from jarvis.core.service_case import ServiceCase


def _fake_capture(duration_s: int) -> int:
    return duration_s * 4800          # samples dummy, offline


def _fake_playback(duration_s: int) -> bool:
    return duration_s > 0


def run_ring() -> dict:
    """Jalankan semua step inti; return metadata-only (ok + steps)."""
    steps: dict = {}

    # WA0 — readiness gate (jujur tanpa kredensial)
    steps["readiness"] = _readiness()

    # WA9 — rollout policy (deny-by-default)
    rollout = WhatsAppRolloutPolicy()
    steps["rollout"] = rollout.allow_outbound("Toko Bunga")

    # WA1 — countdown timer (deadline monotonic)
    timer = CountdownTimer()
    timer.start(5)
    steps["countdown"] = {"status": timer.status(),
                          "remaining_s": timer.remaining_s()}

    # WA2 — call session (approval lokal)
    session = CallSession()
    session.start(contact="Toko Bunga", objective="cek jam buka",
                  ttl_s=300)
    session.approve()
    steps["session"] = {"status": session.status()}

    # WA3 — audio proof (fake capture/playback, offline)
    audio = CallAudioProof(capture=_fake_capture, playback=_fake_playback)
    audio.start(session, 5)
    result = audio.result()
    steps["audio"] = {"status": result["status"],
                      "samples_captured": result["samples_captured"],
                      "audio_exercised": result["audio_exercised"]}

    # WA4 — dialogue (turn alternation lokal ↔ remote)
    dialogue = CallDialogue()
    dialogue.start(session)
    dialogue.submit_turn("Halo, ada info harga?", LOCAL)
    dialogue.submit_turn("Tentu, harga mulai 100rb.", REMOTE)
    summary = dialogue.summary()
    steps["dialogue"] = {"status": summary["status"],
                         "turn_count": summary["turn_count"]}

    # WA5 — call memory (opt-in config; jujur kalau disabled)
    memory = CallMemoryStore()
    memory.record({"session_id": session.session_id(), "status": "done",
                   "duration_s": 5, "turn_count": 2})
    steps["memory"] = {"count": memory.count()}

    # WA6 — calendar proposal (approval lokal)
    proposal = CalendarProposal()
    proposal.create(title="Follow-up Toko Bunga", start_ts=1_800_100_000,
                    duration_min=30)
    proposal.approve()
    steps["proposal"] = {"status": proposal.status()}

    # WA7 — reservation commitment gate (green light)
    gate = ReservationCommitmentGate()
    gate_result = gate.evaluate(approved=True,
                                labels=["commitment",
                                        "cancellation_policy"],
                                cancel_within_days=7)
    steps["reservation"] = {"ok": gate_result["ok"],
                            "reason": gate_result["reason"]}

    # WA8 — service case (disclosure policy)
    case = ServiceCase()
    case.open("order_status", "ORD-123456")
    steps["case"] = {"status": case.status(),
                     "disclosed": case.disclose("order_status_update")}

    # Ring "ok" = semua step SELESAI dieksekusi (tanpa error) — status gate
    # per step tetap jujur apa adanya (deny-by-default adalah hasil, bukan
    # kegagalan ring).
    ok = all(isinstance(step, dict) for step in steps.values())
    return {"ok": ok, "steps": steps}


__all__ = ["run_ring"]
