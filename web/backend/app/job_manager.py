"""Background scan scheduling, progress persistence and result ingestion."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from . import config
from .detector_runner import execute_scan
from .feedback_runner import execute_feedback
from .repo_fetch import RepoError, fetch_repository, parse_repo_url
from .store import TERMINAL, store, utcnow

EVENT_MESSAGES = {
    "scan.collecting": "正在采集源码",
    "scan.prepared": "源码采集完成，准备调用模型",
    "workflow.prepared": "请求已通过校验",
    "workflow.validated": "模型输出已通过结构校验",
    "workflow.saved": "报告已保存",
    "scan.report_saved": "检测结束，正在归档结果",
    "model.package_completed": "Agent Skill 包审查完成",
    "feedback.ready": "反馈任务已准备",
    "feedback.prepared": "反馈目标已通过校验",
    "feedback.finished": "反馈处理结束",
}


class ScanSetupError(RuntimeError):
    """The task cannot start with the submitted configuration."""


def _limit(value, low: int, high: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _human_error(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    text = detail if isinstance(detail, str) else str(exc)
    text = " ".join(text.split())
    return text[:280] or exc.__class__.__name__


def _resolve_finding_path(raw: str, known: list[str]) -> str:
    """Match a model-reported path to a file that was actually collected."""
    if not raw or not known or raw in known:
        return raw
    normalized = raw.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    matches = [
        item
        for item in known
        if item == normalized
        or item.endswith("/" + normalized)
        or normalized.endswith("/" + item)
    ]
    return matches[0] if len(matches) == 1 else raw


class ScanJobManager:
    """Own the asyncio tasks so cancellation and restarts stay predictable."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._pending: dict[str, dict] = {}
        self._semaphore: asyncio.Semaphore | None = None

    def _sem(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_SCANS)
        return self._semaphore

    def remember_credential(self, scan_id: str, credential: dict) -> None:
        """Keep the API key in memory only until the task starts."""
        self._pending[scan_id] = credential

    def start(self, scan_id: str) -> None:
        task = asyncio.create_task(self._run(scan_id), name=f"scan-{scan_id}")
        self._tasks[scan_id] = task
        task.add_done_callback(lambda _task, key=scan_id: self._tasks.pop(key, None))

    def start_feedback(self, scan_id: str) -> None:
        task = asyncio.create_task(self._run_feedback(scan_id), name=f"feedback-{scan_id}")
        self._tasks[scan_id] = task
        task.add_done_callback(lambda _task, key=scan_id: self._tasks.pop(key, None))

    async def cancel(self, scan_id: str) -> bool:
        task = self._tasks.get(scan_id)
        if task is None or task.done():
            self._pending.pop(scan_id, None)
            return False
        task.cancel()
        self._pending.pop(scan_id, None)
        return True

    async def shutdown(self) -> None:
        self._pending.clear()
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, scan_id: str) -> None:
        try:
            async with self._sem():
                try:
                    await self._fetch_if_needed(scan_id)
                    payload = self._prepare(scan_id)
                except Exception as exc:  # noqa: BLE001 - configuration error
                    self._pending.pop(scan_id, None)
                    self._mark_failed(scan_id, _human_error(exc))
                    return
                if payload is None:
                    return
                try:
                    outcome = await execute_scan(
                        workspace=payload["workspace"],
                        language=payload["language"],
                        defect_types=payload["defect_types"],
                        credential=payload["credential"],
                        limits=payload["limits"],
                        reports_root=config.REPORTS_DIR / scan_id,
                        sink=lambda event, data: self._on_event(scan_id, event, data),
                        **payload["retry"],
                    )
                except asyncio.CancelledError:
                    self._mark_cancelled(scan_id)
                    raise
                except Exception as exc:  # noqa: BLE001 - stored for the UI
                    self._mark_failed(scan_id, _human_error(exc))
                    return
                self._ingest(scan_id, outcome)
        except asyncio.CancelledError:
            self._mark_cancelled(scan_id)
            raise

    async def _run_feedback(self, scan_id: str) -> None:
        try:
            async with self._sem():
                try:
                    payload = self._prepare_feedback(scan_id)
                except Exception as exc:  # noqa: BLE001 - configuration error
                    self._pending.pop(scan_id, None)
                    self._mark_failed(scan_id, _human_error(exc))
                    return
                if payload is None:
                    return
                try:
                    outcome = await execute_feedback(
                        parent=payload["parent"],
                        items=payload["items"],
                        credential=payload["credential"],
                        limits=payload["limits"],
                        sink=lambda event, data: self._on_event(scan_id, event, data),
                    )
                except asyncio.CancelledError:
                    self._mark_cancelled(scan_id)
                    raise
                except Exception as exc:  # noqa: BLE001 - stored for the UI
                    self._mark_failed(scan_id, _human_error(exc))
                    return
                self._ingest(scan_id, outcome)
        except asyncio.CancelledError:
            self._mark_cancelled(scan_id)
            raise

    def _prepare_feedback(self, scan_id: str) -> dict | None:
        scan = store.get(scan_id)
        if scan is None or scan.get("status") != "queued":
            self._pending.pop(scan_id, None)
            return None
        parent = store.get(str(scan.get("parent_scan_id", "")))
        if parent is None:
            raise ScanSetupError("原始检测报告不存在，无法提交反馈")
        credential = self._pending.pop(scan_id, None)
        if credential is None:
            raise ScanSetupError("模型配置未随任务保留，请重新提交反馈")
        options = scan.get("options") or {}
        store.update(
            scan_id,
            status="running",
            started_at=utcnow(),
            status_detail="正在准备反馈",
            model_name=credential["model"],
            base_url=credential["base_url"],
        )
        store.append_event(
            scan_id,
            "feedback.started",
            message=f"使用模型 {credential['model']} 处理用户反馈",
        )
        return {
            "parent": parent,
            "items": list(scan.get("feedback_items") or []),
            "credential": {
                "api_key": credential["api_key"],
                "base_url": credential["base_url"],
                "model": credential["model"],
            },
            "limits": {
                "max_files": _limit(
                    options.get("max_files"), 1, 200, config.DEFAULT_MAX_FILES
                ),
                "max_model_calls": _limit(
                    options.get("max_model_calls"), 1, 200, config.DEFAULT_MAX_MODEL_CALLS
                ),
                "timeout": _limit(
                    options.get("timeout"), 30, 3600, config.DEFAULT_TIMEOUT
                ),
                "request_timeout": _limit(
                    options.get("request_timeout"),
                    10,
                    600,
                    config.DEFAULT_REQUEST_TIMEOUT,
                ),
                "max_file_chars": _limit(
                    options.get("max_file_chars"),
                    1000,
                    200_000,
                    config.DEFAULT_MAX_FILE_CHARS,
                ),
                "json_mode": bool(options.get("json_mode")),
            },
        }

    async def _fetch_if_needed(self, scan_id: str) -> None:
        scan = store.get(scan_id)
        if scan is None or scan.get("source_kind") != "url":
            return
        if scan.get("status") != "queued":
            raise ScanSetupError("任务状态异常，无法下载仓库")
        try:
            spec = parse_repo_url(
                str(scan.get("repo_url", "")),
                str(scan.get("repo_ref", "")),
                str(scan.get("repo_subdir", "")),
            )
        except RepoError as exc:
            raise ScanSetupError(str(exc)) from exc
        store.update(
            scan_id,
            status="running",
            started_at=utcnow(),
            status_detail=f"正在下载 {spec.label}",
        )
        store.append_event(
            scan_id,
            "repo.fetching",
            message=f"开始下载 {spec.label}",
            data={"repo": spec.label},
        )

        def on_stage(event: str, data: dict) -> None:
            text = {
                "repo.downloading": f"正在下载 {spec.label}",
                "repo.extracting": f"正在解压 {spec.label}",
            }.get(event, "")
            if text:
                store.append_event(
                    scan_id, event, message=text, status_detail=text, data=data
                )

        try:
            files = await fetch_repository(
                spec=spec,
                workspace=Path(scan["workspace_path"]),
                extensions=[str(item) for item in (scan.get("repo_extensions") or [])],
                on_stage=on_stage,
            )
        except RepoError as exc:
            raise ScanSetupError(str(exc)) from exc
        store.update(scan_id, files=files, source_name=spec.label)
        store.append_event(
            scan_id,
            "repo.extracted",
            message=f"仓库源码已准备，共 {len(files)} 个文件",
            data={"files": len(files)},
        )

    def _prepare(self, scan_id: str) -> dict | None:
        scan = store.get(scan_id)
        if scan is None or scan.get("status") not in ("queued", "running"):
            self._pending.pop(scan_id, None)
            return None
        credential = self._pending.pop(scan_id, None)
        if credential is None:
            raise ScanSetupError("模型配置未随任务保留，请重新提交检测")
        retry = {}
        if scan.get("source_kind") == "retry":
            parent = store.get(scan["parent_scan_id"])
            if not parent or not parent.get("report_path"):
                raise ScanSetupError("原始报告不存在，无法重试失败文件")
            retry = {"retry_report": Path(parent["report_path"]), "retry_paths": scan["retry_paths"]}
        options = scan.get("options") or {}
        store.update(
            scan_id,
            status="running",
            started_at=scan.get("started_at") or utcnow(),
            status_detail="正在启动检测",
            model_name=credential["model"],
            base_url=credential["base_url"],
        )
        store.append_event(
            scan_id,
            "scan.started",
            message=f"使用模型 {credential['model']} 启动检测",
        )
        return {
            "workspace": Path(scan["workspace_path"]),
            "retry": retry,
            "language": scan["language"],
            "defect_types": list(scan.get("defect_types") or []),
            "credential": {
                "api_key": credential["api_key"],
                "base_url": credential["base_url"],
                "model": credential["model"],
            },
            "limits": {
                "max_files": _limit(
                    options.get("max_files"), 1, 200, config.DEFAULT_MAX_FILES
                ),
                "max_model_calls": _limit(
                    options.get("max_model_calls"), 1, 200, config.DEFAULT_MAX_MODEL_CALLS
                ),
                "timeout": _limit(
                    options.get("timeout"), 30, 3600, config.DEFAULT_TIMEOUT
                ),
                "request_timeout": _limit(
                    options.get("request_timeout"),
                    10,
                    600,
                    config.DEFAULT_REQUEST_TIMEOUT,
                ),
                "max_file_chars": _limit(
                    options.get("max_file_chars"),
                    1000,
                    200_000,
                    config.DEFAULT_MAX_FILE_CHARS,
                ),
                "json_mode": bool(options.get("json_mode")),
            },
        }

    def _on_event(self, scan_id: str, event: str, data: dict) -> None:
        message = EVENT_MESSAGES.get(event, "")
        if event == "model.file_completed":
            path = str(data.get("path", ""))
            count = int(data.get("findings", 0) or 0)
            message = f"已审查 {path}，候选缺陷 {count} 个"
        elif event == "model.package_completed":
            files = int(data.get("files", 0) or 0)
            count = int(data.get("findings", 0) or 0)
            message = f"已审查 {files} 个文件，候选缺陷 {count} 个"
        elif event == "scan.prepared":
            message = f"已采集 {int(data.get('total_files', 0) or 0)} 个文件，开始调用模型"
        elif event == "feedback.prepared":
            message = f"反馈任务已准备，涉及 {int(data.get('total_files', 0) or 0)} 个文件"
        elif event == "model.file_repaired":
            message = f"已处理反馈文件 {data.get('path', '')}（{data.get('status', '')}）"
        elif event == "review.file_completed":
            message = f"反馈复核完成：{data.get('path', '')}（{data.get('outcome', '')}）"
        if not message:
            return
        safe_data = {
            key: value
            for key, value in data.items()
            if key in (
                "path",
                "paths",
                "files",
                "findings",
                "status",
                "outcome",
                "round",
                "total_files",
                "snapshot_id",
                "run_id",
            )
        }
        safe_data = json.loads(json.dumps(safe_data, ensure_ascii=False, default=str))
        try:
            scan = store.get(scan_id)
            if scan is None:
                return
            if event in ("scan.prepared", "feedback.ready"):
                total = int(data.get("total_files", 0) or 0)
                store.append_event(
                    scan_id,
                    event,
                    message=message,
                    data=safe_data,
                    total_files=total,
                    status_detail=(
                        f"待处理 {total} 个反馈文件"
                        if event == "feedback.ready"
                        else f"待审查 {total} 个文件"
                    ),
                )
            elif event == "review.file_completed":
                total = int(scan.get("total_files", 0) or 0)
                completed = min(total, int(scan.get("completed_files", 0) or 0) + 1)
                store.append_event(
                    scan_id,
                    event,
                    message=message,
                    data=safe_data,
                    status_detail=f"已复核 {completed}/{total} 个反馈文件",
                    completed_delta=1,
                )
            elif event == "model.file_completed":
                total = int(scan.get("total_files", 0) or 0)
                completed = min(total, int(scan.get("completed_files", 0) or 0) + 1)
                store.append_event(
                    scan_id,
                    event,
                    message=message,
                    data=safe_data,
                    status_detail=f"已审查 {completed}/{total} 个文件",
                    completed_delta=1,
                )
            elif event == "model.package_completed":
                total = int(scan.get("total_files", 0) or 0) or int(
                    data.get("files", 0) or 0
                )
                completed = int(scan.get("completed_files", 0) or 0)
                store.append_event(
                    scan_id,
                    event,
                    message=message,
                    data=safe_data,
                    status_detail=f"已审查 {total} 个文件",
                    completed_delta=max(0, total - completed),
                )
            else:
                store.append_event(scan_id, event, message=message, data=safe_data)
        except Exception:  # noqa: BLE001 - progress persistence is best effort
            pass

    def _ingest(self, scan_id: str, outcome: dict) -> None:
        result = outcome["result"]
        scan = store.get(scan_id)
        if scan is None:
            return
        status = str(result.get("status", "failed"))
        if status not in TERMINAL:
            status = "failed"
        feedback_mode = scan.get("source_kind") == "feedback"
        status_detail = {
            "succeeded": "反馈处理完成" if feedback_mode else "检测完成",
            "partial": "部分完成，存在未处理反馈或错误" if feedback_mode else "部分完成，存在未审查文件或错误",
            "failed": "反馈处理失败" if feedback_mode else "检测失败",
            "cancelled": "任务已取消",
        }[status]
        usage = result.get("usage") or {}
        duration = float(usage.get("duration_seconds", 0) or 0)
        if duration <= 0:
            duration = float(outcome.get("elapsed_seconds", 0) or 0)
        coverage = result.get("coverage") or {}
        errors = result.get("errors") or []
        tokens = outcome.get("token_usage") or {}
        fields = {
            "status": status,
            "status_detail": status_detail,
            "framework_run_id": str(result.get("run_id", "")),
            "skill_id": str(result.get("skill_id", scan.get("skill_id", ""))),
            "skill_version": str(result.get("skill_version", scan.get("skill_version", ""))),
            "finding_count": len(result.get("findings") or []),
            "model_calls": int(usage.get("model_calls", 0) or 0),
            "prompt_tokens": int(tokens.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(tokens.get("completion_tokens", 0) or 0),
            "total_tokens": int(tokens.get("total_tokens", 0) or 0),
            "duration_seconds": duration,
            "coverage": coverage,
            "errors": errors,
            "report_path": outcome.get("report_path", ""),
            "output_dir": outcome.get("output_dir", scan.get("output_dir", "")),
            "feedback_summary": outcome.get("feedback_summary"),
            "finished_at": utcnow(),
            "error_code": "",
            "error_message": "",
        }
        if status != "succeeded" and errors:
            fields["error_code"] = str(errors[0].get("code", ""))[:64]
            fields["error_message"] = str(errors[0].get("message", ""))[:500]
        if scan.get("source_kind") == "retry" and coverage.get("file_reviews"):
            rows = coverage["file_reviews"]
            fields["total_files"] = len(rows)
            fields["completed_files"] = sum(row["status"] == "succeeded" for row in rows)
        known_paths = [str(item.get("path", "")) for item in (scan.get("files") or [])]
        findings = []
        for finding in result.get("findings") or []:
            locations = finding.get("locations") or [{}]
            location = locations[0] if locations else {}
            raw_path = str(location.get("path", ""))[:512]
            findings.append(
                {
                    "finding_key": str(finding.get("id", ""))[:64],
                    "defect_type": str(finding.get("defect_type", ""))[:64],
                    "title": str(finding.get("title", ""))[:255],
                    "description": str(finding.get("description", "")),
                    "severity": str(finding.get("severity", "unknown"))[:16],
                    "path": _resolve_finding_path(raw_path, known_paths)[:512],
                    "start_line": int(location.get("start_line", 1) or 1),
                    "end_line": int(
                        location.get("end_line") or location.get("start_line", 1) or 1
                    ),
                    "evidence": finding.get("evidence") or [],
                    "verification": finding.get("verification") or {},
                    "properties": finding.get("properties") or {},
                }
            )
        store.replace_findings(scan_id, findings, **fields)
        store.append_event(
            scan_id,
            "scan.finished",
            level="info" if status == "succeeded" else "warn",
            message=status_detail,
            data={"status": status, "findings": len(findings)},
        )

    def _mark_failed(self, scan_id: str, message: str) -> None:
        scan = store.get(scan_id)
        if scan is None or scan.get("status") in TERMINAL:
            return
        store.update(
            scan_id,
            status="failed",
            status_detail="反馈处理失败" if scan.get("source_kind") == "feedback" else "检测失败",
            error_code=scan.get("error_code") or "TASK_ERROR",
            error_message=message[:500],
            finished_at=utcnow(),
        )
        store.append_event(
            scan_id,
            "scan.failed",
            level="error",
            message=message[:500],
        )

    def _mark_cancelled(self, scan_id: str) -> None:
        scan = store.get(scan_id)
        if scan is None or scan.get("status") in TERMINAL:
            return
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

    def recover_stale(self) -> None:
        for scan in store.all():
            if scan.get("status") not in ("queued", "running"):
                continue
            store.update(
                scan["id"],
                status="failed",
                status_detail="服务重启，任务已中断",
                error_code="SERVER_RESTART",
                error_message="后端服务重启，未完成的检测已终止，请重新提交",
                finished_at=utcnow(),
            )
            store.append_event(
                scan["id"],
                "scan.failed",
                level="error",
                message="后端服务重启，未完成的检测已终止",
            )


manager = ScanJobManager()
