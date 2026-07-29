"""Kontrak model Gemini Live yang benar-benar dipakai runtime voice."""
from __future__ import annotations

import ast
from pathlib import Path

import yaml


EXPECTED_LIVE_MODEL = "models/gemini-3.1-flash-live-preview"


def _legacy_live_model() -> str:
    tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "LIVE_MODEL"
                for target in node.targets)
    )
    return ast.literal_eval(assignment.value)


def test_live_runtime_and_metadata_use_the_supported_migration_target():
    configured = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))

    assert _legacy_live_model() == EXPECTED_LIVE_MODEL
    assert configured["llm"]["live_model"] == EXPECTED_LIVE_MODEL


def test_live_audio_input_declares_the_required_pcm_sample_rate():
    source = Path("main.py").read_text(encoding="utf-8")

    assert '"mime_type": "audio/pcm;rate=16000"' in source


def test_live_invalid_argument_is_not_misreported_as_an_invalid_api_key():
    source = Path("main.py").read_text(encoding="utf-8")

    assert 'if "API key not valid" in err_str:' in source
    assert 'or "1007" in err_str' not in source
