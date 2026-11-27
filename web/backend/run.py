"""Development launcher: python backend/run.py"""

from __future__ import annotations

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.environ.get("WATCHER_HOST", "127.0.0.1"),
        port=int(os.environ.get("WATCHER_PORT", "8000")),
        reload=os.environ.get("WATCHER_RELOAD", "").lower() in ("1", "true", "yes"),
    )
