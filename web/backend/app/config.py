"""Runtime configuration for the Watcher web console."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.environ.get("WATCHER_DATA_DIR", BASE_DIR / "data")).resolve()
FRAMEWORK_DIR = Path(
    os.environ.get("WATCHER_FRAMEWORK_DIR", BASE_DIR.parent)
).resolve()
FRAMEWORK_SRC = FRAMEWORK_DIR / "src"
WORKSPACES_DIR = DATA_DIR / "workspaces"
REPORTS_DIR = DATA_DIR / "reports"
SCANS_DIR = DATA_DIR / "scans"

MAX_CONCURRENT_SCANS = int(os.environ.get("WATCHER_MAX_CONCURRENT_SCANS", "1"))
if MAX_CONCURRENT_SCANS < 1:
    MAX_CONCURRENT_SCANS = 1

MAX_UPLOAD_FILES = 100
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 12 * 1024 * 1024
MAX_PASTE_CHARS = 200_000

MAX_REPO_BYTES = 60 * 1024 * 1024
MAX_REPO_FILES = 2000
REPO_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "__pycache__",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "target",
    ".venv",
    "venv",
}

DEFAULT_MAX_FILES = 20
DEFAULT_MAX_MODEL_CALLS = 20
DEFAULT_TIMEOUT = 300
DEFAULT_REQUEST_TIMEOUT = 60
DEFAULT_MAX_FILE_CHARS = 30_000


def ensure_dirs() -> None:
    for directory in (DATA_DIR, WORKSPACES_DIR, REPORTS_DIR, SCANS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
