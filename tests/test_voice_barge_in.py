"""Voice playback must not self-interrupt on speaker echo."""
from __future__ import annotations

from pathlib import Path

import yaml


def test_barge_in_defaults_off_until_echo_calibration_exists():
    config = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8-sig"))

    assert config["voice"]["barge_in"]["enabled"] is False
