"""Extension interfaces used by the workflow; production services are injectable."""

from dataclasses import dataclass
from typing import Protocol

from pydantic import JsonValue

from .contracts import Artifact, DetectionRequest, DetectionResult
from .skills import LoadedSkill
from .tasks import ExecutionPlan


class ModelService(Protocol):
    """Model-provider boundary; credentials stay in the service implementation."""

    async def complete(self, *, system: str, user: str) -> str:
        """Return model text for system instructions and user input."""
        ...


class ArtifactService(Protocol):
    """Storage boundary for evidence and other execution outputs."""

    def write_text(self, relative_path: str, content: str) -> Artifact:
        """Save text under the current attempt's artifact root and return its metadata."""
        ...


class EventService(Protocol):
    """Execution logging boundary for progress and diagnostic events."""

    def emit(self, event: str, data: dict[str, JsonValue]) -> None:
        """Record an event; implementations attach run identity and timestamps."""
        ...


class Cancellation(Protocol):
    """Cooperative cancellation signal checked during execution loops."""

    def raise_if_cancelled(self) -> None:
        """Raise when cancellation is requested; otherwise return normally."""
        ...


@dataclass(frozen=True)
class ExecutionContext:
    """Services supplied by the framework for one execution attempt."""

    model: ModelService | None  # None when no model backend is configured.
    artifacts: ArtifactService
    events: EventService
    cancellation: Cancellation
    # Source tasks assembled by prepare_tasks; package/custom executors do not use it.
    execution_plan: ExecutionPlan | None = None
    prescreen_limitations: tuple[str, ...] = ()
    round_number: int = 1
    round_layout: bool = False
    # Shared audit sink; model history input is already captured in each prepared task.
    file_history: dict[str, list[dict]] | None = None


class SkillExecutor(Protocol):
    """Implemented once by the framework, not separately by each Skill author."""

    async def run(
        self, skill: LoadedSkill, request: DetectionRequest, context: ExecutionContext
    ) -> DetectionResult:
        """Execute the loaded Skill for a request using the supplied services."""
        ...


# Skill packages are data (manifest + Markdown + resources), not Python entry points.
