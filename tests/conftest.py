# ============================================================
# Battery Dataset Simulation Platform v0.1
# pytest shared setup
#
# Makes the project root importable regardless of the pytest
# invocation directory (works on native Windows and inside WSL).
# ============================================================

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
