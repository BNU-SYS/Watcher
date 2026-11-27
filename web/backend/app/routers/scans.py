"""Scan submission, progress, history and result endpoints."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from .. import config
from ..catalog import get_language
from ..job_manager import manager
from ..model_service import check_model_config
from ..repo_fetch import RepoError, parse_repo_url
from ..retry_targets import retry_targets
from ..schemas import (
    FindingOut,
    ModelVerifyRequest,
    ScanDetailOut,
    ScanEventOut,
    ScanFileOut,
    ScanOut,
    ScanPage,
    StatsOut,
)
from ..store import parse_time, store, utcnow
from .feedback import enqueue_feedback

router = APIRouter(prefix="/scans", tags=["scans"])

TERMINAL = {"succeeded", "partial", "failed", "cancelled"}
SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4, "unknown": 5}
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
INVALID_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


def _scan_or_404(scan_id: str) -> dict:
    scan = store.get(scan_id)
    if scan is None:
        raise HTTPException(status_code=404, detail="检测任务不存在")
    return scan


def _rel_path(raw: str) -> str:
    value = (raw or "").replace("\\", "/").strip()
    if not value or len(value) > 300:
        raise HTTPException(status_code=400, detail="文件路径为空或过长")
    parts: list[str] = []
    for part in value.split("/"):
        if part in ("", "."):
            continue
        if part == ".." or part.strip() != part or part.endswith("."):
            raise HTTPException(status_code=400, detail="文件路径包含非法片段")
        if INVALID_CHARS.search(part):
            raise HTTPException(status_code=400, detail=f"文件名包含非法字符：{part}")
        if part.split(".")[0].upper() in WINDOWS_RESERVED:
            raise HTTPException(status_code=400, detail=f"文件名不可用：{part}")
        parts.append(part)
    if not parts:
        raise HTTPException(status_code=400, detail="文件路径为空")
    return "/".join(parts)


def _strip_common_root(paths: list[str]) -> list[str]:
    if not paths or not all("/" in path for path in paths):
        return paths
    first = paths[0].split("/", 1)[0]
    if all(path.split("/", 1)[0] == first for path in paths):
        return [path.split("/", 1)[1] for path in paths]
    return paths


def _normalize_extension(path: str, extensions: list[str]) -> str | None:
    """Keep the language's glob (lowercase) matching the stored file name."""
    suffix = Path(path).suffix
    if suffix.lower() not in extensions:
        return None
    if suffix != suffix.lower():
        path = path[: -len(suffix)] + suffix.lower()
    return path


def _clamp(value: int, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _limits(
    max_files: int,
    max_model_calls: int,
    timeout: int,
    request_timeout: int,
    max_file_chars: int,
    json_mode: bool,
) -> dict:
    return {
        "max_files": _clamp(max_files, 1, 200, config.DEFAULT_MAX_FILES),
        "max_model_calls": _clamp(
            max_model_calls, 1, 200, config.DEFAULT_MAX_MODEL_CALLS
        ),
        "timeout": _clamp(timeout, 30, 3600, config.DEFAULT_TIMEOUT),
        "request_timeout": _clamp(
            request_timeout, 10, 600, config.DEFAULT_REQUEST_TIMEOUT
        ),
        "max_file_chars": _clamp(
            max_file_chars, 1000, 200_000, config.DEFAULT_MAX_FILE_CHARS
        ),
        "json_mode": bool(json_mode),
    }


def _defect_types(raw: str, language: dict) -> list[str]:
    try:
        requested = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="缺陷类型参数格式不正确") from None
    if not isinstance(requested, list):
        raise HTTPException(status_code=400, detail="缺陷类型参数格式不正确")
    supported = [item["code"] for item in language["defect_types"]]
    selected = [str(code) for code in requested]
    unknown = [code for code in selected if code not in supported]
    if unknown:
        raise HTTPException(status_code=400, detail=f"不支持的缺陷类型：{', '.join(unknown)}")
    if not selected:
        selected = supported
    return list(dict.fromkeys(selected))


