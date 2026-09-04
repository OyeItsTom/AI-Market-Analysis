"""Pytest configuration.

Its presence at the repository root puts that root on ``sys.path``, so tests
can ``import src.data...`` without an editable install.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
