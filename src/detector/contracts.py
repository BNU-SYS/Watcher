"""Validated data contracts for detection, model responses.

This module contains data and validation only; it does not depend on execution
services. SCHEMA_MODELS lists the three published exchange schemas.
"""

from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


# Shared field constraints; NonEmpty checks length without trimming whitespace.
NonEmpty = Annotated[str, Field(min_length=1)]
FileExtension = Annotated[str, Field(pattern=r"^\.[a-zA-Z0-9_+-]+$")]
Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")]
# Skill IDs use lowercase segments, such as "team.resource-check".
SkillId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")]
Version = Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?$")]
# Accept full Git object IDs or a SHA-256 content snapshot, not branch names.
SnapshotId = Annotated[str, Field(pattern=r"^(?:git:(?:[a-f0-9]{40}|[a-f0-9]{64})|tree:sha256:[a-f0-9]{64})$")]


def relative_path(value: str) -> str:
    """Validate the wire format; runtime must also resolve symlinks and enforce roots."""
    # Use forward slashes on every platform and reject drive-qualified paths.
    if not value or "\\" in value or ":" in value or "\x00" in value:
        raise ValueError("path must be a non-empty POSIX relative path")
    if value.startswith("/") or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("path must not contain absolute, empty, dot or parent components")
    return value


class Contract(BaseModel):
    """Base model for strict, JSON-compatible interface data."""

    # Reject misspelled fields and implicit conversions such as "10" to an integer.
    model_config = ConfigDict(extra="forbid", strict=True)


class ModelReply(BaseModel):
    """Read known model fields without applying unknown annotations or coercing types."""

    model_config = ConfigDict(extra="ignore", strict=True)


def unique_model_items(items, identity):
    """Collapse identical repeated model items; never choose between conflicting entries."""
    unique = {}
    for item in items:
        key = getattr(item, identity)
        if key in unique and item != unique[key]:
            raise ValueError("conflicting repeated model items")
        unique.setdefault(key, item)
    return list(unique.values())


class SkillManifest(Contract):
    """Metadata read from a Skill package's manifest.json."""

    schema_version: Literal["1.0"] = "1.0"  # Interface format version.
    id: SkillId  # Stable registry key, independent of the package directory.
    version: Version  # Version of the Skill's analysis method.
    description: NonEmpty
    owner: NonEmpty
    languages: list[NonEmpty] = Field(min_length=1)  # Open vocabulary for new languages.
    file_extensions: dict[NonEmpty, Annotated[list[FileExtension], Field(min_length=1)]] = Field(default_factory=dict)
    defect_types: list[NonEmpty] = Field(min_length=1)  # CWE or stable custom IDs.
    skill_file: str = "SKILL.md"  # Relative to the Skill package directory.
    options_schema: str | None = None  # Optional package-relative JSON Schema file.
    # A list supplies shared review files; a mapping selects rules by defect type.
    rule_files: list[NonEmpty] | dict[NonEmpty, str] = Field(default_factory=list)
    exclude_dir: list[NonEmpty] = Field(default_factory=list)
    exclude_file: list[FileExtension] = Field(default_factory=list)

    @model_validator(mode="after")
    def extension_languages(self) -> "SkillManifest":
        """Extensions must belong to a language supported by this Skill."""
        if not set(self.file_extensions).issubset(self.languages):
            raise ValueError("file_extensions contains an unsupported language")
        return self

    @field_validator("skill_file", "options_schema")
    @classmethod
    def check_file(cls, value: str | None) -> str | None:
        """Validate package-relative file paths when provided."""
        return relative_path(value) if value is not None else None

    @field_validator("rule_files")
    @classmethod
    def check_rule_files(cls, values: list[str] | dict[str, str]) -> list[str] | dict[str, str]:
        """Rules are explicit package-relative files in either supported format."""
        if isinstance(values, dict):
            return {defect_type: relative_path(path) for defect_type, path in values.items()}
        return [relative_path(value) for value in values]

    @field_validator("exclude_dir")
    @classmethod
    def check_directory_names(cls, values: list[str]) -> list[str]:
        """Directory exclusions match names at any depth, rather than globs."""
        for value in values:
            if "/" in relative_path(value):
                raise ValueError("exclude_dir entries must be directory names")
        return values

    @model_validator(mode="after")
    def rule_file_types(self) -> "SkillManifest":
        """Rule modules may only be declared for manifest-supported defect types."""
        if isinstance(self.rule_files, dict) and not set(self.rule_files).issubset(self.defect_types):
            raise ValueError("rule_files contains an unsupported defect type")
        return self


