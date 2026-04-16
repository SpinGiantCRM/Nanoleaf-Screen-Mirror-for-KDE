from __future__ import annotations

import sys
from pathlib import Path


# Ensure `import capture`, `import color`, etc work when running tests from the repo
# without requiring `PYTHONPATH` to be set manually.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
