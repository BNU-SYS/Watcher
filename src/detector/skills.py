"""Load and register language-neutral Skill packages without importing package code."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

from .contracts import SkillManifest, relative_path


@dataclass(frozen=True)
class LoadedSkill:
    """Loaded package data; treat nested metadata as read-only as well."""

    # Structured metadata loaded from manifest.json and validated by SkillManifest.
    # Includes the ID, version, supported languages and defect types,
    # and instruction file path for registration, lookup.
    # The detection steps from SKILL.md are stored separately in instructions.
    manifest: SkillManifest
    directory: Path  # Resolved package root for locating supporting resources.
    instructions: str  # Main instruction text, not executable Python code.
    definition_sha256: str  # Fingerprint of metadata, instructions, and options schema.
    options_schema: dict | None = None  # Loaded only; option values are not validated here.

    @property
    def analysis_instructions(self) -> str:
        """Keep analysis rules without changing the original Skill or its fingerprint."""
        # Stop at the next level-two section so appended CWE rules remain intact.
        instructions = re.sub(
            r"^##[ \t]+(?:Output contract|输出约定)[ \t]*\r?\n.*?(?=^##[ \t]+|\Z)",
            "", self.instructions, flags=re.MULTILINE | re.DOTALL | re.IGNORECASE,
        )
        # Legacy procedure steps also mix evidence checks with first-pass output instructions.
        analysis = re.sub(
            r"^(\d+\.)[ \t]+(?:Return the final JSON\b|当本次文件的被请求检查完成时，立即返回最终 JSON。)[^\r\n]*",
            r"\1 Complete all requested checks and applicable location checks before forming a conclusion. "
            "Each candidate's title, description and explanation must support the same defect conclusion; "
            "contradictory reasoning invalidates the candidate. An absence of supported candidates does "
            "not prove safety.",
            instructions, flags=re.MULTILINE,
        ).strip()
        if "contradictory reasoning invalidates the candidate" not in analysis:
            analysis += (
                "\n\nEach candidate's title, description and explanation must support the same "
                "defect conclusion; contradictory reasoning invalidates the candidate. "
                "An absence of supported candidates does not prove safety."
            )
        return analysis

    def for_defect_types(self, defect_types: list[str]) -> "LoadedSkill":
        """Compose the common instructions with only the requested rule modules."""
        if not isinstance(self.manifest.rule_files, dict) or not self.manifest.rule_files:
            return self
        if not set(defect_types).issubset(self.manifest.defect_types):
            raise ValueError("requested defect types are not supported by this Skill")
        sections = [self.instructions]
        for defect_type in defect_types:
            rule_path = self.manifest.rule_files.get(defect_type)
            if rule_path is None:
                raise ValueError(f"no rule file is declared for {defect_type}")
            text = package_file(self.directory, rule_path).read_text(encoding="utf-8")
            if not text.strip():
                raise ValueError(f"rule file is empty: {rule_path}")
            sections.append(f"\n\n## Requested defect rule: {defect_type}\n\n{text}")
        instructions = "".join(sections)
        definition = json.dumps(
            {"manifest": self.manifest.model_dump(mode="json"), "instructions": instructions,
             "options_schema": self.options_schema},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        return LoadedSkill(self.manifest, self.directory, instructions,
                           hashlib.sha256(definition).hexdigest(), self.options_schema)


def package_file(root: Path, name: str) -> Path:
    """Check resolved containment as well as the portable relative path syntax."""
    relative_path(name)
    root = root.resolve(strict=True)
    # Resolve links before checking containment; string checks alone are insufficient.
    file = (root / name).resolve(strict=True)
    if not file.is_relative_to(root) or not file.is_file():
        raise ValueError(f"Skill file is outside its package or not a file: {name}")
    return file


def load_skill(directory: str | Path) -> LoadedSkill:
    """Read and validate a Skill package without executing its scripts."""
    root = Path(directory).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Skill package must be a directory")
    # Parse metadata first so the declared instruction path can be validated.
    manifest = SkillManifest.model_validate_json(
        package_file(root, "manifest.json").read_text(encoding="utf-8")
    )
    instructions = package_file(root, manifest.skill_file).read_text(encoding="utf-8")
    if not instructions.strip():
        raise ValueError("Skill instructions must not be empty")
    if isinstance(manifest.rule_files, list) and manifest.rule_files:
        rules = []
        for name in manifest.rule_files:
            text = package_file(root, name).read_text(encoding="utf-8")
            if not text.strip():
                raise ValueError(f"Skill review rules must not be empty: {name}")
            rules.append(f"=== {name} ===\n{text}")
        instructions += "\n\n## Supplied Review Rules\n\n" + "\n\n".join(rules)
    # Workflow preflight validates the Schema and request options; loading only reads it.
    options_schema = None
    if manifest.options_schema is not None:
        options_schema = json.loads(package_file(root, manifest.options_schema).read_text(encoding="utf-8"))
        if not isinstance(options_schema, dict):
            raise ValueError("options_schema must contain a JSON object")
    # Preserve existing definition hashes when the optional additions are unused.
    metadata = manifest.model_dump(mode="json", exclude={"rule_files", "exclude_dir", "exclude_file"})
    for name in ("rule_files", "exclude_dir", "exclude_file"):
        if value := getattr(manifest, name):
            metadata[name] = value
    # Loaded rule contents are part of instructions and therefore the fingerprint.
    # Stable key ordering avoids fingerprint changes caused only by JSON formatting.
    definition = json.dumps(
        {"manifest": metadata, "instructions": instructions,
         "options_schema": options_schema},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return LoadedSkill(manifest, root, instructions, hashlib.sha256(definition).hexdigest(), options_schema)


class SkillRegistry:
    """Explicit registration; one version per ID in an individual registry."""

    def __init__(self) -> None:
        """Create an empty in-memory registry."""
        # Explicitly registered packages only; no directory scanning or persistence.
        self._skills: dict[str, LoadedSkill] = {}

    def register(self, directory: str | Path) -> LoadedSkill:
        """Load and register a Skill, rejecting duplicate IDs."""
        skill = load_skill(directory)
        if skill.manifest.id in self._skills:
            raise ValueError(f"Skill ID already registered: {skill.manifest.id}")
        self._skills[skill.manifest.id] = skill
        return skill

    def replace(self, skill: LoadedSkill) -> LoadedSkill:
        """Replace a registered Skill with a composed immutable instruction view."""
        if skill.manifest.id not in self._skills:
            raise KeyError(f"Skill is not registered: {skill.manifest.id}")
        self._skills[skill.manifest.id] = skill
        return skill

    def get(self, skill_id: str) -> LoadedSkill:
        """Return a registered Skill or raise KeyError if not found."""
        # Return the stored object; callers should not mutate its nested metadata.
        try:
            return self._skills[skill_id]
        except KeyError:
            raise KeyError(f"Skill is not registered: {skill_id}") from None

    def list(self, language: str | None = None) -> list[SkillManifest]:
        """Return manifest copies, optionally filtered by language."""
        # Copies protect registry metadata; language matching is exact and case-sensitive.
        return [
            skill.manifest.model_copy(deep=True)
            for skill in self._skills.values()
            if language is None or language in skill.manifest.languages
        ]

