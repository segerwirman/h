import sys
from pathlib import Path

# project root importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
