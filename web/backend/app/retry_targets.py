"""Find retryable work from persisted report outcomes."""

from pathlib import Path

from . import config
from .schemas import FeedbackItemIn


def retry_targets(scan: dict) -> tuple[list[str], list[FeedbackItemIn]]:
    """Return distinct captured paths and, for feedback reports, the failed claims."""
    if scan.get("status") not in {"partial", "failed", "cancelled"} or scan.get("language") == "agent_skill":
        return [], []
    report_path = scan.get("report_path")
    if not report_path:
        return [], []
    report = Path(report_path).resolve()
    if not report.is_relative_to(config.REPORTS_DIR.resolve()) or not report.is_file():
        return [], []
    if not (report.parent / "input-index.json").is_file():
        return [], []

    if scan.get("source_kind") != "feedback":
        rows = (scan.get("coverage") or {}).get("file_reviews") or []
        return list(dict.fromkeys(
            row["path"] for row in rows if row["status"] in {"failed", "not_run", "interrupted"}
        )), []

    if scan.get("status") == "cancelled" or scan.get("error_code") in {"TIMEOUT", "EXECUTION_FAILED"}:
        return [], []
    findings = {row["finding_key"]: row["path"] for row in scan.get("findings") or []}
    paths = set()
    items = []
    for row in (scan.get("feedback_summary") or {}).get("items") or []:
        if row.get("status") not in {"failed", "not_applied", "budget_exhausted", "unresolved"}:
            continue
        entry = row["feedback"]
        path = entry["path"]
        if entry.get("finding_id") and findings.get(entry["finding_id"]) != path:
            continue
        items.append(FeedbackItemIn.model_validate({k: v for k, v in entry.items() if k != "id"}))
        paths.add(path)
    return sorted(paths), items
