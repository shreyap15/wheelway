"""Shared sys.path bootstrap for local script execution.

Ensures the accessroute project root is on sys.path so imports always
resolve as ``accessroute.*``, matching ``python -m accessroute.*`` runs.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def ensure_project_root() -> Path:
    """Insert the project root on sys.path if it is not already present."""
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    return PROJECT_ROOT
