"""Collect bounded, immutable source inputs without running repository code."""

from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Iterator

from .contracts import ErrorRecord, Scope, relative_path

IGNORED_DIRECTORIES = {".git", ".venv", "node_modules", "target", "build", ".detector",
                       ".cleanup-backup", "__pycache__", "dist"}


@dataclass(frozen=True)
class SourceFile:
    """One UTF-8 source file captured before any model calls."""

    path: str
    text: str
    sha256: str


@dataclass(frozen=True)
class SourceSnapshot:
    """Captured inputs and collection errors; the digest covers captured files only."""

    root: Path
    files: tuple[SourceFile, ...]
    snapshot_id: str
    errors: tuple[ErrorRecord, ...]


def matches(path: str, patterns: list[str]) -> bool:
    """Match root-relative globs; ** spans directories and * stays in one segment."""
    return any(_match_parts(tuple(path.split("/")), tuple(pattern.split("/"))) for pattern in patterns)


@lru_cache(maxsize=4096)
def _match_parts(path: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    """Match path segments with memoized recursive double-star expansion."""
    if not pattern:
        return not path
    if pattern[0] == "**":
        return _match_parts(path, pattern[1:]) or bool(path and _match_parts(path[1:], pattern))
    return bool(path and fnmatchcase(path[0], pattern[0]) and _match_parts(path[1:], pattern[1:]))


def source_paths(target: Path, *, exclude_dir: list[str] | None = None) -> Iterator[Path]:
    """Walk deterministically, excluding generated directories and directory links."""
    if target.is_file():
        yield target
        return
    ignored = IGNORED_DIRECTORIES if exclude_dir is None else set(exclude_dir)
    for directory, dirs, names in os.walk(target, followlinks=False, onerror=_raise_walk_error):
        dirs[:] = sorted(name for name in dirs if name not in ignored
                         and not (Path(directory) / name).is_symlink()
                         and (Path(directory) / name).resolve().is_relative_to(target))
        for name in sorted(names):
            yield Path(directory) / name


def _raise_walk_error(error: OSError) -> None:
    """Do not silently omit unreadable directories from coverage."""
    raise error


def collect_sources(
    target: Path, scope: Scope, *, max_files: int | None = None, max_file_chars: int = 30000,
    exclude_dir: list[str] | None = None, exclude_file: list[str] | None = None,
    allowed_patterns: list[str] | None = None,
) -> SourceSnapshot:
    """Capture matching files once and report skipped or unreadable inputs."""
    if (max_files is not None and max_files < 1) or max_file_chars < 1:
        raise ValueError("source limits must be positive")
    if target.is_symlink():
        raise ValueError("the input target must not be a symbolic link")
    target = target.resolve(strict=True)
    if not target.is_file() and not target.is_dir():
        raise ValueError("the input target must be a regular file or directory")
    root = target.parent if target.is_file() else target
    files, errors = [], []
    matched = 0
    skipped_extensions = {suffix.lower() for suffix in exclude_file or []}
    for path in source_paths(target, exclude_dir=exclude_dir):
        name = path.relative_to(root).as_posix()
        if allowed_patterns is not None and not matches(name, allowed_patterns):
            continue
        if not matches(name, scope.include) or matches(name, scope.exclude):
            continue
        if path.suffix.lower() in skipped_extensions:
            continue
        matched += 1
        if max_files is not None and matched > max_files:
            errors.append(ErrorRecord(code="SOURCE_LIMIT", message="Additional matching files exceed max_files"))
            break
        try:
            relative_path(name)
            if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
                raise ValueError("source links and non-regular files are not supported")
            with path.open("rb") as stream:
                raw = stream.read(max_file_chars * 4 + 1)
            if len(raw) > max_file_chars * 4:
                raise ValueError("file exceeds the configured size limit")
            text = raw.decode("utf-8-sig")
            if re.fullmatch(
                r"version (?:https://(?:git-lfs|hawser)\.github\.com/spec/v1|http://git-media\.io/v/2)\r?\n"
                r"(?:ext-[^\r\n]+\r?\n)*"
                r"oid sha256:[0-9a-f]{64}\r?\nsize [0-9]+(?:\r?\n)?", text,
            ):
                errors.append(ErrorRecord(
                    code="LFS_SOURCE_NOT_FETCHED",
                    message=f"{name}: Git LFS pointer skipped; actual file content was not fetched; coverage is incomplete",
                ))
                continue
            if len(text) > max_file_chars:
                raise ValueError("file exceeds max_file_chars")
            files.append(SourceFile(name, text, hashlib.sha256(raw).hexdigest()))
        except (OSError, UnicodeError, ValueError) as exc:
            reason = ("not valid UTF-8" if isinstance(exc, UnicodeError) else
                      "source could not be read" if isinstance(exc, OSError) else str(exc))
            errors.append(ErrorRecord(code="SOURCE_SKIPPED", message=f"{name}: {reason}"))
    if not matched:
        raise ValueError("No source files match the requested scope")
    definition = json.dumps([(f.path, f.sha256) for f in files], ensure_ascii=False).encode("utf-8")
    return SourceSnapshot(root, tuple(files), "tree:sha256:" + hashlib.sha256(definition).hexdigest(),
                          tuple(errors))