@router.post("", response_model=ScanOut, status_code=201)
async def create_scan(
    language: str = Form(...),
    defect_types: str = Form("[]"),
    base_url: str = Form(...),
    model: str = Form(...),
    api_key: str = Form(...),
    source_kind: str = Form("upload"),
    files: list[UploadFile] = File(default=[]),
    paths: str = Form("[]"),
    code: str = Form(""),
    filename: str = Form(""),
    repo_url: str = Form(""),
    repo_ref: str = Form(""),
    repo_subdir: str = Form(""),
    max_files: int = Form(config.DEFAULT_MAX_FILES),
    max_model_calls: int = Form(config.DEFAULT_MAX_MODEL_CALLS),
    timeout: int = Form(config.DEFAULT_TIMEOUT),
    request_timeout: int = Form(config.DEFAULT_REQUEST_TIMEOUT),
    max_file_chars: int = Form(config.DEFAULT_MAX_FILE_CHARS),
    json_mode: bool = Form(False),
) -> ScanOut:
    entry = get_language(language)
    if entry is None:
        raise HTTPException(status_code=400, detail="所选代码类型暂不可用")
    if source_kind not in ("upload", "paste", "url"):
        raise HTTPException(status_code=400, detail="未知的源码来源")
    credential = check_model_config(base_url, model, api_key)
    selected = _defect_types(defect_types, entry)
    options = _limits(
        max_files, max_model_calls, timeout, request_timeout, max_file_chars, json_mode
    )
    package_mode = entry["code"] == "agent_skill"
    extensions = [suffix.lower() for suffix in entry["extensions"]]

    scan_id = uuid4().hex
    workspace = config.WORKSPACES_DIR / scan_id / "source"
    workspace.mkdir(parents=True, exist_ok=False)
    stored: list[dict] = []
    skipped: list[str] = []
    repo_fields: dict = {}

    try:
        if source_kind == "paste":
            if package_mode:
                raise HTTPException(
                    status_code=400,
                    detail="Agent Skill 需要上传完整包目录，不支持粘贴单个文件",
                )
            text = code.replace("\r\n", "\n").replace("\r", "\n")
            if not text.strip():
                raise HTTPException(status_code=400, detail="请粘贴需要检测的代码")
            if len(text) > config.MAX_PASTE_CHARS:
                raise HTTPException(status_code=400, detail="粘贴代码过长，请改用文件上传")
            if len(text) > options["max_file_chars"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"粘贴代码超过单文件上限 {options['max_file_chars']} 字符，请调整高级参数或改用文件上传",
                )
            name = PurePosixPath((filename or "").replace("\\", "/")).name
            suffix = Path(name).suffix.lower()
            if not name:
                name = "snippet" + extensions[0]
            elif not suffix:
                name += extensions[0]
            elif suffix not in extensions:
                raise HTTPException(
                    status_code=400,
                    detail=f"文件扩展名需为 {', '.join(extensions)}",
                )
            if Path(name).suffix != suffix:
                name = name[: -len(Path(name).suffix)] + suffix
            rel = _rel_path(name)
            stored.append(
                {
                    "path": rel,
                    "text": text,
                    "size": len(text.encode("utf-8")),
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "lines": text.count("\n") + 1,
                }
            )
            source_name = rel
        elif source_kind == "url":
            if package_mode:
                raise HTTPException(
                    status_code=400,
                    detail="Agent Skill 包暂不支持仓库链接，请上传完整包目录",
                )
            try:
                spec = parse_repo_url(repo_url, repo_ref, repo_subdir)
            except RepoError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            repo_fields = {
                "repo_url": spec.web_url,
                "repo_ref": spec.ref,
                "repo_subdir": spec.subdir,
                "repo_extensions": list(extensions),
            }
            source_name = spec.label
        else:
            if not files:
                raise HTTPException(status_code=400, detail="请选择要上传的源码文件")
            if len(files) > config.MAX_UPLOAD_FILES:
                raise HTTPException(
                    status_code=400,
                    detail=f"单次最多上传 {config.MAX_UPLOAD_FILES} 个文件",
                )
            try:
                raw_paths = json.loads(paths) if paths.strip() else []
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="文件路径参数格式不正确") from None
            if not isinstance(raw_paths, list):
                raise HTTPException(status_code=400, detail="文件路径参数格式不正确")
            total_bytes = 0
            candidates: list[tuple[str, bytes, str]] = []
            for index, upload in enumerate(files):
                try:
                    raw_name = (
                        raw_paths[index]
                        if index < len(raw_paths) and isinstance(raw_paths[index], str)
                        else (upload.filename or f"file-{index + 1}.txt")
                    )
                    rel = _rel_path(raw_name)
                    data = await upload.read(config.MAX_FILE_BYTES + 1)
                    if len(data) > config.MAX_FILE_BYTES:
                        raise HTTPException(
                            status_code=400,
                            detail=f"文件 {rel} 超过 {config.MAX_FILE_BYTES // (1024 * 1024)} MB 限制",
                        )
                    total_bytes += len(data)
                    if total_bytes > config.MAX_TOTAL_BYTES:
                        raise HTTPException(
                            status_code=400,
                            detail=f"上传总大小超过 {config.MAX_TOTAL_BYTES // (1024 * 1024)} MB 限制",
                        )
                    try:
                        text = data.decode("utf-8-sig")
                    except UnicodeDecodeError:
                        if package_mode:
                            skipped.append(rel)
                            continue
                        raise HTTPException(
                            status_code=400, detail=f"文件 {rel} 不是有效的 UTF-8 文本"
                        ) from None
                    candidates.append((rel, data, text))
                finally:
                    await upload.close()

            if candidates:
                stripped = _strip_common_root([item[0] for item in candidates])
                candidates = [
                    (new_path, item[1], item[2])
                    for new_path, item in zip(stripped, candidates)
                ]
            for rel, data, text in candidates:
                if package_mode:
                    fixed = rel
                else:
                    fixed = _normalize_extension(rel, extensions)
                    if fixed is None:
                        skipped.append(rel)
                        continue
                if not text.strip():
                    skipped.append(fixed)
                    continue
                stored.append(
                    {
                        "path": fixed,
                        "text": text,
                        "size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "lines": text.count("\n") + 1,
                    }
                )
            if not stored:
                detail = (
                    "没有找到可读取的 Agent Skill 文件，请上传包含 SKILL.md 的完整包"
                    if package_mode
                    else f"没有找到可检测的文件，支持 {', '.join(extensions)}"
                )
                raise HTTPException(status_code=400, detail=detail)
            if package_mode and not any(
                item["path"] == "SKILL.md" for item in stored
            ):
                raise HTTPException(
                    status_code=400,
                    detail="请在 Agent Skill 包根目录放置 SKILL.md，一次上传一个包",
                )
            seen: set[str] = set()
            for item in stored:
                key = item["path"].lower()
                if key in seen:
                    raise HTTPException(status_code=400, detail=f"文件路径重复：{item['path']}")
                seen.add(key)
            for item in stored:
                prefix = item["path"] + "/"
                if any(other["path"].startswith(prefix) for other in stored):
                    raise HTTPException(
                        status_code=400,
                        detail=f"文件与目录同名，无法写入：{item['path']}",
                    )
            source_name = (
                stored[0]["path"] if len(stored) == 1 else f"{len(stored)} 个文件"
            )

        for item in stored:
            dest = (workspace / PurePosixPath(item["path"])).resolve()
            if not dest.is_relative_to(workspace.resolve()):
                raise HTTPException(status_code=400, detail="文件路径越界")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(item["text"], encoding="utf-8")

        created = utcnow()
        scan = {
            "id": scan_id,
            "language": entry["code"],
            "skill_id": entry["skill_id"],
            "skill_version": entry["skill_version"],
            "defect_types": selected,
            "options": options,
            "source_kind": source_kind,
            "source_name": source_name[:255],
            **repo_fields,
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
            "workspace_path": str(workspace),
            "report_path": "",
            "created_at": created,
            "started_at": None,
            "finished_at": None,
            "files": [
                {
                    "path": item["path"],
                    "size_bytes": item["size"],
                    "sha256": item["sha256"],
                    "line_count": item["lines"],
                }
                for item in stored
            ],
            "findings": [],
            "events": [
                {
                    "id": 1,
                    "event": "scan.queued",
                    "level": "info",
                    "message": (
                        f"已接受仓库 {source_name}，等待下载"
                        if source_kind == "url"
                        else f"已接收 {len(stored)} 个文件，等待检测"
                    ),
                    "created_at": created,
                    "data": {},
                }
            ],
        }
        store.create(scan)
    except Exception:
        shutil.rmtree(workspace.parent, ignore_errors=True)
        raise

    manager.remember_credential(scan_id, credential)
    manager.start(scan_id)
    return ScanOut.model_validate(scan)


