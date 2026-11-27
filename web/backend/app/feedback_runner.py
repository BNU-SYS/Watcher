"""Run the framework feedback workflow for feedback submitted from the web UI."""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from uuid import uuid4

import httpx

from . import catalog, config
from .detector_runner import EventSink, _failure_result, _ScanEvents
from .token_usage import TokenUsage, UsageTrackingClient


class FeedbackInputError(RuntimeError):
    """Feedback cannot be applied to the selected report."""


def feedback_root(report_path: Path, parent_source_kind: str) -> Path:
    """Match the framework CLI layout so feedback reports stay chainable."""
    if parent_source_kind == "feedback":
        return report_path.parent.parent.parent
    return report_path.parent.parent / "user-feedback"


def next_feedback_number(root: Path) -> int:
    numbers = []
    if root.is_dir():
        for path in root.glob("feedback-*"):
            match = re.fullmatch(r"feedback-([0-9]+)", path.name)
            if match:
                numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def _clean_items(items: list[dict]) -> list[dict]:
    cleaned = []
    for item in items:
        value = {key: item[key] for key in (
            "kind", "reason", "finding_id", "path", "defect_type",
            "start_line", "end_line",
        ) if item.get(key) is not None and item.get(key) != ""}
        cleaned.append(value)
    return cleaned


async def execute_feedback(
    *,
    parent: dict,
    items: list[dict],
    credential: dict,
    limits: dict,
    sink: EventSink,
) -> dict:
    """Load a saved report, submit feedback to the model, and return the new report."""
    started_perf = time.perf_counter()
    report_path = Path(str(parent.get("report_path", ""))).resolve()
    if (
        not report_path.is_file()
        or not report_path.is_relative_to(config.REPORTS_DIR.resolve())
    ):
        raise FeedbackInputError("原始报告文件不存在，无法提交反馈")
    if parent.get("language") == "agent_skill":
        raise FeedbackInputError("Agent Skill 报告暂不支持用户反馈，请对源码报告提交")

    catalog.ensure_framework_path()
    from detector.contracts import (
        Budget,
        Coverage,
        DetectionRequest,
        DetectionResult,
        ErrorRecord,
        FeedbackBatch,
        FeedbackItem,
    )
    from detector.executor import DirectModelExecutor
    from detector.feedback import FeedbackSession
    from detector.model import ChatModel
    from detector.protocols import ExecutionContext
    from detector.review import ModelReviewer
    from detector.services import LocalArtifacts, TaskCancellation
    from detector.skills import SkillRegistry
    from detector.workflow import DetectionWorkflow

    framework = {
        "DetectionResult": DetectionResult,
        "ErrorRecord": ErrorRecord,
        "Coverage": Coverage,
    }

    registry = SkillRegistry()
    try:
        session = FeedbackSession(report_path, registry)
    except (ValueError, OSError) as exc:
        raise FeedbackInputError(f"无法读取原始报告：{exc}") from exc

    try:
        batch = FeedbackBatch(
            report_sha256=session.report_sha256,
            items=[FeedbackItem.model_validate(item) for item in _clean_items(items)],
        )
        session.set_feedback(batch)
    except (ValueError, KeyError) as exc:
        raise FeedbackInputError(f"反馈内容不合法：{exc}") from exc
    if not session.tasks:
        raise FeedbackInputError("反馈没有命中任何可处理文件")

    output_root = feedback_root(report_path, str(parent.get("source_kind", "")))
    number = next_feedback_number(output_root)
    output = output_root / f"feedback-{number:04d}" / "attempt-1"
    output.mkdir(parents=True, exist_ok=False)

    request = session.request.model_copy(deep=True)
    request.run_id = "run-" + uuid4().hex
    request.attempt = 1
    request.scope.defect_types = list(dict.fromkeys([
        *request.scope.defect_types,
        *(kind for task in session.tasks.values() for kind in task.defect_types),
    ]))
    request.budget = Budget(
        wall_time_seconds=int(limits.get("timeout") or config.DEFAULT_TIMEOUT),
        max_model_calls=max(2, len(session.tasks) * 2),
    )
    request = DetectionRequest.model_validate(request.model_dump(mode="python"))

    sink(
        "feedback.ready",
        {"total_files": len(session.tasks), "paths": list(session.tasks)},
    )

    artifacts = LocalArtifacts(output)
    artifacts.write_text("request.json", request.model_dump_json(indent=2))
    artifacts.write_text(
        "run.json",
        json.dumps(
            {
                "mode": "feedback",
                "model": credential["model"],
                "base_url": credential["base_url"],
                "language": session.run.get("language"),
                "json_mode": bool(limits.get("json_mode")),
                "definition_sha256": session.skill.definition_sha256,
                "model_review": True,
                "max_review_rounds": 1,
                "review_until_pass": False,
                "parent_report_sha256": session.report_sha256,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )

    events = _ScanEvents(output / "events.jsonl", sink)
    executor = DirectModelExecutor(session.snapshot)
    reviewer = ModelReviewer(executor, max_rounds=1)
    workflow = DetectionWorkflow(registry, executor, reviewer=reviewer, feedback=session)
    token_usage = TokenUsage()

    async with httpx.AsyncClient(
        timeout=int(limits.get("request_timeout") or config.DEFAULT_REQUEST_TIMEOUT),
        follow_redirects=False,
    ) as client:
        model = ChatModel(
            UsageTrackingClient(client, token_usage),
            base_url=credential["base_url"],
            model=credential["model"],
            api_key=credential["api_key"],
            json_mode=bool(limits.get("json_mode")),
        )
        context = ExecutionContext(
            model=model,
            artifacts=artifacts,
            events=events,
            cancellation=TaskCancellation(),
            round_layout=True,
        )

        def save_partial_summary() -> None:
            if executor.result is None:
                return
            try:
                session.save_summary(executor, reviewer, context)
            except Exception:  # noqa: BLE001 - keep the failure report readable
                pass

        try:
            result = await workflow.run(request, context)
        except asyncio.CancelledError:
            save_partial_summary()
            result = _failure_result(
                framework,
                request,
                executor,
                "CANCELLED",
                "用户取消了反馈任务",
            )
        except TimeoutError:
            save_partial_summary()
            result = _failure_result(
                framework,
                request,
                executor,
                "TIMEOUT",
                f"反馈处理超过 {request.budget.wall_time_seconds} 秒",
            )
        except Exception as exc:  # noqa: BLE001 - saved as a failed feedback report
            save_partial_summary()
            detail = " ".join(str(exc).split())[:240] or exc.__class__.__name__
            result = _failure_result(
                framework,
                request,
                executor,
                "EXECUTION_FAILED",
                f"反馈处理失败：{detail}",
            )

    result_path = artifacts.path("result.json")
    if not result_path.exists():
        artifacts.write_text(
            "result.json",
            result.model_dump_json(indent=2, exclude={"coverage": {"model_reviews"}}),
        )
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    summary_path = artifacts.path("feedback-summary.json")
    summary = None
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    sink("feedback.finished", {"status": payload.get("status", "failed")})
    return {
        "result": payload,
        "report_path": str(result_path),
        "output_dir": str(output),
        "feedback_summary": summary,
        "outcomes": list(session.outcomes.values()),
        "token_usage": token_usage.as_dict(),
        "elapsed_seconds": round(time.perf_counter() - started_perf, 3),
    }
