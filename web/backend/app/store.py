"""File-backed scan records.

Each scan is a single JSON document under ``data/scans/<scan_id>/scan.json``.
This keeps the project free of a database while still retaining history across
restarts. All access goes through one process-wide lock.
"""

from __future__ import annotations

import json
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from . import config

TERMINAL = {"succeeded", "partial", "failed", "cancelled"}
MAX_EVENTS = 500


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class ScanStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.RLock()
        self._scans: dict[str, dict] = {}

    def load(self) -> None:
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            self._scans.clear()
            for path in sorted(self.root.glob("*/scan.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(data, dict) or not data.get("id"):
                    continue
                self._normalize(data)
                self._scans[str(data["id"])] = data

    def _normalize(self, scan: dict) -> None:
        scan.setdefault("status", "failed")
        scan.setdefault("status_detail", "")
        scan.setdefault("files", [])
        scan.setdefault("findings", [])
        scan.setdefault("events", [])
        scan.setdefault("errors", [])
        scan.setdefault("coverage", None)
        scan.setdefault("defect_types", [])
        scan.setdefault("options", {})
        scan.setdefault("total_files", 0)
        scan.setdefault("completed_files", 0)
        scan.setdefault("finding_count", 0)
        scan.setdefault("model_calls", 0)
        scan.setdefault("prompt_tokens", 0)
        scan.setdefault("completion_tokens", 0)
        scan.setdefault("total_tokens", 0)
        scan.setdefault("duration_seconds", 0.0)
        scan.setdefault("report_path", "")
        scan.setdefault("framework_run_id", "")
        scan.setdefault("error_code", "")
        scan.setdefault("error_message", "")
        scan.setdefault("parent_scan_id", "")
        scan.setdefault("feedback_items", [])
        scan.setdefault("feedback_summary", None)
        scan.setdefault("output_dir", "")
        scan.setdefault("started_at", None)
        scan.setdefault("finished_at", None)
        scan.setdefault("created_at", utcnow())

    def _path(self, scan_id: str) -> Path:
        return self.root / scan_id / "scan.json"

    def _write(self, scan: dict) -> None:
        path = self._path(str(scan["id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.tmp")
        temp.write_text(
            json.dumps(scan, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(path)

    def create(self, scan: dict) -> dict:
        with self._lock:
            self._normalize(scan)
            self._scans[str(scan["id"])] = scan
            self._write(scan)
            return deepcopy(scan)

    def get(self, scan_id: str) -> dict | None:
        with self._lock:
            scan = self._scans.get(scan_id)
            return deepcopy(scan) if scan is not None else None

    def update(self, scan_id: str, **fields) -> dict | None:
        with self._lock:
            scan = self._scans.get(scan_id)
            if scan is None:
                return None
            scan.update(fields)
            self._write(scan)
            return deepcopy(scan)

    def append_event(
        self,
        scan_id: str,
        event: str,
        *,
        level: str = "info",
        message: str = "",
        data: dict | None = None,
        status_detail: str | None = None,
        total_files: int | None = None,
        completed_delta: int = 0,
    ) -> dict | None:
        with self._lock:
            scan = self._scans.get(scan_id)
            if scan is None:
                return None
            if total_files is not None:
                scan["total_files"] = int(total_files)
                scan["completed_files"] = 0
            if completed_delta:
                completed = int(scan.get("completed_files", 0)) + completed_delta
                scan["completed_files"] = min(int(scan.get("total_files", 0)), completed)
            if status_detail is not None:
                scan["status_detail"] = status_detail
            events = scan.setdefault("events", [])
            next_id = max((int(item.get("id", 0)) for item in events), default=0) + 1
            events.append(
                {
                    "id": next_id,
                    "event": event,
                    "level": level,
                    "message": message[:500],
                    "created_at": utcnow(),
                    "data": data or {},
                }
            )
            if len(events) > MAX_EVENTS:
                del events[:-MAX_EVENTS]
            self._write(scan)
            return deepcopy(scan)

    def replace_findings(self, scan_id: str, findings: list[dict], **fields) -> dict | None:
        with self._lock:
            scan = self._scans.get(scan_id)
            if scan is None:
                return None
            normalized = []
            for index, item in enumerate(findings, start=1):
                normalized.append({**item, "id": index})
            scan.update(fields)
            scan["findings"] = normalized
            scan["finding_count"] = len(normalized)
            self._write(scan)
            return deepcopy(scan)

    def delete(self, scan_id: str) -> bool:
        with self._lock:
            removed = self._scans.pop(scan_id, None)
            if removed is None:
                return False
            path = self._path(scan_id)
            try:
                path.unlink()
            except OSError:
                pass
            try:
                path.parent.rmdir()
            except OSError:
                pass
            return True

    def all(self) -> list[dict]:
        with self._lock:
            rows = [deepcopy(scan) for scan in self._scans.values()]
        rows.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return rows


store = ScanStore(config.SCANS_DIR)
