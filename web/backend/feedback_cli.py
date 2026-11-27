"""Terminal user feedback entry point.

Usage:
    python backend/feedback_cli.py --user-feedback --report <result.json>
        [--base-url URL] [--model NAME] [--api-key KEY]

The interaction is the framework's own feedback loop: report numbers, 1/2/3,
M for an omission, R to submit the batch, Q to exit.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from app import config
from app.catalog import ensure_framework_path
from app.feedback_runner import execute_feedback


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Watcher user feedback.")
    parser.add_argument(
        "--user-feedback",
        action="store_true",
        required=True,
        help="required: enter the framework user-feedback loop",
    )
    parser.add_argument("--report", type=Path, required=True, help="saved result.json")
    parser.add_argument("--base-url", help="model API root; default from the report")
    parser.add_argument("--model", help="model name; default from the report")
    parser.add_argument("--api-key", help="API key; default from WATCHER_API_KEY")
    parser.add_argument("--request-timeout", type=int, default=config.DEFAULT_REQUEST_TIMEOUT)
    return parser


def _event_sink(event: str, data: dict) -> None:
    message = {
        "feedback.ready": "反馈任务已准备",
        "model.file_repaired": "模型已处理反馈文件",
        "review.file_completed": "反馈复核完成",
        "feedback.finished": "反馈处理结束",
    }.get(event)
    if message:
        detail = data.get("path") or data.get("status") or ""
        print(f"[feedback] {message} {detail}".rstrip())


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    ensure_framework_path()

    from detector.feedback import FeedbackSession, interactive_feedback
    from detector.skills import SkillRegistry

    session = FeedbackSession(args.report, SkillRegistry())
    model = args.model or session.run.get("model") or os.environ.get("WATCHER_MODEL")
    base_url = (
        args.base_url
        or session.run.get("base_url")
        or os.environ.get("WATCHER_BASE_URL")
    )
    api_key = args.api_key or os.environ.get("WATCHER_API_KEY")
    if not model or not base_url or not api_key:
        parser.error(
            "需要模型名、根地址和 API Key：用参数传入，或设置 WATCHER_MODEL、"
            "WATCHER_BASE_URL、WATCHER_API_KEY"
        )

    while True:
        batch = interactive_feedback(session)
        if batch is None:
            return 0

        parent = {
            "report_path": str(session.report),
            "language": session.run.get("language"),
            "source_kind": (
                "feedback" if session.run.get("mode") == "feedback" else "upload"
            ),
        }
        outcome = asyncio.run(
            execute_feedback(
                parent=parent,
                items=[item.model_dump(exclude_none=True) for item in batch.items],
                credential={"api_key": api_key, "base_url": base_url, "model": model},
                limits={
                    "timeout": session.request.budget.wall_time_seconds,
                    "request_timeout": args.request_timeout,
                    "json_mode": bool(session.run.get("json_mode", False)),
                },
                sink=_event_sink,
            )
        )
        result = outcome["result"]
        print(
            f"Status: {result.get('status')}; "
            f"findings: {len(result.get('findings') or [])}"
        )
        print(f"Report: {outcome['report_path']}")
        if result.get("status") not in ("succeeded", "partial"):
            return 1
        session = FeedbackSession(Path(outcome["report_path"]), SkillRegistry())


if __name__ == "__main__":
    raise SystemExit(main())
