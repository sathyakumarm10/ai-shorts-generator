"""Pytest configuration and isolated runtime setup for the test suite."""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path


_test_runtime_dir = Path(tempfile.mkdtemp(prefix="ai-shorts-tests-"))
atexit.register(shutil.rmtree, _test_runtime_dir, ignore_errors=True)

# Set these before importing application modules so default stores never touch
# normal development databases, uploaded media, outputs, or model caches.
os.environ["DATABASE_BACKEND"] = "sqlite"
os.environ.pop("DATABASE_URL", None)
os.environ["JOB_DB_PATH"] = str(_test_runtime_dir / "jobs.sqlite3")
os.environ["USER_DB_PATH"] = str(_test_runtime_dir / "users.sqlite3")
os.environ["UPLOAD_DIR"] = str(_test_runtime_dir / "uploads")
os.environ["MEDIA_ROOT"] = str(_test_runtime_dir / "outputs")
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# Add backend directory to Python sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
