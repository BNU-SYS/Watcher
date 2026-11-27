"""Language-neutral LangGraph orchestration around an injected Skill executor."""

import asyncio
import json
import sys
from dataclasses import replace
from functools import partial
from typing import TypedDict

from jsonschema.validators import validator_for
from langgraph.errors import NodeCancelledError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .contracts import Artifact, DetectionRequest, DetectionResult, FileRepairTask, validate_exchange
from .protocols import ExecutionContext, SkillExecutor
from .prescreen import CwePrescreener
from .review import ModelReviewer
from .skills import LoadedSkill, SkillRegistry
from .tasks import ExecutionPlan, prepare_execution_tasks


class WorkflowState(TypedDict, total=False):
    """Per-invocation data; service objects stay outside graph state."""

    request: DetectionRequest
    skill: LoadedSkill
    result: DetectionResult
    report: Artifact
    selected_types: dict[str, list[str]]
    round_number: int
    repair_tasks: dict[str, FileRepairTask]
    review_paths: list[str]
    execution_plan: ExecutionPlan


class DetectionWorkflow:
    """Run one selected Skill through preflight, execution, validation, and storage."""

    def __init__(
        self, registry: SkillRegistry, executor: SkillExecutor,
        prescreener: CwePrescreener | None = None,
        reviewer: ModelReviewer | None = None,
        feedback=None,
        initial_file_scopes: dict[str, list[str]] | None = None,
    ) -> None:
        """Inject shared dependencies; no language-specific handlers are required."""
        self.registry = registry
        self.executor = executor
        self.prescreener = prescreener
        self.reviewer = reviewer
        self.feedback = feedback
        self.initial_file_scopes = initial_file_scopes

    def build_graph(self, context: ExecutionContext) -> CompiledStateGraph:
        """Compile a graph bound to the services for one execution attempt."""
        builder = StateGraph(WorkflowState)
        builder.add_node("prepare", partial(self._prepare, context=context))
        builder.add_node("prescreen", partial(self._prescreen, context=context))
        builder.add_node("prepare_tasks", partial(self._prepare_tasks, context=context))
        builder.add_node("execute", partial(self._execute, context=context))
        builder.add_node("review", partial(self._review, context=context))
        builder.add_node("validate", partial(self._validate, context=context))
        builder.add_node("save", partial(self._save, context=context))
        builder.add_node("feedback", partial(self._feedback, context=context))
        builder.add_edge(START, "prepare")
        # Package and custom executors retain their own input preparation and run interface.
        execution_entry = "prepare_tasks" if getattr(self.executor, "analysis_mode", None) == "direct-model" else "execute"
        builder.add_conditional_edges("prepare", lambda state: "feedback" if self.feedback else (
            "prescreen" if self.prescreener else execution_entry),
            {"feedback": "feedback", "prescreen": "prescreen", execution_entry: execution_entry})
        builder.add_edge("feedback", "prepare_tasks")
        builder.add_edge("prescreen", "prepare_tasks")
        builder.add_edge("prepare_tasks", "execute")
        builder.add_conditional_edges("execute", lambda state: "review" if self.reviewer else "validate",
                                      {"review": "review", "validate": "validate"})
        builder.add_conditional_edges("review", lambda state: "prepare_tasks" if state["repair_tasks"] else "validate",
                                      {"prepare_tasks": "prepare_tasks", "validate": "validate"})
        builder.add_edge("validate", "save")
        builder.add_edge("save", END)
        return builder.compile()

    async def run(
        self, request: DetectionRequest, context: ExecutionContext,
    ) -> DetectionResult:
        """Run with a wall-time limit; propagate errors without reporting success."""
        # Reparse mutable models so callers cannot bypass input validation.
        request = DetectionRequest.model_validate(request.model_dump(mode="python"))
        if self.reviewer is not None:
            context = replace(context, round_layout=True)
        graph = self.build_graph(context)
        # LangGraph compares its step count with this threshold; infinity removes
        # that cap while the workflow timeout and file stop conditions still apply.
        call_cap = request.budget.max_model_calls
        recursion_limit = float("inf") if call_cap is None else 3 * call_cap + 10
        # Cooperative asyncio timeout cannot terminate blocking code or child processes.
        async with asyncio.timeout(request.budget.wall_time_seconds):
            try:
                state = await graph.ainvoke({"request": request, "round_number": 1},
                                           {"recursion_limit": recursion_limit})
            except NodeCancelledError as exc:
                # LangGraph wraps cancellation raised inside a node.
                raise asyncio.CancelledError(str(exc)) from exc
        return state["result"]

    async def _prepare(self, state: WorkflowState, *, context: ExecutionContext) -> dict:
        """Resolve the Skill and reject incompatible inputs before execution."""
        context.cancellation.raise_if_cancelled()
        request = state["request"]
        skill = self.registry.get(request.skill_id)
        if skill.manifest.version != request.skill_version:
            raise ValueError("request does not match the selected skill version")
        if not set(request.scope.defect_types).issubset(skill.manifest.defect_types):
            raise ValueError("request contains unsupported defect types")
        if skill.options_schema is not None:
            validator = validator_for(skill.options_schema)
            validator.check_schema(skill.options_schema)
            validator(skill.options_schema).validate(request.options)
        context.events.emit("workflow.prepared", self._identity(request))
        return {"skill": skill}

    async def _prescreen(self, state: WorkflowState, *, context: ExecutionContext) -> dict:
        """Rank possible CWEs independently for each file before detailed review."""
        assert self.prescreener is not None
        selected = await self.prescreener.run(state["skill"], state["request"], context)
        return {"selected_types": selected}

    async def _feedback(self, state: WorkflowState, *, context: ExecutionContext) -> dict:
        """Restore the saved result and build per-file targets without another model call."""
        context.cancellation.raise_if_cancelled()
        tasks = self.feedback.initialize(self.executor, self.reviewer, state["request"], context)
        context.events.emit("feedback.prepared", {
            **self._identity(state["request"]), "paths": list(tasks),
        })
        return {"repair_tasks": tasks}

    async def _prepare_tasks(self, state: WorkflowState, *, context: ExecutionContext) -> dict:
        """Select files and assemble rules and context before each source execution."""
        context.cancellation.raise_if_cancelled()
        snapshot = self.executor.snapshot
        selected_types = state.get("selected_types")
        if self.initial_file_scopes is not None and state.get("repair_tasks") is None:
            selected_types = self.initial_file_scopes
            snapshot = replace(snapshot, files=tuple(
                source for source in snapshot.files if source.path in selected_types
            ))
        plan = prepare_execution_tasks(
            snapshot, state["skill"], state["request"],
            selected_types=selected_types, repairs=state.get("repair_tasks"),
            result=self.executor.result,
            history=self.reviewer.history if self.reviewer is not None else None,
            feedback=self.feedback is not None,
        )
        context.events.emit("tasks.prepared", {
            **self._identity(state["request"]), "round": state["round_number"], "mode": plan.mode,
            "files": [{"path": task.source.path, "defect_types": task.request.scope.defect_types,
                       "finding_ids": task.repair.finding_ids if task.repair is not None else []}
                      for task in plan.tasks],
        })
        return {"execution_plan": plan}

    async def _execute(self, state: WorkflowState, *, context: ExecutionContext) -> dict:
        """Run the prepared tasks; execution does not reconstruct their input scope."""
        context.cancellation.raise_if_cancelled()
        if "execution_plan" in state:
            context = replace(context, execution_plan=state["execution_plan"],
                              prescreen_limitations=tuple(self.prescreener.limitations) if self.prescreener else ())
        if self.reviewer is not None:
            context = replace(context, round_number=state["round_number"],
                              file_history=self.reviewer.history)
        # Preserve the original request for the later cross-object validation.
        result = await self.executor.run(
            state["skill"], state["request"].model_copy(deep=True), context,
        )
        update = {"result": result}
        if self.reviewer is not None:
            update["review_paths"] = list(self.reviewer.executor.completed_paths)
        return update

    async def _review(self, state: WorkflowState, *, context: ExecutionContext) -> dict:
        """Review source evidence independently; keep structural validation separate."""
        assert self.reviewer is not None
        validate_exchange(state["skill"].manifest, state["request"], state["result"])
        round_number = state["round_number"]
        tasks = {}
        try:
            tasks = await self.reviewer.run(
                state["skill"], state["request"], state["result"], context,
                round_number=round_number, paths=state.get("review_paths"),
            )
        finally:
            result = state["result"]
            summary = {
                "round": round_number,
                "detection_tasks": {path: task.model_dump(mode="json")
                                    for path, task in state.get("repair_tasks", {}).items()},
                "detected_paths": state.get("review_paths", []),
                "skipped_tasks": dict(self.reviewer.executor.skipped_repairs),
                "files": [row.model_dump(mode="json") for row in result.coverage.model_reviews
                          if row.round == round_number],
                "next_tasks": {path: task.model_dump(mode="json") for path, task in tasks.items()},
                "cumulative_usage": result.usage.model_dump(mode="json"),
            }
            self.reviewer.executor.add_artifact(
                context, f"round-{round_number}/round.json",
                json.dumps(summary, ensure_ascii=False, indent=2),
            )
        return {"result": self.reviewer.result, "round_number": round_number + 1,
                "repair_tasks": tasks}

    async def _validate(self, state: WorkflowState, *, context: ExecutionContext) -> dict:
        """Revalidate returned data and check its identity, references, and budgets."""
        context.cancellation.raise_if_cancelled()
        result = state["result"]
        if self.feedback is not None:
            self.feedback.save_summary(self.executor, self.reviewer, context)
        if not isinstance(result, DetectionResult):
            raise TypeError("SkillExecutor.run must return DetectionResult")
        result = DetectionResult.model_validate(result.model_dump(mode="python"))
        validate_exchange(state["skill"].manifest, state["request"], result)
        if self.reviewer is not None and self.feedback is None:
            result = result.final_report()
        context.events.emit("workflow.validated", self._identity(state["request"]))
        return {"result": result}

    async def _save(self, state: WorkflowState, *, context: ExecutionContext) -> dict:
        """Persist only a validated report in the attempt-scoped artifact service."""
        context.cancellation.raise_if_cancelled()
        report = context.artifacts.write_text(
            "result.json", state["result"].model_dump_json(
                indent=2, exclude={"coverage": {"model_reviews"}},
            ) + "\n",
        )
        try:
            context.events.emit("workflow.saved", {
                **self._identity(state["request"]), "report_path": report.path,
            })
        except OSError:
            # A completed report remains valid if only its final log write fails.
            print("Warning: report saved successfully, but the save event could not be written.",
                  file=sys.stderr)
        # Keep the report outside its own artifact list to avoid a self-referential hash.
        return {"report": report}

    @staticmethod
    def _identity(request: DetectionRequest) -> dict:
        """Attach run and attempt identity to workflow events."""
        return {"run_id": request.run_id, "attempt": request.attempt,
                "skill_id": request.skill_id}
