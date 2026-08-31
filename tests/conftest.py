"""Pytest configuration and sys.path setup for the test suite."""

import sys
from pathlib import Path

# Add backend directory to Python sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
