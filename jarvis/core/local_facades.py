"""Phase 27 — named local facade.

Komposisi lokal yang dipanggil agent dengan nama eksplisit. Setiap facade
= daftar FIXED langkah lokal (tuple immutable, deny-unknown); invoke
menjalankan langkah berurutan dengan context lokal per call; hasil
metadata-only. TANPA authority baru: hanya komposisi modul inti yang
sudah ada (WA6 proposal, WA7 gate, WA8 case). Tanpa provider/network/file.
"""
from __future__ import annotations

from jarvis.core.calendar_proposal import CalendarProposal
from jarvis.core.reservation_gate import ReservationCommitmentGate
from jarvis.core.service_case import ServiceCase


class LocalFacadeRegistry:
    """Registry facade bernama; langkah fixed; deny-unknown."""

    def __init__(self) -> None:
        self._facades: dict[str, tuple] = {}

    def register(self, name: str, steps: tuple) -> None:
        """Daftarkan facade; steps = tuple (step_name, fn(ctx, **kwargs))."""
        self._facades[name] = tuple(steps)

    def steps(self, name: str) -> tuple:
        """Daftar langkah fixed (immutable)."""
        return self._facades.get(name, ())

    def invoke(self, name: str, **kwargs: object) -> dict:
        """Jalankan facade; deny-unknown; stop pada langkah gagal."""
        if name not in self._facades:
            return {"ok": False, "reason": "facade_unknown"}
        ctx: dict = {}
        step_results: dict = {}
        for step_name, fn in self._facades[name]:
            try:
                outcome = fn(ctx, **kwargs)
            except Exception as exc:  # noqa: BLE001
                outcome = {"ok": False, "error": type(exc).__name__}
            step_results[step_name] = outcome
            if not outcome.get("ok", True):
                return {"ok": False, "facade": name, "steps": step_results}
        return {"ok": True, "facade": name, "steps": step_results}


# ── langkah default (komposisi modul inti existing) ──────────────────────────

def _step_open_case(ctx: dict, reference: object) -> dict:
    case = ServiceCase()
    if not case.open("order_status", reference):
        return {"ok": False, "reason": "facade_step_rejected"}
    ctx["case"] = case
    return {"ok": True, "status": case.status()}


def _step_disclose_status(ctx: dict, **kwargs: object) -> dict:
    case: ServiceCase = ctx["case"]
    return {"ok": True, "disclosed": case.disclose("order_status_update")}


def _step_create_proposal(ctx: dict, title: str, start_ts: int,
                          duration_min: int, **kwargs: object) -> dict:
    proposal = CalendarProposal()
    if not proposal.create(title=title, start_ts=start_ts,
                           duration_min=duration_min):
        return {"ok": False, "reason": "facade_step_rejected"}
    proposal.approve()
    ctx["proposal"] = proposal
    return {"ok": True, "status": proposal.status()}


def _step_commitment_gate(ctx: dict, cancel_within_days: int,
                          **kwargs: object) -> dict:
    gate = ReservationCommitmentGate()
    outcome = gate.evaluate(approved=True,
                            labels=["commitment", "cancellation_policy"],
                            cancel_within_days=cancel_within_days)
    return {"ok": outcome["ok"], "reason": outcome["reason"]}


def default_facades() -> LocalFacadeRegistry:
    """Facade bawaan — komposisi murni modul inti, tanpa authority baru."""
    registry = LocalFacadeRegistry()
    registry.register("check_order_status", (
        ("open_case", _step_open_case),
        ("disclose_status", _step_disclose_status),
    ))
    registry.register("book_reservation", (
        ("create_proposal", _step_create_proposal),
        ("commitment_gate", _step_commitment_gate),
    ))
    return registry


__all__ = ["LocalFacadeRegistry", "default_facades"]
