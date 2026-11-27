"""Small local services used by the command-line tool."""

import asyncio
import hashlib
import json
from pathlib import Path

from .contracts import Artifact, relative_path


class LocalArtifacts:
    """Write UTF-8 evidence and reports inside one trusted attempt directory."""

    def __init__(self, root: Path) -> None:
        """Bind storage to an existing, per-attempt directory."""
        self.root = root.resolve(strict=True)

    def write_text(self, relative_path: str, content: str) -> Artifact:
        """Write exact bytes and return their digest; reject escaping paths."""
        path = self.path(relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        # Attempts use unique directories; exclusive writes also prevent overwrites.
        with path.open("xb") as stream:
            stream.write(data)
        return Artifact(id="artifact-" + hashlib.sha256(relative_path.encode()).hexdigest(),
                        path=relative_path, sha256=hashlib.sha256(data).hexdigest(),
                        media_type="application/json" if path.suffix == ".json" else "text/plain")

    def path(self, name: str) -> Path:
        """Resolve a portable artifact name under the configured root."""
        relative_path(name)
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("artifact path escapes its root")
        return path


class JsonEvents:
    """Append progress events to a local JSON Lines file."""

    def __init__(self, path: Path) -> None:
        """Bind the event log to the current attempt."""
        self.path = path

    def emit(self, event: str, data: dict) -> None:
        """Append an event without logging prompts or credentials."""
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": event, **data}, ensure_ascii=False) + "\n")


class TaskCancellation:
    """Bridge asyncio task cancellation into the framework protocol."""

    def raise_if_cancelled(self) -> None:
        """Stop when the current async task has a pending cancellation."""
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError()