class RepoSnapshot(Contract):
    """Repository location and fixed revision associated with an analysis."""

    root: NonEmpty  # Absolute path on the machine executing the run.
    snapshot_id: SnapshotId  # Format validation does not verify the actual revision.

    @field_validator("root")
    @classmethod
    def absolute_root(cls, value: str) -> str:
        """Accept absolute Windows or POSIX paths without checking existence."""
        if not (PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute()):
            raise ValueError("repository root must be absolute")
        return value


class Scope(Contract):
    """Requested file patterns and defect types; file matching happens at runtime."""

    include: list[NonEmpty] = Field(default_factory=lambda: ["**/*"], min_length=1)
    exclude: list[NonEmpty] = Field(default_factory=list)
    defect_types: list[NonEmpty] = Field(min_length=1)


class Budget(Contract):
    """Per-attempt limits to be enforced by the execution services."""

    wall_time_seconds: int = Field(default=900, ge=1)
    max_model_calls: int | None = Field(default=10, ge=0)  # None leaves calls unlimited.


class DetectionRequest(Contract):
    """Input for one attempt to run a selected Skill on a repository snapshot."""

    schema_version: Literal["1.0"] = "1.0"
    run_id: Identifier  # Identifies one detection run; retained across retries.
    attempt: int = Field(default=1, ge=1)  # Incremented for each retry of the same run.
    skill_id: SkillId
    skill_version: Version
    repository: RepoSnapshot
    scope: Scope
    budget: Budget = Field(default_factory=Budget)
    options: dict[str, JsonValue] = Field(default_factory=dict)  # Skill-specific settings.


class Location(Contract):
    """Source location with repository-relative paths and one-based line numbers."""

    path: str
    start_line: int = Field(ge=1)
    end_line: int | None = Field(default=None, ge=1)  # Inclusive when supplied.

    @field_validator("path")
    @classmethod
    def check_path(cls, value: str) -> str:
        """Require a portable path relative to the repository root."""
        return relative_path(value)

    @model_validator(mode="after")
    def line_order(self) -> "Location":
        """Reject reversed ranges; actual file length is checked separately."""
        if self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must not precede start_line")
        return self


class Artifact(Contract):
    """Reference to a saved output file, such as a log or evidence excerpt."""

    id: Identifier  # Unique within one DetectionResult.
    path: str  # Relative to this attempt's artifact directory, not the repository.
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]  # Digest of the file bytes.
    media_type: NonEmpty = "text/plain"

    @field_validator("path")
    @classmethod
    def check_path(cls, value: str) -> str:
        """Require a portable path relative to the artifact directory."""
        return relative_path(value)


class Evidence(Contract):
    """Readable evidence summary linked to a saved artifact."""

    id: Identifier  # Unique within its containing Finding.
    kind: Literal["code_excerpt", "test_output", "human_review", "analysis_trace"]
    artifact_id: Identifier  # References an Artifact in the enclosing result.
    summary: NonEmpty


class Verification(Contract):
    """Recorded assessment of a finding, separate from execution success."""

    verdict: Literal["unverified", "confirmed", "rejected"] = "unverified"
    method: NonEmpty | None = None
    evidence_ids: list[Identifier] = Field(default_factory=list)  # Evidence in this finding.
    explanation: NonEmpty | None = None

    @model_validator(mode="after")
    def needs_basis(self) -> "Verification":
        """Require an assessment record without judging its scientific validity."""
        if self.verdict != "unverified" and (
            not self.method or not self.evidence_ids or not self.explanation
        ):
            raise ValueError("confirmed/rejected verdict requires method, evidence and explanation")
        return self


