"""Command-line entry point for direct-model defect detection."""

import argparse
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import sys
from uuid import uuid4

import httpx

from .contracts import Budget, Coverage, DetectionRequest, DetectionResult, ErrorRecord, RepoSnapshot, Scope
from .agent_executor import AgentSkillExecutor
from .executor import DirectModelExecutor
from .model import ChatModel
from .prescreen import CwePrescreener
from .review import ModelReviewer
from .protocols import ExecutionContext
from .discovery import default_include, discover_agent_skill_packages, resolve_skill
from .services import JsonEvents, LocalArtifacts, TaskCancellation
from .skills import SkillRegistry
from .sources import collect_sources
from .workflow import DetectionWorkflow
from .feedback import rule_fingerprints
from .repositories import clone_repository, parse_target, remove_repository

DEFAULT_MODEL = "gpt-5.5"  # Used when no model is supplied through arguments or environment.
DEFAULT_BASE_URL = "https://aihubmix.com/v1"
API_KEY = os.environ.get("ICODE_API_KEY", "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()


def positive_int(value: str) -> int:
    """Require a positive integer for command-line limits."""
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def review_round_limit(args: argparse.Namespace) -> int | None:
    """Validate review controls; None means loop within the shared execution budget."""
    if (args.max_review_rounds is not None or args.review_until_pass) and not args.model_review:
        raise ValueError("--max-review-rounds and --review-until-pass require --model-review")
    if args.max_review_rounds is not None and args.review_until_pass:
        raise ValueError("--max-review-rounds and --review-until-pass are mutually exclusive")
    return None if args.review_until_pass else (args.max_review_rounds or 1)


def default_calls_per_file(args: argparse.Namespace, *, automatic: bool) -> int:
    """Reserve complete detection/review pairs for a finite round limit."""
    rounds = review_round_limit(args)
    if rounds is None:
        raise ValueError("Until-pass has no automatic call budget; it uses an optional explicit cap")
    detailed = 2 * rounds if args.model_review else 1
    return int(automatic) + detailed


def build_parser() -> argparse.ArgumentParser:
    """Define the minimal tool entry point and explicit model configuration."""
    parser = argparse.ArgumentParser(description="Detect source defects with a Skill and a language model.",
        epilog="Interactive feedback on a saved report: python -m detector feedback --report PATH/result.json")
    parser.add_argument("target", type=parse_target,
                        help="Local source/Agent Skill path, or an HTTPS Git repository URL")
    parser.add_argument("--branch", help="Branch to shallow-clone; URL inputs only; default: remote default branch")
    parser.add_argument("--clone-dir", type=Path,
                        help="Clone directory, removed after detection; URL inputs only; default: ./repos/<repository>")
    parser.add_argument("--clone-timeout", type=positive_int,
                        help="Repository acquisition timeout in seconds; URL inputs only; default: 300")
    parser.add_argument("--language", help="Language override, especially for mixed-language projects")
    parser.add_argument("--model", default=os.environ.get("ICODE_MODEL", "").strip() or DEFAULT_MODEL,
                        help=f"Model name; default: ICODE_MODEL or {DEFAULT_MODEL}")
    parser.add_argument("--base-url", default=os.environ.get("ICODE_BASE_URL",DEFAULT_BASE_URL),
                        help="Chat Completions API root, including /v1 when required")
    parser.add_argument("--json-mode", action="store_true", help="Request JSON mode if the provider supports it")
    parser.add_argument("--model-review", action="store_true",
                        help="Review source findings once by default; model agreement is not independent verification")
    parser.add_argument("--user-feedback", action="store_true",
                        help="After source detection, collect feedback repeatedly; each batch executes and reviews once; Q exits")
    review_limits = parser.add_mutually_exclusive_group()
    review_limits.add_argument("--max-review-rounds", type=positive_int,
                              help="Review round cap, including the initial review; requires --model-review")
    review_limits.add_argument("--review-until-pass", action="store_true",
                              help="Review until pass within timeout; without --max-model-calls, calls are unlimited; requires --model-review")
    parser.add_argument("--include", action="append", help="Source glob; repeatable, defaults to the selected language")
    parser.add_argument("--exclude", action="append", default=[], help="Excluded source glob; repeatable")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--defect-type", action="append", help="Requested defect type; repeatable, skips CWE prescreen")
    selection.add_argument("--all-defect-types", action="store_true", help="Review all Skill types without CWE prescreen")
    parser.add_argument("--cwe-top-k", type=positive_int,
                        help="Per-file type limit for prescreen and review rework; default: 3; required revisions are preserved")
    parser.add_argument("--output", type=Path, default=Path(".detector"), help="Parent output directory")
    parser.add_argument("--max-files", type=positive_int,
                        help="Matching-file cap; source default: all matching files; Agent Skill default: 20")
    parser.add_argument("--max-file-chars", type=positive_int, default=30000)
    parser.add_argument("--max-model-calls", type=positive_int,
                        help="Total call cap; source default: files and stages/rounds, or unlimited with --review-until-pass; Agent Skill default: file cap")
    parser.add_argument("--timeout", type=positive_int, default=300, help="Overall workflow timeout in seconds")
    parser.add_argument("--request-timeout", type=positive_int, default=60, help="HTTP timeout in seconds")
    return parser


def build_feedback_parser() -> argparse.ArgumentParser:
    """Define the command for interactive feedback on a saved source report."""
    parser = argparse.ArgumentParser(prog="python -m detector feedback",
        description="Open a saved source report for interactive feedback; Q exits.")
    parser.add_argument("--report", type=Path, required=True,
                        help="Saved result.json with its companion files; select the latest batch to continue it")
    parser.add_argument("--model", help="Override the model saved with the report")
    parser.add_argument("--base-url", help="Override the API root saved with the report")
    parser.add_argument("--json-mode", action=argparse.BooleanOptionalAction, default=None,
                        help="Override the report's JSON mode setting")
    parser.add_argument("--timeout", type=positive_int,
                        help="Per-batch timeout in seconds; default: the saved report's workflow timeout")
    parser.add_argument("--request-timeout", type=positive_int, default=60,
                        help="HTTP timeout in seconds; default: 60")
    return parser


async def run_feedback(args: argparse.Namespace) -> int:
    """Load saved report settings and start the interactive feedback loop."""
    from .feedback import FeedbackSession

    session = FeedbackSession(args.report, SkillRegistry())
    args.model = args.model or session.run.get("model") or os.environ.get("ICODE_MODEL") or DEFAULT_MODEL
    args.base_url = args.base_url or session.run.get("base_url") or os.environ.get("ICODE_BASE_URL") or DEFAULT_BASE_URL
    if args.json_mode is None:
        args.json_mode = bool(session.run.get("json_mode", False))
    if args.timeout is None:
        args.timeout = session.request.budget.wall_time_seconds
    return await _user_feedback_loop(args, session.report, session=session)


async def _run_feedback_batch(args: argparse.Namespace, session, batch, output: Path):
    """Execute and review one submitted batch with its own budget and saved report."""
    registry = SkillRegistry()
    registry.register(session.skill.directory)
    session.set_feedback(batch)
    count = len(session.tasks)
    cap = count * 2
    request = session.request.model_copy(deep=True)
    request.run_id = "run-" + uuid4().hex
    request.attempt = 1
    request.scope.defect_types = list(dict.fromkeys([
        *request.scope.defect_types, *(kind for task in session.tasks.values() for kind in task.defect_types)]))
    request.budget = Budget(wall_time_seconds=args.timeout, max_model_calls=cap)
    request = DetectionRequest.model_validate(request.model_dump(mode="python"))
    print(f"Feedback files: {count}; review: 1 round; call cap: {cap} (new batch budget)")
    for path, task in session.tasks.items():
        print(f"{path}: targets={task.finding_ids}; defect_types={task.defect_types}")
    output = output.resolve()
    if output.is_relative_to(session.root):
        raise ValueError("Feedback output must be outside the original attempt directory")
    output.mkdir(parents=True, exist_ok=False)
    artifacts = LocalArtifacts(output)
    artifacts.write_text("request.json", request.model_dump_json(indent=2))
    artifacts.write_text("run.json", json.dumps({
        "mode": "feedback", "model": args.model, "base_url": args.base_url,
        "language": session.run.get("language"), "json_mode": args.json_mode,
        "definition_sha256": session.skill.definition_sha256, "model_review": True,
        "max_review_rounds": 1, "review_until_pass": False,
        "parent_report_sha256": session.report_sha256,
        **({"repository_origin": session.run["repository_origin"]} if "repository_origin" in session.run else {}),
    }, ensure_ascii=False, indent=2))
    executor = DirectModelExecutor(session.snapshot)
    reviewer = ModelReviewer(executor, max_rounds=1)
    async with httpx.AsyncClient(timeout=args.request_timeout, follow_redirects=False) as client:
        model = ChatModel(client, base_url=args.base_url, model=args.model, api_key=API_KEY, json_mode=args.json_mode)
        context = ExecutionContext(model=model, artifacts=artifacts, events=JsonEvents(output / "events.jsonl"),
                                   cancellation=TaskCancellation(), round_layout=True)
        workflow = DetectionWorkflow(registry, executor, reviewer=reviewer, feedback=session)
        try:
            result = await workflow.run(request, context)
        except (asyncio.CancelledError, Exception) as exc:
            code = "CANCELLED" if isinstance(exc, asyncio.CancelledError) else (
                "TIMEOUT" if isinstance(exc, TimeoutError) else "EXECUTION_FAILED")
            if executor.result is not None:
                session.save_summary(executor, reviewer, context)
            result = failure_result(request, executor, code, executor.result)
            if not artifacts.path("result.json").exists():
                artifacts.write_text("result.json", result.model_dump_json(indent=2, exclude={"coverage": {"model_reviews"}}))
    for outcome in session.outcomes.values():
        print(f"{outcome['feedback']['id']}: {outcome['status']}; {outcome['reason'] or ''}")
    print(f"Status: {result.status}; candidate findings: {len(result.findings)}; model calls: {result.usage.model_calls}")
    if result.status != "succeeded":
        for error in result.errors:
            print(f"{error.code}: {error.message}", file=sys.stderr)
    print(f"Report: {output / 'result.json'}")
    return result


async def _user_feedback_loop(args: argparse.Namespace, report: Path, *, session=None) -> int:
    """Show every current finding, process submitted batches, and stop on Q or EOF."""
    from .feedback import FeedbackSession, interactive_feedback

    session = session or FeedbackSession(report, SkillRegistry())
    report = session.report
    if session.run.get("mode") == "feedback":
        output_root = report.parent.parent.parent
        if output_root.name != "user-feedback" or not re.fullmatch(r"feedback-[0-9]+", report.parent.parent.name):
            raise ValueError("A feedback report must remain under user-feedback/feedback-NNNN/attempt-1/")
    else:
        output_root = report.parent.parent / "user-feedback"
    number = max((int(path.name[9:]) for path in output_root.glob("feedback-*")
                  if re.fullmatch(r"feedback-[0-9]+", path.name)), default=0)
    while True:
        print(f"\nCurrent report: {report}")
        batch = interactive_feedback(session)
        if batch is None:
            print(f"User feedback ended; saved report: {report}")
            return 130 if session.previous.status == "cancelled" else (0 if session.previous.status == "succeeded" else 1)
        number += 1
        output = output_root / f"feedback-{number:04d}" / "attempt-1"
        result = await _run_feedback_batch(args, session, batch, output)
        report = output / "result.json"
        if result.status == "cancelled":
            return 130
        session = FeedbackSession(report, SkillRegistry())


def failure_result(request: DetectionRequest, executor: DirectModelExecutor, code: str,
                   previous: DetectionResult | None = None, *, model_review: bool = False) -> DetectionResult:
    """Create an honest incomplete report when execution aborts outside a file call."""
    if previous is not None:
        previous.status = "cancelled" if code == "CANCELLED" else "partial"
        message = "Execution stopped before completion; inspect saved findings, execution states and artifacts"
        previous.errors.append(ErrorRecord(code=code, message=message))
        previous.coverage.limitations.append(message)
        return previous.final_report() if model_review else previous
    return DetectionResult(
        run_id=request.run_id, attempt=request.attempt, skill_id=request.skill_id,
        skill_version=request.skill_version, snapshot_id=request.repository.snapshot_id,
        status="cancelled" if code == "CANCELLED" else "failed",
        errors=[ErrorRecord(code=code, message="Execution stopped before a complete validated report was available")],
        artifacts=executor.artifacts,
        coverage=Coverage(scope_description=f"Incomplete {executor.analysis_mode} execution",
                          limitations=["No complete result; inspect the local event log and any saved artifacts"],
                          file_reviews=executor.file_reviews),
        usage=executor.usage,
    )


async def _run_agent_skill_batch(args: argparse.Namespace, packages: list[Path]) -> int:
    """Reuse single-package detection with separate reports and a batch index."""
    target = args.target.resolve()
    model_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", args.model).strip("._-") or "model"
    batch_id = model_name
    output = args.output.resolve() / batch_id
    output.mkdir(parents=True, exist_ok=False)
    results = []
    summary = {"batch_id": batch_id, "target": str(target), "total_packages": len(packages), "results": results}
    if getattr(args, "repository_origin", None):
        summary["repository_origin"] = args.repository_origin
    summary_path = output / "batch.json"

    def save_summary(status: str) -> None:
        counts = {state: sum(row["status"] == state for row in results)
                  for state in ("succeeded", "partial", "failed", "cancelled")}
        summary.update(status=status, processed_packages=len(results), counts=counts,
                       finding_count=sum(row["finding_count"] for row in results),
                       model_calls=sum(row["model_calls"] for row in results))
        temporary = summary_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(summary_path)

    save_summary("running")
    print(f"Agent Skill batch: {len(packages)} packages; index: {summary_path}")
    for index, package in enumerate(packages, start=1):
        relative = package.relative_to(target)
        child_args = argparse.Namespace(**vars(args))
        child_args.target = package
        child_args.language = "agent_skill"
        child_args.output = output / "packages" / relative
        child_args.exclude = list(args.exclude)
        if args.output.resolve().is_relative_to(package):
            # Exclude the entire report tree, including this batch's shared index.
            child_args.exclude.append(args.output.resolve().relative_to(package).as_posix() + "/**")
        row = {"package": relative.as_posix(), "status": "failed", "exit_code": 2,
               "finding_count": 0, "model_calls": 0, "report_path": None}
        print(f"[{index}/{len(packages)}] Package: {relative.as_posix()}")
        try:
            row["exit_code"] = await run_detection(child_args)
            report = next(child_args.output.glob("run-*/attempt-1/result.json"), None)
            if report is not None:
                result = DetectionResult.model_validate_json(report.read_text(encoding="utf-8"))
                row.update(status=result.status, finding_count=len(result.findings),
                           model_calls=result.usage.model_calls,
                           report_path=report.relative_to(output).as_posix())
            else:
                row["error"] = "No report was saved for this package"
        except asyncio.CancelledError:
            row.update(status="cancelled", exit_code=130)
        except (ValueError, OSError, KeyError, httpx.InvalidURL) as exc:
            row.update(status="failed", exit_code=2)
            row["error"] = f"Package could not be processed: {type(exc).__name__}"
            print(f"Package error: {relative.as_posix()}: {type(exc).__name__}", file=sys.stderr)
        results.append(row)
        if row["exit_code"] == 130:
            save_summary("cancelled")
            print(f"Batch report: {summary_path}")
            return 130
        save_summary("running")
    status = "succeeded" if all(row["status"] == "succeeded" for row in results) else (
        "partial" if any(row["status"] in ("succeeded", "partial") for row in results) else "failed")
    save_summary(status)
    print(f"Batch status: {status}; packages: {len(results)}/{len(packages)}; "
          f"candidate findings: {summary['finding_count']}; model calls: {summary['model_calls']}")
    print(f"Batch report: {summary_path}")
    return 0 if status == "succeeded" else 1


async def run_detection(args: argparse.Namespace) -> int:
    """Acquire URL inputs and clean their clones after all detection work ends."""
    review_round_limit(args)
    args = argparse.Namespace(**vars(args))
    if isinstance(args.target, str):
        args.target = parse_target(args.target)
    if isinstance(args.target, str):
        args.target, args.repository_origin = await clone_repository(
            args.target, branch=getattr(args, "branch", None), directory=getattr(args, "clone_dir", None),
            timeout=getattr(args, "clone_timeout", None) or 300)
        args.branch = args.clone_dir = args.clone_timeout = None
        try:
            if args.output.resolve().is_relative_to(args.target):
                raise ValueError("For URL inputs, --output must be outside the clone directory so reports survive cleanup")
            return await _run_local_detection(args)
        finally:
            try:
                remove_repository(args.target)
            except (OSError, ValueError) as exc:
                print(f"Clone cleanup failed; inspect {args.target}: {exc}", file=sys.stderr)
    elif any(getattr(args, field, None) is not None for field in ("branch", "clone_dir", "clone_timeout")):
        raise ValueError("--branch, --clone-dir and --clone-timeout only apply to Git repository URLs")
    return await _run_local_detection(args)


async def _run_local_detection(args: argparse.Namespace) -> int:
    """Detect one local target, or dispatch a collection package by package."""
    api_key = API_KEY
    rounds = review_round_limit(args)

    target_root = args.target.resolve() if args.target.is_dir() else args.target.resolve().parent
    output_root = args.output.resolve()
    exclude = list(args.exclude)
    if output_root == target_root:
        raise ValueError("Choose an output subdirectory or a directory outside the source root")
    if output_root.is_relative_to(target_root):
        # Previous reports contain copied source files and must not become new inputs.
        exclude.append(output_root.relative_to(target_root).as_posix() + "/**")
    registry = SkillRegistry()
    skill, language, include = resolve_skill(
        args.target, registry, language=args.language,
        include=args.include, exclude=exclude,
    )
    
    scope = Scope(include=include, exclude=exclude,
                  defect_types=args.defect_type or skill.manifest.defect_types)
    
    if not set(scope.defect_types).issubset(skill.manifest.defect_types):
        raise ValueError("Requested defect types are not supported by the selected Skill")
    if language == "agent_skill" and args.model_review:
        raise ValueError("--model-review currently supports source review only, not Agent Skill packages")
    if language == "agent_skill" and args.user_feedback:
        raise ValueError("--user-feedback currently supports source reports only, not Agent Skill packages")
    if language == "agent_skill" and args.target.is_dir():
        discovery_exclude = ([output_root.relative_to(target_root).as_posix() + "/**"]
                             if output_root.is_relative_to(target_root) else [])
        packages = discover_agent_skill_packages(args.target,
            exclude_dir=[*skill.manifest.exclude_dir, ".detector"], exclude=discovery_exclude)
        if not packages:
            raise ValueError("No Agent Skill packages containing SKILL.md were found in the target directory")
        if output_root in packages:
            raise ValueError("Choose an output subdirectory or a directory outside the Skill packages")
        if packages != [target_root]:
            return await _run_agent_skill_batch(args, packages)
    automatic = language != "agent_skill" and not args.defect_type and not args.all_defect_types
    # Keep the base definition for report fingerprints and later feedback.
    # prepare_tasks composes the selected rules independently for each source.
    top_k = args.cwe_top_k or 3
    print(f"Language: {language}; Skill: {skill.manifest.id}")
    collection_options = {}
    max_files = args.max_files
    if language == "agent_skill":
        max_files = args.max_files if args.max_files is not None else 20
        collection_options = {"exclude_dir": skill.manifest.exclude_dir,
                              "exclude_file": skill.manifest.exclude_file,
                              "allowed_patterns": default_include(language)}
    snapshot = collect_sources(args.target, scope, max_files=max_files, max_file_chars=args.max_file_chars,
                               **collection_options)
    origin = getattr(args, "repository_origin", None)
    if origin and origin["unfetched_submodules"]:
        snapshot = replace(snapshot, errors=(*snapshot.errors, ErrorRecord(
            code="SUBMODULES_NOT_FETCHED", message="Repository submodules were not fetched: "
            + ", ".join(origin["unfetched_submodules"]))))
    file_count = len(snapshot.files)
    if language == "agent_skill":
        max_model_calls = args.max_model_calls if args.max_model_calls is not None else max_files
    else:
        initial_calls = file_count * (int(automatic) + 1 + int(args.model_review))
        max_model_calls = args.max_model_calls
        if max_model_calls is None and not args.review_until_pass:
            max_model_calls = file_count * default_calls_per_file(args, automatic=automatic)
        if max_model_calls is not None and max_model_calls < initial_calls:
            raise ValueError(
                f"Collected {file_count} files; the configured initial stages require {initial_calls} model calls, "
                f"but --max-model-calls is {max_model_calls}. Increase --max-model-calls or reduce --max-files.")
        print(f"Collected files: {file_count}; file limit: {max_files if max_files is not None else 'none'}")
        if any(error.code == "SOURCE_LIMIT" for error in snapshot.errors):
            print("Additional matching files were excluded by --max-files; coverage is incomplete.")
        selection_mode = f"automatic prescreen (top-k {top_k}; full-scope fallback if unavailable)" if automatic else "fixed scope"
        review_mode = ("until pass" if rounds is None else f"at most {rounds} round(s)") if args.model_review else "off"
        print(f"Type selection: {selection_mode}; model review: {review_mode}")
        call_limit = ("unlimited (subject to overall timeout)" if max_model_calls is None else
                      f"{max_model_calls} ({'manual' if args.max_model_calls is not None else 'automatic'})")
        print(f"Initial-stage call allowance: {initial_calls}; total call cap: {call_limit}")
    request = DetectionRequest(
        run_id="run-" + uuid4().hex, skill_id=skill.manifest.id, skill_version=skill.manifest.version,
        repository=RepoSnapshot(root=str(snapshot.root), snapshot_id=snapshot.snapshot_id), scope=scope,
        budget=Budget(wall_time_seconds=args.timeout,
                      max_model_calls=max_model_calls),
    )
    async with httpx.AsyncClient(timeout=args.request_timeout, follow_redirects=False) as client:
        model = ChatModel(client, base_url=args.base_url, model=args.model, api_key=api_key, json_mode=args.json_mode)
        output = args.output.resolve() / request.run_id / "attempt-1"
        output.mkdir(parents=True, exist_ok=False)
        artifacts = LocalArtifacts(output)
        artifacts.write_text("request.json", request.model_dump_json(indent=2))
        artifacts.write_text("run.json", json.dumps({
            "model": args.model, "base_url": args.base_url,
            "mode": "agent-skill" if language == "agent_skill" else "direct-model", "language": language,
            "json_mode": args.json_mode, "definition_sha256": skill.definition_sha256,
            **({"rule_definition_sha256": rule_fingerprints(skill)} if language != "agent_skill" else {}),
            "defect_selection": "prescreen" if automatic else "explicit" if args.defect_type else "all",
            "cwe_top_k": top_k if automatic or args.model_review else None,
            "model_review": args.model_review,
            "max_review_rounds": rounds if args.model_review else 0,
            "review_until_pass": args.review_until_pass,
            **({"user_feedback": True} if args.user_feedback else {}),
            **({"repository_origin": origin} if origin else {}),
        }, ensure_ascii=False, indent=2))
        context = ExecutionContext(model=model, artifacts=artifacts,
                                   events=JsonEvents(output / "events.jsonl"), cancellation=TaskCancellation(),
                                   round_layout=args.model_review)
        executor = AgentSkillExecutor(snapshot) if language == "agent_skill" else DirectModelExecutor(snapshot)
        prescreener = CwePrescreener(snapshot, top_k, executor.usage, executor.artifacts,
                                   reserved_calls_per_file=2 if args.model_review else 1) if automatic else None
        reviewer = ModelReviewer(executor, max_rounds=rounds,
                                 allow_scope_expansion=automatic, top_k=top_k) if args.model_review else None
        workflow = DetectionWorkflow(registry, executor, prescreener, reviewer)
        try:
            result = await workflow.run(request, context)
        except asyncio.CancelledError:
            result = failure_result(request, executor, "CANCELLED", executor.result, model_review=reviewer is not None)
            artifacts.write_text("result.json", result.model_dump_json(
                indent=2, exclude={"coverage": {"model_reviews"}},
            ))
        except Exception as exc:
            code = "TIMEOUT" if isinstance(exc, TimeoutError) else "EXECUTION_FAILED"
            print(f"Execution error: {type(exc).__name__}", file=sys.stderr)
            result = failure_result(request, executor, code, executor.result, model_review=reviewer is not None)
            # Do not overwrite a report if only its post-save event failed.
            if not artifacts.path("result.json").exists():
                artifacts.write_text("result.json", result.model_dump_json(
                    indent=2, exclude={"coverage": {"model_reviews"}},
                ))
        print(f"Status: {result.status}; candidate findings: {len(result.findings)}; "
              f"model calls: {result.usage.model_calls}")
        if result.status != "succeeded":
            print("Detection incomplete; the finding count does not indicate that the code is defect-free.",
                  file=sys.stderr)
            for error in result.errors:
                print(f"{error.code}: {error.message}", file=sys.stderr)
        print(f"Report: {output / 'result.json'}")
    if args.user_feedback and result.status != "cancelled":
        if any(artifact.path == "input-index.json" for artifact in result.artifacts):
            return await _user_feedback_loop(args, output / "result.json")
        print("User feedback unavailable: detection did not save a source snapshot.", file=sys.stderr)
    return 130 if result.status == "cancelled" else (0 if result.status == "succeeded" else 1)


def main(argv: list[str] | None = None) -> int:
    """Return a process exit code without printing credentials or provider bodies."""
    values = list(sys.argv[1:] if argv is None else argv)
    feedback_command = bool(values and values[0] == "feedback")
    parser = build_feedback_parser() if feedback_command else build_parser()
    args = parser.parse_args(values[1:] if feedback_command else values)
    try:
        return asyncio.run(run_feedback(args) if feedback_command else run_detection(args))
    except (ValueError, OSError, KeyError, httpx.InvalidURL) as exc:
        print(f"Cannot start or save detection: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
