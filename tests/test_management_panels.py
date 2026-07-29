"""Fase 10 — management panels consume only the safe shared snapshot."""
from __future__ import annotations

import importlib


def test_sessions_panel_memformat_snapshot_tanpa_raw_task():
    try:
        panel = importlib.import_module("jarvis.ui.sessions_panel")
    except ModuleNotFoundError:
        panel = None

    assert panel is not None
    assert panel.session_rows({"sessions": [{"id": "s1", "source": "ui",
                                              "status": "completed", "turn_count": 2}]}) == [
        "s1 · ui · completed · 2 turns"
    ]


def test_provider_panel_memformat_snapshot_aman():
    panel = importlib.import_module("jarvis.ui.provider_health_panel")
    assert panel.provider_rows({"providers": [{"name": "local", "configured": True,
                                                 "model": "safe-model"}]}) == [
        "local · configured · safe-model"
    ]