class Finding(Contract):
    """One candidate finding, including locations, evidence, and assessment."""

    id: Identifier  # Unique within one DetectionResult.
    defect_type: NonEmpty
    title: NonEmpty
    description: NonEmpty
    # Severity describes potential impact, not confidence in the finding.
    severity: Literal["unknown", "info", "low", "medium", "high", "critical"] = "unknown"
    locations: list[Location] = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)
    verification: Verification = Field(default_factory=Verification)
    properties: dict[str, JsonValue] = Field(default_factory=dict)  # Domain-specific metadata.

    @model_validator(mode="after")
    def evidence_links(self) -> "Finding":
        """Ensure evidence IDs are unique and verification references resolve."""
        ids = [item.id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence IDs must be unique within a finding")
        if not set(self.verification.evidence_ids).issubset(ids):
            raise ValueError("verification references an unknown evidence ID")
        return self


class ErrorRecord(Contract):
    """Structured execution failure or cancellation reason."""

    code: NonEmpty
    message: NonEmpty
    retryable: bool = False  # A hint; retry policy must also respect budgets and cancellation.


class FileReview(Contract):
    """Detailed-review scope and execution state, assigned by the framework."""

    path: str
    defect_types: list[NonEmpty] = Field(min_length=1)
    status: Literal["not_run", "in_progress", "succeeded", "failed", "interrupted"] = "not_run"

    @field_validator("path")
    @classmethod
    def check_path(cls, value: str) -> str:
        """Use the same repository-relative paths as source locations."""
        return relative_path(value)


class FindingAssessment(Contract):
    """A model's source-based assessment, not an independently verified verdict."""

    model_config = ConfigDict(json_schema_extra={"allOf": [{
        "if": {"properties": {"decision": {"const": "supported"}}, "required": ["decision"]},
        "then": {"properties": {"issue": {"const": "none"}}},
        "else": {"properties": {"issue": {"enum": [
            "location", "classification", "duplicate", "evidence", "description",
        ]}}},
    }]})

    finding_id: Identifier
    reason: NonEmpty = Field(description=(
        "Source-based conclusion about the review subject, justifying the following decision. "
        "In feedback_actions mode assess the proposed report handling, not whether the user is right."))
    decision: Literal["supported", "needs_revision", "refuted", "insufficient_evidence"] = Field(description=(
        "supported approves the review subject; needs_revision requests correction; refuted rejects it "
        "with source counterevidence; insufficient_evidence lacks necessary context. "
        "In feedback_actions mode, approving retain or withdraw both use supported."))
    issue: Literal["none", "location", "classification", "duplicate", "evidence", "description"] = Field(
        description="none only for supported; otherwise identify the problem with the review subject.",
    )
    evidence_lines: list[Annotated[int, Field(ge=1)]] = Field(
        description="Original source lines; may be empty only when the supplied source has no lines.",
    )
    target_defect_type: NonEmpty | None = None

    @model_validator(mode="after")
    def consistent_issue(self) -> "FindingAssessment":
        if (self.decision == "supported") != (self.issue == "none"):
            raise ValueError("only supported assessments may use issue=none")
        return self


class ReviewConcern(Contract):
    """A possible omission to reconsider within the existing per-file scope."""

    defect_type: NonEmpty
    reason: NonEmpty
    evidence_lines: list[Annotated[int, Field(ge=1)]] = Field(min_length=1)


class ModelFindingAssessment(FindingAssessment):
    """Tolerant model input; stored review records keep the strict assessment contract."""

    model_config = ConfigDict(extra="ignore", strict=True)


class ModelReviewConcern(ReviewConcern):
    """Read known concern fields without retaining extra model annotations."""

    model_config = ConfigDict(extra="ignore", strict=True)


class ModelReviewAnalysis(ModelReply):
    """Required reviewer reply; every supplied finding needs one assessment."""

    assessments: list[ModelFindingAssessment] = Field(max_length=100)
    concerns: list[ModelReviewConcern] = Field(default_factory=list, max_length=100)
    scope_concerns: list[ModelReviewConcern] = Field(default_factory=list, max_length=100)
    limitations: list[NonEmpty] = Field(default_factory=list)

    @field_validator("assessments")
    @classmethod
    def unique_assessments(cls, value):
        return unique_model_items(value, "finding_id")


class FeedbackItem(Contract):
    """One user claim; the framework assigns an ID within the feedback batch."""

    kind: Literal["false_positive", "false_negative", "location", "classification"]
    reason: Annotated[str, Field(min_length=1, pattern=r"\S")]
    finding_id: Identifier | None = None
    path: str | None = None
    defect_type: NonEmpty | None = None
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)

    @field_validator("path")
    @classmethod
    def check_path(cls, value: str | None) -> str | None:
        return relative_path(value) if value is not None else None

    @model_validator(mode="after")
    def target(self) -> "FeedbackItem":
        if self.kind == "false_negative":
            if self.path is None or self.finding_id is not None:
                raise ValueError("false_negative requires a path and no finding_id")
        elif self.finding_id is None:
            raise ValueError("feedback about an existing finding requires finding_id")
        if self.end_line is not None and (self.start_line is None or self.end_line < self.start_line):
            raise ValueError("end_line requires start_line and must not precede it")
        return self


