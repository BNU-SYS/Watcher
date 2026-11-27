"""In-process adapter that feeds a user's API credential into Watcher."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Callable
from uuid import uuid4

import httpx

from . import catalog, config
from .token_usage import TokenUsage, UsageTrackingClient

EventSink = Callable[[str, dict], None]


class ScanInputError(RuntimeError):
    """A problem with the submitted source or options, safe to show to the user."""


class _ScanEvents:
    """Mirror framework events to a JSONL file and the web progress sink."""

    def __init__(self, path: Path, sink: EventSink) -> None:
        self.path = path
        self.sink = sink

    def emit(self, event: str, data: dict) -> None:
        try:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"event": event, **data}, ensure_ascii=False) + "\n")
        except OSError:
            pass
        try:
            self.sink(event, data)
        except Exception:  # noqa: BLE001 - progress must never break detection
            pass


def _failure_result(
    framework, request, executor, code: str, message: str | None = None, *, preserve_files=False,
):
    checkpoint = executor.result if preserve_files and executor.source_artifacts else None
    status = "cancelled" if code == "CANCELLED" else "failed"
    if checkpoint is not None and code == "TIMEOUT" and any(
        row.status == "succeeded" for row in checkpoint.coverage.file_reviews
    ):
        status = "partial"
    message = message or "检测未完成，未生成完整的校验报告"
    return framework["DetectionResult"](
        run_id=request.run_id,
        attempt=request.attempt,
        skill_id=request.skill_id,
        skill_version=request.skill_version,
        snapshot_id=request.repository.snapshot_id,
        status=status,
        findings=checkpoint.findings if checkpoint is not None else [],
        errors=[
            framework["ErrorRecord"](code=code, message=message),
            *(checkpoint.errors if checkpoint is not None else []),
        ],
        artifacts=checkpoint.artifacts if checkpoint is not None else executor.artifacts,
        coverage=framework["Coverage"](
            scope_description=checkpoint.coverage.scope_description if checkpoint is not None else "检测执行未完成",
            limitations=[message, *(checkpoint.coverage.limitations if checkpoint is not None else [])],
            file_reviews=checkpoint.coverage.file_reviews if checkpoint is not None else [],
        ),
        usage=executor.usage,
    )


async def execute_scan(
    *,
    workspace: Path,
    language: str,
    defect_types: list[str],
    credential: dict,
    limits: dict,
    reports_root: Path,
    sink: EventSink,
    retry_report: Path | None = None,
    retry_paths: list[str] | None = None,
) -> dict:
    """Run one detection attempt and return the validated result JSON."""
    started_perf = time.perf_counter()
    catalog.ensure_framework_path()

    from detector.agent_executor import AgentSkillExecutor
    from detector.contracts import (
        Budget,
        Coverage,
        DetectionRequest,
        DetectionResult,
        ErrorRecord,
        RepoSnapshot,
        Scope,
        validate_exchange,
    )
    from detector.discovery import discover_agent_skill_packages, resolve_skill
    from detector.executor import DirectModelExecutor
    from detector.feedback import FeedbackSession, rule_fingerprints
    from detector.model import ChatModel
    from detector.protocols import ExecutionContext
    from detector.retry import FileRetryExecutor
    from detector.services import LocalArtifacts, TaskCancellation
    from detector.skills import SkillRegistry
    from detector.sources import collect_sources
    from detector.workflow import DetectionWorkflow

    framework = {
        "DetectionResult": DetectionResult,
        "ErrorRecord": ErrorRecord,
        "Coverage": Coverage,
    }

    registry = SkillRegistry()
    parent = None
    file_scopes = None
    try:
        if retry_report is None:
            skill, resolved_language, include = resolve_skill(workspace, registry, language=language)
        else:
            retry_report = retry_report.resolve()
            if not retry_report.is_relative_to(config.REPORTS_DIR.resolve()):
                raise ValueError("原始报告路径不在报告目录中")
            parent = FeedbackSession(retry_report, registry)
            if parent.run.get("mode") != "direct-model" or parent.run.get("language") != language:
                raise ValueError("原始报告不支持按文件重试")
            skill, resolved_language, include = parent.skill, language, parent.request.scope.include
            paths = set(retry_paths or [])
            file_scopes = {
                row.path: list(row.defect_types) for row in parent.previous.coverage.file_reviews
                if row.path in paths and row.status in {"failed", "interrupted", "not_run"}
            }
            if not paths or paths != file_scopes.keys() or not paths.issubset(
                source.path for source in parent.snapshot.files
            ):
                raise ValueError("原始报告未保存所选失败文件")
    except (ValueError, KeyError, OSError) as exc:
        raise ScanInputError(f"无法加载 {language} 检测能力：{exc}") from exc

    requested = [code for code in defect_types if code in skill.manifest.defect_types]
    if not requested:
        requested = list(skill.manifest.defect_types)

    agent_skill = resolved_language == "agent_skill"
    if agent_skill:
        skill = skill.for_defect_types(requested)
        registry.replace(skill)
        try:
            packages = discover_agent_skill_packages(
                workspace,
                exclude_dir=[*skill.manifest.exclude_dir, ".detector"],
            )
        except ValueError as exc:
            raise ScanInputError(f"无法识别 Agent Skill 包：{exc}") from exc
        if not packages:
            raise ScanInputError("没有找到包含 SKILL.md 的 Agent Skill 包")
        if len(packages) != 1 or packages[0].resolve() != workspace.resolve():
            raise ScanInputError("一次只能检测一个 Agent Skill 包，请上传包含顶层 SKILL.md 的单个包目录")

    scope = parent.request.scope if parent else Scope(include=include, exclude=[], defect_types=requested)
    sink("scan.collecting", {"language": resolved_language, "skill_id": skill.manifest.id})

    collection_options = {}
    if agent_skill:
        collection_options = {
            "exclude_dir": skill.manifest.exclude_dir,
            "exclude_file": skill.manifest.exclude_file,
        }
    try:
        snapshot = parent.snapshot if parent else collect_sources(
            workspace,
            scope,
            max_files=limits["max_files"],
            max_file_chars=limits["max_file_chars"],
            **collection_options,
        )
    except ValueError as exc:
        message = str(exc)
        if "No source files match" in message:
            extensions = "、".join(skill.manifest.file_extensions.get(resolved_language, []))
            raise ScanInputError(f"没有找到可检测的 {extensions} 文件") from exc
        raise ScanInputError(f"源码采集失败：{message}") from exc

    if not snapshot.files:
        detail = "；".join(error.message for error in snapshot.errors[:3]) or "没有可审查的源码"
        raise ScanInputError(detail)

    sink(
        "scan.prepared",
        {
            "total_files": len(file_scopes) if file_scopes is not None else len(snapshot.files),
            "snapshot_id": snapshot.snapshot_id,
            "skill_id": skill.manifest.id,
        },
    )

    request = DetectionRequest(
        run_id="run-" + uuid4().hex,
        skill_id=skill.manifest.id,
        skill_version=skill.manifest.version,
        repository=RepoSnapshot(root=str(snapshot.root), snapshot_id=snapshot.snapshot_id),
        scope=scope,
        options=parent.request.options if parent else {},
        budget=Budget(
            wall_time_seconds=limits["timeout"],
            max_model_calls=limits["max_model_calls"],
        ),
    )

    output = reports_root / request.run_id / "attempt-1"
    output.mkdir(parents=True, exist_ok=False)
    artifacts = LocalArtifacts(output)
    artifacts.write_text("request.json", request.model_dump_json(indent=2))
    run_meta = {
        "model": credential["model"],
        "base_url": credential["base_url"],
        "mode": "agent-skill" if agent_skill else "direct-model",
        "language": resolved_language,
        "json_mode": limits["json_mode"],
        "skill_id": skill.manifest.id,
        "definition_sha256": skill.definition_sha256,
        "model_review": False,
        "max_review_rounds": 0,
        "review_until_pass": False,
    }
    if not agent_skill:
        run_meta["rule_definition_sha256"] = rule_fingerprints(skill)
    if parent is not None:
        run_meta["parent_report_sha256"] = parent.report_sha256
    artifacts.write_text(
        "run.json",
        json.dumps(run_meta, ensure_ascii=False, indent=2),
    )

    events = _ScanEvents(output / "events.jsonl", sink)
    if parent is not None:
        executor = FileRetryExecutor(parent)
    else:
        executor = AgentSkillExecutor(snapshot) if agent_skill else DirectModelExecutor(snapshot)
    workflow = DetectionWorkflow(registry, executor, initial_file_scopes=file_scopes)

    result = None
    token_usage = TokenUsage()
    async with httpx.AsyncClient(
        timeout=limits["request_timeout"], follow_redirects=False
    ) as client:
        model = ChatModel(
            UsageTrackingClient(client, token_usage),
            base_url=credential["base_url"],
            model=credential["model"],
            api_key=credential["api_key"],
            json_mode=limits["json_mode"],
        )
        context = ExecutionContext(
            model=model,
            artifacts=artifacts,
            events=events,
            cancellation=TaskCancellation(),
        )
        try:
            result = await workflow.run(request, context)
        except asyncio.CancelledError:
            result = _failure_result(
                framework, request, executor, "CANCELLED", "用户取消了检测任务",
                preserve_files=not agent_skill,
            )
        except TimeoutError:
            result = _failure_result(
                framework,
                request,
                executor,
                "TIMEOUT",
                f"检测超过 {limits['timeout']} 秒的总时限",
                preserve_files=not agent_skill,
            )
        except Exception as exc:  # noqa: BLE001 - converted into a failed result below
            detail = " ".join(str(exc).split())[:240] or exc.__class__.__name__
            result = _failure_result(
                framework,
                request,
                executor,
                "EXECUTION_FAILED",
                f"检测执行失败：{detail}",
            )

    report_path = artifacts.path("result.json")
    if not report_path.exists():
        if parent is not None and executor.source_artifacts and not executor.merged:
            result = DetectionResult.model_validate(executor.merge(result, context).model_dump())
            validate_exchange(skill.manifest, request, result)
        artifacts.write_text("result.json", result.model_dump_json(indent=2) + "\n")

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    sink("scan.report_saved", {"report_path": str(report_path)})
    return {
        "result": payload,
        "report_path": str(report_path),
        "output_dir": str(output),
        "token_usage": token_usage.as_dict(),
        "elapsed_seconds": round(time.perf_counter() - started_perf, 3),
    }
