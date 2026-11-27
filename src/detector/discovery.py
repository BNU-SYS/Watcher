"""Discover source languages and select declarative Skill packages."""

from pathlib import Path
import sysconfig

from .contracts import SkillManifest
from .skills import LoadedSkill, SkillRegistry, package_file
from .sources import matches, source_paths

# Keep language recognition separate from detection algorithms and Skill IDs.
LANGUAGE_EXTENSIONS = {
    "java": (".java",),
    "python": (".py", ".pyi"),
    "c": (".c", ".cpp", ".cc", ".cxx", ".C", ".h", ".hpp", ".hh", ".hxx"),
    "javascript": (".js", ".jsx", ".mjs", ".cjs"),
    "typescript": (".ts", ".tsx", ".mts", ".cts"),
    "go": (".go",),
    "rust": (".rs",),
}
PROJECT_MARKERS = {
    "pom.xml": "java", "pyproject.toml": "python", "setup.py": "python",
    "go.mod": "go", "Cargo.toml": "rust", "tsconfig.json": "typescript",
}


def canonical_language(language: str) -> str:
    """Use one C/C++ category; keep cpp as an input alias for c."""
    return "c" if language == "cpp" else language


def skill_root() -> Path:
    """Locate the checkout or installed collection of built-in Skill packages."""
    checkout = Path(__file__).resolve().parents[2] / "skills"
    if checkout.is_dir():
        return checkout
    return Path(sysconfig.get_path("data")) / "share" / "detector" / "skills"


def detect_project_language(
    target: Path, *, include: list[str] | None = None, exclude: list[str] | None = None,
    extensions: dict[str, tuple[str, ...]] | None = None,
) -> str:
    """Infer one language from scoped filenames, then root project markers."""
    if target.is_symlink():
        raise ValueError("the input target must not be a symbolic link")
    target = target.resolve(strict=True)
    if not target.is_file() and not target.is_dir():
        raise ValueError("the input target must be a regular file or directory")
    root = target.parent if target.is_file() else target
    extensions = LANGUAGE_EXTENSIONS if extensions is None else extensions
    languages = set()
    for path in source_paths(target):
        name = path.relative_to(root).as_posix()
        if not matches(name, include or ["**/*"]) or matches(name, exclude or []):
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            continue
        languages.update(language for language, suffixes in extensions.items()
                         if path.suffix in suffixes)
    if not languages and target.is_dir() and include is None:
        languages.update(language for marker, language in PROJECT_MARKERS.items()
                         if (target / marker).is_file() and not matches(marker, exclude or []))
    if len(languages) > 1:
        raise ValueError(f"Multiple project languages detected: {', '.join(sorted(languages))}; "
                         "use --language to select one or --include to narrow the scope")
    if not languages:
        raise ValueError("Cannot infer the project language; declare file_extensions in a Skill manifest")
    return next(iter(languages))


def default_include(language: str, extensions: dict[str, tuple[str, ...]] | None = None) -> list[str]:
    """Build source patterns directly from the selected language's extensions."""
    language = canonical_language(language)
    if language == "agent_skill":
        return ["SKILL.md", "scripts/*", "references/*"]
    extensions = LANGUAGE_EXTENSIONS if extensions is None else extensions
    if language not in extensions:
        raise ValueError(f"No source patterns are defined for '{language}'; pass --include")
    return ["**/*" + extension for extension in extensions[language]]


def resolve_skill(
    target: Path, registry: SkillRegistry, *,
    language: str | None = None, include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> tuple[LoadedSkill, str, list[str]]:
    """Discover declarations once, identify source language, then load its Skill."""
    packages = {}
    extensions = dict(LANGUAGE_EXTENSIONS)
    for path in sorted(skill_root().glob("*/manifest.json")):
        manifest = SkillManifest.model_validate_json(
            package_file(path.parent, "manifest.json").read_text(encoding="utf-8"))
        packages[path.parent] = manifest
        for name, suffixes in manifest.file_extensions.items():
            extensions[name] = tuple(dict.fromkeys((*extensions.get(name, ()), *suffixes)))

    language = canonical_language(language) if language else detect_project_language(
        target, include=include, exclude=exclude, extensions=extensions)
    candidates = [path for path, manifest in packages.items() if language in manifest.languages]
    if not candidates:
        raise ValueError(f"No completed Skill is available for language '{language}'; "
                         f"add manifest.json and SKILL.md under skills/{language}/")
    if len(candidates) > 1:
        raise ValueError(f"Multiple Skills support '{language}': "
                         f"{', '.join(path.name for path in candidates)}; keep one active Skill per language")
    return registry.register(candidates[0]), language, include or default_include(language, extensions)


def resolve_agent_skill(
    target: Path, registry: SkillRegistry, *, include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> tuple[LoadedSkill, str, list[str]]:
    """Explicitly select package security review through the existing registry."""
    return resolve_skill(target, registry, language="agent_skill", include=include, exclude=exclude)


def discover_agent_skill_packages(
    target: Path, *, exclude_dir: list[str] | None = None, exclude: list[str] | None = None,
) -> list[Path]:
    """Find package roots by SKILL.md, keeping nested materials in their outer package."""
    if target.is_symlink():
        raise ValueError("the input target must not be a symbolic link")
    target = target.resolve(strict=True)
    if not target.is_dir():
        raise ValueError("Agent Skill package discovery requires a directory")
    marker = target / "SKILL.md"
    if marker.is_file() and not marker.is_symlink():
        return [target]
    packages = []
    for path in source_paths(target, exclude_dir=exclude_dir):
        if path.name != "SKILL.md" or path.is_symlink() or not path.is_file():
            continue
        if matches(path.relative_to(target).as_posix(), exclude or []):
            continue
        package = path.parent
        if not any(package.is_relative_to(parent) for parent in packages):
            packages.append(package)
    return sorted(packages)