class FeedbackBatch(Contract):
    """A batch of feedback collected through the interactive loop."""

    report_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None
    items: list[FeedbackItem] = Field(min_length=1, max_length=100)


class FileRepairTask(Contract):
    """Framework-selected work; accepted findings are not replacement targets."""

    finding_ids: list[Identifier]
    assessments: list[FindingAssessment]
    concerns: list[ReviewConcern]
    defect_types: list[NonEmpty] = Field(min_length=1)
    feedback: list[dict[str, JsonValue]] = Field(default_factory=list)


class ModelReviewRecord(Contract):
    """Framework-owned per-file history; execution success differs from review outcome."""

    path: str
    round: int = Field(ge=1)
    status: Literal["not_run", "in_progress", "succeeded", "failed", "interrupted"] = "not_run"
    finding_ids: list[Identifier] = Field(default_factory=list)
    assessments: list[FindingAssessment] = Field(default_factory=list)
    concerns: list[ReviewConcern] = Field(default_factory=list)
    scope_concerns: list[ReviewConcern] = Field(default_factory=list)
    limitations: list[NonEmpty] = Field(default_factory=list)
    artifact_id: Identifier | None = None
    outcome: Literal["passed", "needs_revision", "insufficient_evidence", "round_limit",
                     "budget_exhausted", "failed", "interrupted"] | None = None
    stop_reason: NonEmpty | None = None

    @field_validator("path")
    @classmethod
    def check_path(cls, value: str) -> str:
        return relative_path(value)

    @model_validator(mode="after")
    def assessment_identity(self) -> "ModelReviewRecord":
        if len(self.finding_ids) != len(set(self.finding_ids)):
            raise ValueError("review finding IDs must be unique")
        assessed = [item.finding_id for item in self.assessments]
        if len(assessed) != len(set(assessed)) or not set(assessed).issubset(self.finding_ids):
            raise ValueError("review assessments must refer to unique supplied findings")
        if self.status == "succeeded" and set(assessed) != set(self.finding_ids):
            raise ValueError("successful review must assess every supplied finding")
        return self


class Coverage(Contract):
    """Describe what was analyzed and which gaps remain."""

    scope_description: NonEmpty
    limitations: list[NonEmpty] = Field(default_factory=list)
    file_reviews: list[FileReview] = Field(default_factory=list)
    model_reviews: list[ModelReviewRecord] = Field(
        default_factory=list,
        description="Detailed runtime or legacy review records; omitted from the final report.",
    )


class Usage(Contract):
    """Reported execution measurements; this model does not collect them."""

    model_calls: int = Field(default=0, ge=0)
    duration_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)


