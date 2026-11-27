"""User feedback entry points backed by the framework feedback workflow."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from ..catalog import get_language
from ..job_manager import manager
from ..model_service import check_model_config
from ..schemas import FeedbackItemIn, FeedbackReportOut, FeedbackRequest, ScanOut
from ..store import store, utcnow

router = APIRouter(prefix="/feedback", tags=["feedback"])


def _feedback_ready(scan: dict) -> bool:
    if scan.get("language") == "agent_skill":
        return False
    if scan.get("status") not in ("succeeded", "partial"):
        return False
    report = scan.get("report_path")
    return bool(report and Path(report).is_file())


@router.get("/reports", response_model=list[FeedbackReportOut])
def feedback_reports() -> list[FeedbackReportOut]:
    rows = []
    for scan in store.all():
        if not _feedback_ready(scan):
            continue
        rows.append(FeedbackReportOut.model_validate({**scan, "number": len(rows) + 1}))
    return rows


@router.post("", response_model=ScanOut, status_code=201)
async def create_feedback(payload: FeedbackRequest) -> ScanOut:
    parent = store.get(payload.scan_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="原始检测报告不存在")
    if not _feedback_ready(parent):
        raise HTTPException(status_code=400, detail="该报告不支持提交反馈")
    credential = check_model_config(payload.base_url, payload.model, payload.api_key)
    return enqueue_feedback(parent, payload.items, credential)


def enqueue_feedback(
    parent: dict, feedback: list[FeedbackItemIn], credential: dict, *, retry_files: int = 0,
) -> ScanOut:
    findings = {str(item.get("finding_key", "")): item for item in parent.get("findings") or []}
    files = {str(item.get("path", "")) for item in parent.get("files") or []}
    language = get_language(str(parent.get("language", "")))
    supported = {
        item["code"] for item in (language or {}).get("defect_types", [])
    }
    for item in feedback:
        if item.kind == "false_negative":
            if item.path not in files:
                raise HTTPException(status_code=400, detail="漏报反馈指向了报告之外的文件")
        elif item.finding_id not in findings:
            raise HTTPException(status_code=400, detail="反馈指向了不存在的报告条目")
        if item.defect_type and item.defect_type not in supported:
            raise HTTPException(status_code=400, detail=f"该语言不支持缺陷类型：{item.defect_type}")

    items = [item.model_dump(exclude_none=True) for item in feedback]
    defect_types = list(parent.get("defect_types") or [])
    for item in feedback:
        if item.defect_type and item.defect_type not in defect_types:
            defect_types.append(item.defect_type)
    scan_id = uuid4().hex
    created = utcnow()
    options = dict(parent.get("options") or {})
    if retry_files:
        options["max_model_calls"] = max(options.get("max_model_calls") or 0, retry_files * 2)
    source_name = parent.get("source_name", "报告")
    if retry_files:
        source_name = source_name.removesuffix(" · 反馈重试").removesuffix(" · 反馈")
        source_name += " · 反馈重试"
    else:
        source_name += " · 反馈"
    scan = {
        "id": scan_id,
        "language": parent.get("language", ""),
        "skill_id": parent.get("skill_id", ""),
        "skill_version": parent.get("skill_version", ""),
        "defect_types": defect_types,
        "options": options,
        "source_kind": "feedback",
        "source_name": source_name,
        "parent_scan_id": parent["id"],
        "retry_of": parent["id"] if retry_files else "",
        "feedback_items": items,
        "status": "queued",
        "status_detail": "排队中",
        "total_files": 0,
        "completed_files": 0,
        "finding_count": 0,
        "model_calls": 0,
        "duration_seconds": 0.0,
        "model_name": credential["model"],
        "base_url": credential["base_url"],
        "framework_run_id": "",
        "error_code": "",
        "error_message": "",
        "coverage": None,
        "errors": [],
        "feedback_summary": None,
        "output_dir": "",
        "workspace_path": parent.get("workspace_path", ""),
        "report_path": "",
        "created_at": created,
        "started_at": None,
        "finished_at": None,
        "files": list(parent.get("files") or []),
        "findings": [],
        "events": [
            {
                "id": 1,
                "event": "feedback.queued",
                "level": "info",
                "message": f"已接收 {len(items)} 条用户反馈，等待模型处理",
                "created_at": created,
                "data": {},
            }
        ],
    }
    store.create(scan)
    manager.remember_credential(scan_id, credential)
    manager.start_feedback(scan_id)
    return ScanOut.model_validate(scan)
