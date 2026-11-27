"""Retry selected source files and carry validated results into a new report."""

from pathlib import Path
import re

from .contracts import DetectionResult
from .executor import DirectModelExecutor
from .feedback import FeedbackSession, finding_order


class FileRetryExecutor(DirectModelExecutor):
    """Keep the original source snapshot while executing a subset of its file tasks."""

    def __init__(self, parent: FeedbackSession) -> None:
        super().__init__(parent.snapshot)
        self.parent = parent
        self.merged = False
        self._next_id = max((
            int(match[1]) for finding in parent.previous.findings
            if (match := re.fullmatch(r"finding-(\d+)", finding.id))
        ), default=0)

    async def run(self, skill, request, context):
        result = await super().run(skill, request, context)
        return self.merge(result, context)

    def merge(self, result: DetectionResult, context) -> DetectionResult:
        """Replace only successfully rerun file results and preserve their evidence."""
        previous = self.parent.previous
        rerun = {row.path: row for row in result.coverage.file_reviews}
        replaced = {path for path, row in rerun.items() if row.status == "succeeded"}
        carried = [
            finding.model_copy(deep=True) for finding in previous.findings
            if finding.locations[0].path not in replaced
        ]
        referenced = {evidence.artifact_id for finding in carried for evidence in finding.evidence}
        artifacts = {item.path: item for item in result.artifacts}
        remap = {}
        for artifact, raw in self.parent.saved_artifacts:
            if artifact.id not in referenced:
                continue
            copied = artifacts.get(artifact.path) if artifact.path.startswith("sources/") else None
            if copied is None or copied.sha256 != artifact.sha256:
                path = "prior/" + artifact.id + Path(artifact.path).suffix
                copied = artifacts.get(path)
                if copied is None:
                    copied = context.artifacts.write_text(path, raw.decode("utf-8"))
                    result.artifacts.append(copied)
            remap[artifact.id] = copied.id
        for finding in carried:
            for evidence in finding.evidence:
                evidence.artifact_id = remap[evidence.artifact_id]
        result.findings = sorted([*carried, *result.findings], key=finding_order)

        attempted = replaced | {path for path, row in rerun.items() if row.status == "failed"}
        obsolete_errors = {
            error.message for error in previous.errors
            if error.message.partition(": ")[0] in attempted
            or error.code in {"BUDGET_EXCEEDED", "TIMEOUT", "CANCELLED"}
        }
        result.errors = [
            *result.errors,
            *(error for error in previous.errors if error.message not in obsolete_errors),
        ]
        result.coverage.file_reviews = [
            rerun.get(row.path, row) for row in previous.coverage.file_reviews
        ]
        result.coverage.limitations = list(dict.fromkeys([
            *(item for item in previous.coverage.limitations if item not in obsolete_errors),
            *result.coverage.limitations,
        ]))
        completed = sum(row.status == "succeeded" for row in result.coverage.file_reviews)
        total = len(result.coverage.file_reviews)
        result.coverage.scope_description = f"Model reviewed {completed}/{total} captured files"
        if result.status != "cancelled":
            result.status = "succeeded" if not result.errors else "partial" if completed else "failed"
        self.merged = True
        return result
