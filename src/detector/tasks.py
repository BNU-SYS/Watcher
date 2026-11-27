"""Prepare source execution tasks without calling models or changing reports."""

from dataclasses import dataclass
from typing import Literal

from .contracts import DetectionRequest, DetectionResult, FileRepairTask, Finding
from .skills import LoadedSkill
from .sources import SourceFile, SourceSnapshot


@dataclass(frozen=True)
class FileExecutionTask:
    """One selected file with its rules, model input and current report context."""

    index: int  # Keep artifact numbering tied to the original snapshot order.
    source: SourceFile
    request: DetectionRequest
    skill: LoadedSkill
    user: dict
    before: tuple[Finding, ...] = ()
    repair: FileRepairTask | None = None


@dataclass(frozen=True)
class ExecutionPlan:
    """A fresh set of prepared tasks for one invocation of the execute node."""

    mode: Literal["detection", "repair", "feedback"]
    tasks: tuple[FileExecutionTask, ...]


def prepare_execution_tasks(
    snapshot: SourceSnapshot, skill: LoadedSkill, request: DetectionRequest, *,
    selected_types: dict[str, list[str]] | None = None,
    repairs: dict[str, FileRepairTask] | None = None,
    result: DetectionResult | None = None,
    history: dict[str, list[dict]] | None = None,
    feedback: bool = False,
) -> ExecutionPlan:
    """Normalize initial scopes, review work or feedback into per-file tasks."""
    mode = "feedback" if feedback else "repair" if repairs is not None else "detection"
    if repairs is not None:
        if result is None:
            raise ValueError("repair task preparation requires a prior result")
        if not set(repairs).issubset(source.path for source in snapshot.files):
            raise ValueError("repair task references an uncaptured file")
    findings_by_path = {}
    for finding in result.findings if result is not None else ():
        for path in dict.fromkeys(location.path for location in finding.locations):
            findings_by_path.setdefault(path, []).append(finding)
    tasks = []
    for index, source in enumerate(snapshot.files, 1):
        repair = repairs.get(source.path) if repairs is not None else None
        if repairs is not None and repair is None:
            continue
        kinds = (repair.defect_types if repair is not None else
                 selected_types[source.path] if selected_types is not None else request.scope.defect_types)
        if not set(kinds).issubset(request.scope.defect_types):
            raise ValueError("execution task exceeds the user scope")
        scoped = request.model_copy(deep=True)
        scoped.scope.defect_types = list(kinds)
        file_skill = skill.for_defect_types(kinds)
        before = tuple(findings_by_path.get(source.path, ()))
        user = source_input(source, scoped)
        if repair is not None:
            user.update(
                repair_task=repair.model_dump(mode="json"),
                retained_findings=[finding_context(item) for item in before if item.id not in repair.finding_ids],
                findings_to_repair=[finding_context(item) for item in before if item.id in repair.finding_ids],
                history=history_context((history or {}).get(source.path, [])),
            )
            if feedback:
                user["feedback_ids_to_respond"] = [entry["id"] for entry in repair.feedback]
        tasks.append(FileExecutionTask(index, source, scoped, file_skill, user, before, repair))
    return ExecutionPlan(mode, tuple(tasks))


def source_input(source: SourceFile, request: DetectionRequest) -> dict:
    """Numbered source data shared by execution and independent review inputs."""
    return {
        "path": source.path, "defect_types": list(request.scope.defect_types),
        "options": request.options,
        "source_lines": [{"line": i, "text": line} for i, line in enumerate(source.text.splitlines(), start=1)],
    }


def finding_context(finding: Finding) -> dict:
    """Send the current claim without duplicated excerpts or framework metadata."""
    return {
        "id": finding.id, "defect_type": finding.defect_type,
        "title": finding.title, "description": finding.description, "severity": finding.severity,
        "locations": [{"path": item.path, "start_line": item.start_line,
                       "end_line": item.end_line} for item in finding.locations],
        "explanation": next((item.summary for item in finding.evidence if item.id == "model"), ""),
    }


def history_context(history: list[dict]) -> list[dict]:
    """Summarize all rounds for the model; leave the full audit intact."""
    summaries = []
    # Restored feedback runs already contain compact records from earlier runs.
    restored = [item for item in history if "kind" in item]
    history = [item for item in history if "kind" not in item]
    records = [("repair", item["detection"]) if "detection" in item
               else ("review", {**item["review"], **{
                   key: item[key] for key in ("run_id", "applied") if key in item}}) for item in history]
    summaries.extend(restored)
    for kind, item in records:
        summary = {"kind": kind, "round": item["round"], "status": item["status"]}
        if item.get("run_id"):
            summary["run_id"] = item["run_id"]
        if kind == "review":
            summary.update(
                outcome=item["outcome"],
                assessments=[entry for entry in item["assessments"] if entry["decision"] != "supported"],
                concerns=item["concerns"], scope_concerns=item["scope_concerns"],
                limitations=item["limitations"],
            )
            if item.get("stop_reason"):
                summary["stop_reason"] = item["stop_reason"]
            if "applied" in item:
                summary["applied"] = item["applied"]
        else:
            output = item.get("output", {})
            summary.update(
                repairs=[{key: entry[key] for key in ("finding_id", "action", "reason")}
                         for entry in output.get("repairs", [])],
                new_finding_ids=item.get("new_finding_ids", []),
                limitations=output.get("limitations", []),
            )
            if item.get("task", {}).get("feedback"):
                summary["feedback"] = item["task"]["feedback"]
                summary["feedback_responses"] = output.get("feedback_responses", [])
                summary["application"] = item.get("application", "not_applied")
        summaries.append(summary)
    return summaries
