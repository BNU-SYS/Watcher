"""Materialize HTTPS Git inputs before entering the detection workflow."""

import asyncio
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
from urllib.parse import unquote, urlsplit


def remove_repository(target: Path) -> None:
    """Remove only the completed clone owned by the current URL invocation."""
    if not target.exists() and not target.is_symlink():
        return
    if (target.is_symlink() or target.resolve() != target or Path.cwd().resolve().is_relative_to(target)
            or not (target / ".git").is_dir()):
        raise ValueError("Refusing to clean a replaced directory or a working-directory ancestor")

    def remove_readonly(function, path, exc_info):
        # Git pack files are read-only on Windows.
        if (not isinstance(exc_info[1], PermissionError) or os.path.islink(path)
                or function not in (os.unlink, os.remove, os.rmdir)):
            raise exc_info[1]
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        function(path)

    shutil.rmtree(target, onerror=remove_readonly)
    print(f"Removed cloned repository: {target}")


def parse_target(value: str) -> Path | str:
    """Keep URLs intact while preserving local Path inputs for existing callers."""
    if "://" in value or value.lower().startswith(("https:", "http:", "ssh:", "git:", "git@")):
        return value
    return Path(value)


def repository_name(url: str) -> str:
    """Accept repository URLs without embedding credentials in commands or reports."""
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "https" and parsed.hostname and parsed.port != 0
                 and parsed.username is None and parsed.password is None
                 and not parsed.query and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid or any(character.isspace() or ord(character) < 32 for character in url):
        raise ValueError("Use an HTTPS Git repository URL without credentials, query or fragment; use local Git authentication")
    parts = [unquote(part) for part in parsed.path.rstrip("/").split("/") if part]
    if not parts or any(part in (".", "..") or "/" in part or "\\" in part for part in parts):
        raise ValueError("The URL must identify a Git repository")
    # Reject common code-page links rather than treating them as clone endpoints.
    if ((parsed.hostname.lower() == "github.com" and len(parts) != 2)
            or parsed.hostname.lower() == "raw.githubusercontent.com"
            or ("-" in parts[:-1] and any(part in ("blob", "tree", "raw") for part in parts))):
        raise ValueError("Use the repository clone URL, not a file, branch or directory web page")
    name = parts[-1].removesuffix(".git")
    if (not name or name.endswith((".", " ")) or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", name)):
        raise ValueError("The repository name is not a valid directory name")
    return name


async def _stop_git(process) -> None:
    """Terminate Git and its transport helpers on timeout or cancellation."""
    if process.returncode is not None:
        return
    if os.name == "nt":
        try:
            cleanup = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(process.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            await cleanup.wait()
        except OSError:
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    await process.wait()


async def _git(*arguments: str, timeout: float, cwd: Path | None = None) -> str:
    """Run Git without a shell, interactive prompts, hooks, or LFS downloads."""
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never",
                   "GIT_LFS_SKIP_SMUDGE": "1"}
    options = ({"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
               if os.name == "nt" else {"start_new_session": True})
    try:
        process = await asyncio.create_subprocess_exec(
            "git", "-c", "core.hooksPath=" + os.devnull, "-c", "submodule.recurse=false",
            *arguments, cwd=cwd, env=environment, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **options,
        )
    except FileNotFoundError:
        raise ValueError("Git is required for repository URLs; install Git and add it to PATH") from None
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except (TimeoutError, asyncio.CancelledError):
        await _stop_git(process)
        raise
    if process.returncode:
        # Git/provider stderr can contain credentials from local authentication configuration.
        raise ValueError(f"Git {arguments[0]} failed (exit {process.returncode}); check repository access and branch")
    return stdout.decode("utf-8", errors="replace").strip()


async def clone_repository(url: str, *, branch: str | None = None, directory: Path | None = None,
                           timeout: int = 300) -> tuple[Path, dict]:
    """Shallow-clone one branch and record its exact origin for the caller."""
    name = repository_name(url)
    if timeout < 1:
        raise ValueError("clone timeout must be positive")
    if branch is not None:
        if not branch or branch.startswith("-") or branch != branch.strip():
            raise ValueError("--branch requires a valid branch name")
    target = directory if directory is not None else Path.cwd() / "repos" / name
    if target.is_symlink():
        raise ValueError("The clone directory must not be a symbolic link")
    target = target.resolve()
    if Path.cwd().resolve().is_relative_to(target):
        raise ValueError("Choose a clone directory outside the current working directory's ancestors")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError(f"Clone directory is not empty: {target}; choose --clone-dir or detect the existing local path")
    target.parent.mkdir(parents=True, exist_ok=True)
    arguments = ["clone", "--quiet", "--depth", "1", "--single-branch", "--no-recurse-submodules", "--template="]
    if branch is not None:
        arguments.extend(["--branch", branch])
    arguments.extend(["--", url, str(target)])
    print(f"Cloning repository to: {target}")
    try:
        async with asyncio.timeout(timeout):
            if branch is not None:
                await _git("check-ref-format", "refs/heads/" + branch, timeout=timeout)
            await _git(*arguments, timeout=timeout)
            actual_branch = await _git("symbolic-ref", "--short", "HEAD", timeout=timeout, cwd=target)
            commit = await _git("rev-parse", "HEAD", timeout=timeout, cwd=target)
            tracked = await _git("ls-files", "--stage", "-z", timeout=timeout, cwd=target)
    except TimeoutError:
        raise ValueError(f"Repository acquisition timed out after {timeout}s; inspect any retained directory: {target}") from None
    except ValueError as exc:
        raise ValueError(f"{exc}; no detection started; inspect any retained directory: {target}") from None
    submodules = [entry.split("\t", 1)[1] for entry in tracked.split("\0") if entry.startswith("160000 ")]
    origin = {"url": url, "requested_branch": branch, "branch": actual_branch,
              "commit": commit, "clone_dir": str(target), "depth": 1, "unfetched_submodules": submodules}
    print(f"Repository branch: {actual_branch}; commit: {commit}")
    if submodules:
        print("Submodules were not fetched: " + ", ".join(submodules))
    return target, origin