class DetectionResult(Contract):
    """Output of one execution attempt, including traceable findings and errors."""

    # Identity fields must match the request; validate_exchange checks this relation.
    schema_version: Literal["1.0"] = "1.0"
    run_id: Identifier
    attempt: int = Field(ge=1)
    skill_id: SkillId
    skill_version: Version
    snapshot_id: SnapshotId
    status: Literal["succeeded", "partial", "failed", "cancelled"]  # Execution outcome only.
    findings: list[Finding] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    errors: list[ErrorRecord] = Field(default_factory=list)
    coverage: Coverage
    usage: Usage = Field(default_factory=Usage)

    def final_report(self) -> "DetectionResult":
        """Keep final candidates and compact review states; detailed history stays in round files."""
        data = self.model_dump(mode="python", exclude={"coverage": {"model_reviews"}})
        for finding in data["findings"]:
            properties = finding["properties"]
            opinion = properties.get("model_review")
            if isinstance(opinion, dict):
                properties["model_review"] = {
                    key: opinion[key] for key in ("decision", "issue", "round", "artifact_id")
                    if key in opinion
                }
            else:
                properties["model_review"] = {"decision": "not_reviewed"}
            # Original source/model evidence remains; full review reasons are in round-N/review/.
            required = set(finding["verification"]["evidence_ids"])
            finding["evidence"] = [item for item in finding["evidence"]
                                   if not item["id"].startswith("model-review-") or item["id"] in required]
        return DetectionResult.model_validate(data)

    @model_validator(mode="after")
    def consistency(self) -> "DetectionResult":
        """Validate local IDs, artifact references, and execution-state consistency."""
        # Findings and artifacts each have their own ID namespace.
        for name, values in (("finding", self.findings), ("artifact", self.artifacts)):
            ids = [item.id for item in values]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{name} IDs must be unique within a result")
        # Check references here; file existence and hashes require filesystem access.
        artifact_ids = {item.id for item in self.artifacts}
        for finding in self.findings:
            if any(item.artifact_id not in artifact_ids for item in finding.evidence):
                raise ValueError("evidence references an unknown artifact ID")
        review_keys = [(record.path, record.round) for record in self.coverage.model_reviews]
        if len(review_keys) != len(set(review_keys)):
            raise ValueError("duplicate model review round for a file")
        for record in self.coverage.model_reviews:
            if record.artifact_id is not None and record.artifact_id not in artifact_ids:
                raise ValueError("model review references an unknown artifact ID")
        # An incomplete run must explain both the failure and its coverage impact.
        if self.status == "succeeded" and self.errors:
            raise ValueError("successful result must not contain execution errors")
        if self.status != "succeeded" and not self.errors:
            raise ValueError("partial/failed/cancelled result requires an error or reason")
        if self.status != "succeeded" and not self.coverage.limitations:
            raise ValueError("incomplete result must state coverage limitations")
        return self


# Model analysis output, before framework-assigned identity and evidence.


class ModelFinding(ModelReply):
    """Untrusted candidate returned by the model; identity is assigned locally."""

    defect_type: NonEmpty
    title: NonEmpty
    description: NonEmpty
    severity: Literal["unknown", "info", "low", "medium", "high", "critical"]
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    explanation: NonEmpty


class ModelAnalysis(ModelReply):
    """Required model response, including an explicit empty finding list."""

    findings: list[ModelFinding] = Field(max_length=100)
    limitations: list[NonEmpty] = Field(default_factory=list)


class FindingRepair(ModelReply):
    """Explicitly resolve one requested finding; never silently remove a retained one."""

    model_config = ConfigDict(json_schema_extra={"allOf": [{
        "if": {"properties": {"action": {"const": "replace"}}, "required": ["action"]},
        "then": {"properties": {"findings": {"minItems": 1}}, "required": ["findings"]},
        "else": {"if": {"properties": {"action": {"const": "retain"}}, "required": ["action"]},
                 "then": {"properties": {"findings": {"maxItems": 1}}},
                 "else": {"properties": {"findings": {"maxItems": 0}}}},
    }]})

    finding_id: Identifier
    reason: NonEmpty = Field(description=(
        "Source-based conclusion about the original Finding that justifies the following action."))
    action: Literal["retain", "replace", "withdraw", "unresolved"] = Field(description=(
        "Effect on the original Finding: retain keeps it unchanged; replace corrects the same issue; "
        "withdraw removes it from the report; unresolved preserves it because necessary context is missing."))
    findings: list[ModelFinding] = Field(default_factory=list, max_length=100, description=(
        "Replacement findings: nonempty for replace; use [] for retain, withdraw and unresolved. "
        "A retain copy is accepted only when every content field exactly matches the original; "
        "the framework still keeps the original unchanged."))

    @model_validator(mode="after")
    def action_payload(self) -> "FindingRepair":
        if self.action == "replace" and not self.findings:
            raise ValueError("replace requires replacement findings")
        if self.action == "retain" and len(self.findings) > 1:
            raise ValueError("retain may include at most one unchanged copy")
        if self.action in ("withdraw", "unresolved") and self.findings:
            raise ValueError("withdraw and unresolved cannot contain replacement findings")
        return self


