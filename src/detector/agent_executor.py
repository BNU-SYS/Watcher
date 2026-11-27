"""Review one Agent Skill package in one model call, using the shared workflow."""

import json
from time import monotonic

from pydantic import ValidationError

from .contracts import (
    AgentModelAnalysis, Coverage, DetectionRequest, DetectionResult, ErrorRecord, Usage,
)
from .executor import DirectModelExecutor
from .model import ModelError
from .protocols import ExecutionContext
from .skills import LoadedSkill


class AgentSkillExecutor(DirectModelExecutor):
    """Reuse source storage and finding conversion for package-wide analysis."""

    analysis_mode = "agent-skill"

    def _package_prompt(self) -> str:
        """Combine file paths and explicitly numbered lines for the user message."""
        parts = []
        for source in self.snapshot.files:
            numbered = "\n".join(f"{number}: {line}"
                                 for number, line in enumerate(source.text.splitlines(), start=1))
            parts.append(f"=== {json.dumps(source.path, ensure_ascii=False)} ===\n"
                         + numbered)
        return "\n\n".join(parts)

    def _check_package_locations(self, analysis: AgentModelAnalysis, request: DetectionRequest) -> None:
        """Reject paths outside the captured package and invalid types or lines."""
        sources = {source.path: source for source in self.snapshot.files}
        for finding in analysis.findings:
            if finding.path not in sources:
                raise ValueError("model returned a file outside the captured package")
            if finding.defect_type not in request.scope.defect_types:
                raise ValueError("model returned an unrequested defect type")
            if not finding.start_line <= finding.end_line <= len(sources[finding.path].text.splitlines()):
                raise ValueError("model returned a location outside the supplied file")

    async def run(
        self, skill: LoadedSkill, request: DetectionRequest, context: ExecutionContext,
    ) -> DetectionResult:
        """Submit all captured files once and normalize to the existing report."""
        if context.model is None:
            raise ValueError("AgentSkillExecutor requires a model service")
        if request.repository.snapshot_id != self.snapshot.snapshot_id or \
                request.repository.root != str(self.snapshot.root):
            raise ValueError("request does not match the captured source snapshot")
        self.usage = Usage()
        self.artifacts = []
        started = monotonic()
        errors = list(self.snapshot.errors)
        limitations = []
        findings = []
        completed = 0
        try:
            sources = self._save_sources(skill, context)
            context.cancellation.raise_if_cancelled()
            if not self.snapshot.files:
                errors.append(ErrorRecord(code="NO_SOURCE_FILES", message="No readable Skill files were captured"))
            elif request.budget.max_model_calls is not None and request.budget.max_model_calls < 1:
                errors.append(ErrorRecord(code="BUDGET_EXCEEDED", message="No model call budget remains"))
            else:
                user = self._package_prompt()
                self.artifacts.append(context.artifacts.write_text("model/package-input.txt", user))
                try:
                    self.usage.model_calls += 1
                    raw = await context.model.complete(system=skill.instructions, user=user)
                    response = context.artifacts.write_text("model/package.txt", raw)
                    self.artifacts.append(response)
                    analysis = AgentModelAnalysis.model_validate_json(raw)
                    self._check_package_locations(analysis, request)
                except ModelError as exc:
                    errors.append(ErrorRecord(code="MODEL_REQUEST_FAILED", message=f"Skill package: {exc}"))
                except (ValidationError, ValueError):
                    errors.append(ErrorRecord(code="INVALID_MODEL_OUTPUT",
                        message="Skill package: invalid JSON, file path, defect type, or line range"))
                else:
                    captured = {source.path: source for source in self.snapshot.files}
                    for candidate in analysis.findings:
                        findings.append(self._finding(candidate, captured[candidate.path],
                            sources[candidate.path], response, f"finding-{len(findings) + 1}", skill))
                    limitations.extend(analysis.limitations)
                    completed = len(self.snapshot.files)
                    context.events.emit("model.package_completed", {
                        "run_id": request.run_id, "attempt": request.attempt,
                        "files": completed, "findings": len(findings),
                    })
        finally:
            self.usage.duration_seconds = monotonic() - started
        limitations.extend(error.message for error in errors)
        return DetectionResult(
            run_id=request.run_id, attempt=request.attempt, skill_id=request.skill_id,
            skill_version=request.skill_version, snapshot_id=request.repository.snapshot_id,
            status="succeeded" if not errors else ("partial" if completed else "failed"),
            findings=findings, artifacts=self.artifacts, errors=errors,
            coverage=Coverage(
                scope_description=f"Model reviewed {completed}/{len(self.snapshot.files)} captured Skill files in one package",
                limitations=limitations), usage=self.usage,
        )