@router.get("", response_model=ScanPage)
def list_scans(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    status_filter: str | None = Query(None, alias="status"),
    language: str | None = Query(None),
    q: str | None = Query(None, max_length=100),
) -> ScanPage:
    if status_filter and status_filter not in TERMINAL | {"queued", "running"}:
        raise HTTPException(status_code=400, detail="未知的任务状态")
    rows = store.all()
    if status_filter:
        rows = [row for row in rows if row.get("status") == status_filter]
    if language:
        rows = [row for row in rows if row.get("language") == language]
    if q:
        needle = q.strip().lower()
        rows = [
            row
            for row in rows
            if needle in str(row.get("source_name", "")).lower()
            or needle in str(row.get("model_name", "")).lower()
        ]
    total = len(rows)
    start = (page - 1) * page_size
    items = rows[start : start + page_size]
    return ScanPage(
        items=[ScanOut.model_validate(row) for row in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stats", response_model=StatsOut)
def scan_stats() -> StatsOut:
    rows = store.all()
    total_findings = 0
    high_findings = 0
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    severity = {name: 0 for name in SEVERITY_RANK}
    for scan in rows:
        prompt_tokens += int(scan.get("prompt_tokens", 0) or 0)
        completion_tokens += int(scan.get("completion_tokens", 0) or 0)
        total_tokens += int(scan.get("total_tokens", 0) or 0)
        for finding in scan.get("findings") or []:
            total_findings += 1
            name = str(finding.get("severity", "unknown"))
            severity[name] = severity.get(name, 0) + 1
            if name in ("high", "critical"):
                high_findings += 1
    running = sum(1 for scan in rows if scan.get("status") in ("queued", "running"))
    completed = sum(1 for scan in rows if scan.get("status") in ("succeeded", "partial"))
    languages = len({scan.get("language") for scan in rows if scan.get("language")})
    recent = rows[:5]
    today = datetime.now(timezone.utc).date()
    counts: dict[str, int] = {}
    since = datetime.now(timezone.utc) - timedelta(days=7)
    for scan in rows:
        created = parse_time(scan.get("created_at"))
        if created is None or created < since:
            continue
        counts[created.date().isoformat()] = counts.get(created.date().isoformat(), 0) + 1
    token_counts: dict[str, dict[str, int]] = {}
    for scan in rows:
        created = parse_time(scan.get("created_at"))
        if created is None or created < since:
            continue
        entry = token_counts.setdefault(
            created.date().isoformat(),
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
        entry["prompt_tokens"] += int(scan.get("prompt_tokens", 0) or 0)
        entry["completion_tokens"] += int(scan.get("completion_tokens", 0) or 0)
        entry["total_tokens"] += int(scan.get("total_tokens", 0) or 0)
    daily = []
    token_daily = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        key = day.isoformat()
        daily.append({"date": key, "count": counts.get(key, 0)})
        counts_for_day = token_counts.get(key, {})
        token_daily.append(
            {
                "date": key,
                "prompt_tokens": counts_for_day.get("prompt_tokens", 0),
                "completion_tokens": counts_for_day.get("completion_tokens", 0),
                "total_tokens": counts_for_day.get("total_tokens", 0),
            }
        )
    return StatsOut(
        total_scans=len(rows),
        running_scans=running,
        completed_scans=completed,
        total_findings=total_findings,
        high_findings=high_findings,
        languages=languages,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        recent=[ScanOut.model_validate(row) for row in recent],
        daily=daily,
        token_daily=token_daily,
        severity=severity,
    )


@router.get("/{scan_id}", response_model=ScanDetailOut)
def get_scan(scan_id: str) -> ScanDetailOut:
    scan = _scan_or_404(scan_id)
    files = sorted(scan.get("files") or [], key=lambda item: item.get("path", ""))
    findings = sorted(
        scan.get("findings") or [],
        key=lambda item: (
            SEVERITY_RANK.get(str(item.get("severity", "unknown")), 9),
            item.get("path", ""),
            int(item.get("start_line", 1) or 1),
            int(item.get("id", 0) or 0),
        ),
    )
    events = list(scan.get("events") or [])[-100:]
    report = Path(scan["report_path"]) if scan.get("report_path") else None
    data = {
        **scan,
        "files": files,
        "findings": findings,
        "events": events,
        "coverage": scan.get("coverage") or None,
        "errors": scan.get("errors") or [],
        "has_report": bool(report and report.is_file()),
        "retry_file_count": len(retry_targets(scan)[0]),
    }
    return ScanDetailOut.model_validate(data)


@router.post("/{scan_id}/retry", response_model=ScanOut, status_code=201)
async def retry_failed_files(scan_id: str, payload: ModelVerifyRequest) -> ScanOut:
    parent = _scan_or_404(scan_id)
    paths, feedback = retry_targets(parent)
    if not paths:
        raise HTTPException(status_code=409, detail="该报告没有可重试的失败文件")
    if any(row.get("retry_of") == scan_id and row["status"] not in TERMINAL for row in store.all()):
        raise HTTPException(status_code=409, detail="该报告已有正在进行的重试任务")
    credential = check_model_config(payload.base_url, payload.model, payload.api_key)
    if feedback:
        return enqueue_feedback(parent, feedback, credential, retry_files=len(paths))

    new_id = uuid4().hex
    created = utcnow()
    options = dict(parent["options"])
    options["max_model_calls"] = max(options.get("max_model_calls") or 0, len(paths))
    scan = {
        "id": new_id,
        "language": parent["language"],
        "skill_id": parent["skill_id"],
        "skill_version": parent["skill_version"],
        "defect_types": parent["defect_types"],
        "workspace_path": parent["workspace_path"],
        "files": parent["files"],
        "repo_url": parent.get("repo_url", ""),
        "options": options,
        "source_kind": "retry",
        "source_name": parent["source_name"].removesuffix(" · 重试") + " · 重试",
        "parent_scan_id": scan_id,
        "retry_of": scan_id,
        "retry_paths": paths,
        "status": "queued",
        "status_detail": "排队中",
        "total_files": len(paths),
        "model_name": credential["model"],
        "base_url": credential["base_url"],
        "created_at": created,
    }
    scan = store.create(scan)
    store.append_event(new_id, "scan.queued", message=f"等待重试 {len(paths)} 个失败文件")
    manager.remember_credential(new_id, credential)
    manager.start(new_id)
    return ScanOut.model_validate(scan)


@router.get("/{scan_id}/findings", response_model=list[FindingOut])
def list_findings(
    scan_id: str,
    severity: str | None = Query(None),
    defect_type: str | None = Query(None),
) -> list[FindingOut]:
    scan = _scan_or_404(scan_id)
    rows = scan.get("findings") or []
    if severity:
        rows = [row for row in rows if row.get("severity") == severity]
    if defect_type:
        rows = [row for row in rows if row.get("defect_type") == defect_type]
    return [FindingOut.model_validate(row) for row in rows]


@router.get("/{scan_id}/report")
def download_report(scan_id: str):
    scan = _scan_or_404(scan_id)
    if not scan.get("report_path"):
        raise HTTPException(status_code=404, detail="该任务尚未生成报告")
    path = Path(scan["report_path"]).resolve()
    if not path.is_file() or not path.is_relative_to(config.REPORTS_DIR.resolve()):
        raise HTTPException(status_code=404, detail="报告文件不存在")
    return FileResponse(
        path,
        media_type="application/json",
        filename=f"watcher-{scan['id']}.json",
    )


@router.get("/{scan_id}/source", response_class=PlainTextResponse)
def read_source(scan_id: str, path: str = Query(..., max_length=300)) -> PlainTextResponse:
    scan = _scan_or_404(scan_id)
    rel = _rel_path(path)
    workspace = Path(scan["workspace_path"]).resolve()
    target = (workspace / PurePosixPath(rel)).resolve()
    if not target.is_relative_to(workspace) or not target.is_file():
        raise HTTPException(status_code=404, detail="源码文件不存在")
    if target.stat().st_size > 2 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件过大，无法在线预览")
    return PlainTextResponse(
        target.read_text(encoding="utf-8"),
        media_type="text/plain; charset=utf-8",
    )


@router.post("/{scan_id}/cancel")
async def cancel_scan(scan_id: str) -> dict:
    scan = _scan_or_404(scan_id)
    if scan.get("status") not in ("queued", "running"):
        raise HTTPException(status_code=409, detail="该任务已结束，无法取消")
    store.update(scan_id, status_detail="正在取消任务")
    await manager.cancel(scan_id)
    current = store.get(scan_id)
    if current is not None and current.get("status") not in TERMINAL:
        store.update(
            scan_id,
            status="cancelled",
            status_detail="任务已取消",
            finished_at=utcnow(),
        )
        store.append_event(
            scan_id,
            "scan.cancelled",
            level="warn",
            message="用户取消了检测任务",
        )
    return {"status": "cancelling"}


def _purge_scan(scan: dict) -> None:
    """Remove one scan record together with its workspace and report files."""
    store.delete(scan["id"])
    if scan.get("source_kind") not in ("feedback", "retry"):
        workspace = Path(scan.get("workspace_path", ""))
        if workspace.name:
            shutil.rmtree(workspace.parent, ignore_errors=True)
    output_dir = scan.get("output_dir")
    if output_dir:
        path = Path(output_dir)
        if path.is_relative_to(config.REPORTS_DIR.resolve()):
            shutil.rmtree(path.parent, ignore_errors=True)
    shutil.rmtree(config.REPORTS_DIR / scan["id"], ignore_errors=True)


@router.delete("/{scan_id}", status_code=204)
def delete_scan(scan_id: str, cascade: bool = False) -> Response:
    scan = _scan_or_404(scan_id)
    if scan.get("status") in ("queued", "running"):
        raise HTTPException(status_code=409, detail="请先取消正在进行的任务")
    rows = store.all()
    children: list[dict] = []
    frontier = [scan_id]
    while frontier:
        current = frontier.pop()
        for row in rows:
            if row.get("parent_scan_id") == current and row not in children:
                children.append(row)
                frontier.append(row["id"])
    if children and not cascade:
        raise HTTPException(
            status_code=409,
            detail=f"该报告有 {len(children)} 份后续报告，需一并删除",
        )
    if any(child["status"] not in TERMINAL for child in children):
        raise HTTPException(status_code=409, detail="请先取消正在进行的后续任务")
    for child in reversed(children):
        _purge_scan(child)
    _purge_scan(scan)
    return Response(status_code=204)