class ModelRepairAnalysis(ModelReply):
    """Targeted detector reply; source identities and final merging remain local."""

    repairs: list[FindingRepair] = Field(default_factory=list, max_length=100)
    additions: list[ModelFinding] = Field(default_factory=list, max_length=100)
    limitations: list[NonEmpty] = Field(default_factory=list)

    @field_validator("repairs")
    @classmethod
    def unique_repairs(cls, value):
        return unique_model_items(value, "finding_id")


class FeedbackResponse(ModelReply):
    """Explain how every feedback item was handled, including an empty omission search."""

    feedback_id: Identifier
    reason: NonEmpty = Field(description=(
        "Explain this feedback's result, including existing coverage or no supported new defect. "
        "A response is required; a new Finding is not."))
    addition_indices: list[Annotated[int, Field(ge=0)]] = Field(
        default_factory=list, max_length=100,
        description="Zero-based indices into additions supported by this omission feedback; [] otherwise.",
    )
    covered_finding_ids: list[Identifier] = Field(
        default_factory=list, max_length=100,
        description="Existing unchanged Findings covering this omission claim; [] otherwise. Do not regenerate them.",
    )

    @field_validator("addition_indices", "covered_finding_ids")
    @classmethod
    def unique_references(cls, value):
        """These are sets of links, not operations; repetition has no extra effect."""
        return list(dict.fromkeys(value))


class FeedbackRepairAnalysis(ModelRepairAnalysis):
    """A proposed change set; it is committed only after action review succeeds."""

    additions: list[ModelFinding] = Field(default_factory=list, max_length=100, description=(
        "Only supported new defects absent from existing Findings. Use [] when no feedback yields a new defect; "
        "put existing coverage, search results and no-defect explanations in feedback_responses, never here."))
    feedback_responses: list[FeedbackResponse] = Field(min_length=1, max_length=100)

    @field_validator("feedback_responses")
    @classmethod
    def unique_responses(cls, value):
        return unique_model_items(value, "feedback_id")


class AgentModelFinding(ModelFinding):
    """A package-level model finding must identify its source file."""

    path: str

    @field_validator("path")
    @classmethod
    def check_path(cls, value: str) -> str:
        return relative_path(value)


class AgentModelAnalysis(Contract):
    """Agent Skill response; the final DetectionResult stays unchanged."""

    findings: list[AgentModelFinding] = Field(max_length=100)
    limitations: list[NonEmpty] = Field(default_factory=list)


def validate_exchange(
    manifest: SkillManifest, request: DetectionRequest, result: DetectionResult
) -> None:
    """Check one manifest-request-result exchange beyond JSON Schema validation."""
    # Validate the selected Skill and supported targets before accepting its output.
    if (manifest.id, manifest.version) != (request.skill_id, request.skill_version):
        raise ValueError("request does not match the selected skill version")
    if not set(request.scope.defect_types).issubset(manifest.defect_types):
        raise ValueError("request contains unsupported defect types")
    # Reject output from another run, retry, Skill version, or source snapshot.
    for field in ("run_id", "attempt", "skill_id", "skill_version"):
        if getattr(request, field) != getattr(result, field):
            raise ValueError(f"result does not match request: {field}")
    if request.repository.snapshot_id != result.snapshot_id:
        raise ValueError("result does not match the repository snapshot")
    if any(f.defect_type not in request.scope.defect_types for f in result.findings):
        raise ValueError("finding is outside requested defect types")
    if any(not set(review.defect_types).issubset(request.scope.defect_types)
           for review in result.coverage.file_reviews):
        raise ValueError("file review is outside requested defect types")
    scopes = {review.path: review.defect_types for review in result.coverage.file_reviews}
    for record in result.coverage.model_reviews:
        if record.path not in scopes or any(concern.defect_type not in scopes[record.path]
                                            for concern in record.concerns):
            raise ValueError("model review is outside the actual per-file scope")
        if any(item.defect_type not in manifest.defect_types for item in record.scope_concerns):
            raise ValueError("model review references an unregistered scope concern")
    # Post-run count checks supplement runtime enforcement; no timer runs here.
    if request.budget.max_model_calls is not None and result.usage.model_calls > request.budget.max_model_calls:
        raise ValueError("model call budget exceeded")


# Public schema entry points; scripts/check_contracts.py generates their JSON files.
SCHEMA_MODELS = {
    "skill-manifest": SkillManifest,
    "detection-request": DetectionRequest,
    "detection-result": DetectionResult,
}
