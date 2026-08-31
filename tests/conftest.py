import sys
from pathlib import Path

# project root importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# An ImportError during collection aborts the whole run, so a single file that
# imports a module which does not exist costs the entire suite, not just its own
# tests. Measured here on 2026-08-31: with the file below collected, `pytest`
# stopped after 5.05s having run ZERO tests; with it skipped, the same command
# ran 3899 tests in 1202s. That is the whole reason this list exists.
#
# test_voice_turn_guard.py (untracked, written 2026-08-24) imports
# jarvis.integrations.voice_turn_guard, which has never been written. Its own
# docstring says the seam is meant to be installed via monkeypatch "like
# voice_playback_fix", so it is a RED test for a seam that is still a plan —
# not a regression. Building the seam cannot make it pass anyway: wiring it
# into production needs an edit to main.py, which is on the FROZEN manifest.
#
# Re-enable by deleting the entry once the module exists. Do not clear this
# list to make the collection error "go away" — that error is the only signal
# that the suite stopped running at all.
collect_ignore = [
    "test_voice_turn_guard.py",
]
