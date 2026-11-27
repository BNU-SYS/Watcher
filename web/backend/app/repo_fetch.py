"""Download a public GitHub repository snapshot into a scan workspace.

Only ``github.com`` web links are accepted. The archive is streamed from the
GitHub API with a hard byte cap, then extracted by hand so that only files
matching the selected language ever reach the workspace.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

import httpx

from . import config

OWNER_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
ALLOWED_HOSTS = {"github.com", "www.github.com"}
DOWNLOAD_HOSTS = {"api.github.com", "codeload.github.com"}
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL",
                    *(f"COM{i}" for i in range(1, 10)),
                    *(f"LPT{i}" for i in range(1, 10))}
INVALID_PATH_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


class RepoError(RuntimeError):
    """A repository problem that is safe to show to the user."""


@dataclass(frozen=True)
class RepoSpec:
    owner: str
    repo: str
    ref: str = ""
    subdir: str = ""

    @property
    def label(self) -> str:
        text = f"{self.owner}/{self.repo}"
        if self.ref:
            text += f"@{self.ref}"
        if self.subdir:
            text += f"/{self.subdir}"
        return text

    @property
    def web_url(self) -> str:
        url = f"https://github.com/{self.owner}/{self.repo}"
        if self.ref:
            url += f"/tree/{quote(self.ref, safe='/')}"
            if self.subdir:
                url += f"/{quote(self.subdir, safe='/')}"
        return url


def parse_repo_url(raw: str, ref: str = "", subdir: str = "") -> RepoSpec:
    """Normalize a GitHub link and merge the optional ref/subdir fields."""
    text = (raw or "").strip()
    if not text:
        raise RepoError("请填写 GitHub 仓库地址")
    if "://" not in text:
        text = "https://" + text
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https"):
        raise RepoError("仓库地址需以 https://github.com/ 开头")
    if parts.username or parts.password:
        raise RepoError("仓库地址不能包含账号信息")
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise RepoError("暂时只支持 github.com 的公开仓库")

    raw_segments = [unquote(item) for item in parts.path.split("/") if item]
    if len(raw_segments) < 2:
        raise RepoError("仓库地址不完整，应形如 https://github.com/owner/repo")
    owner, repo = raw_segments[0], raw_segments[1]
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if not OWNER_RE.match(owner) or not OWNER_RE.match(repo):
        raise RepoError("仓库地址中的 owner 或 repo 名称不合法")

    link_ref = ""
    link_subdir = ""
    extra = raw_segments[2:]
    if extra:
        if extra[0] not in ("tree", "blob") or len(extra) < 2:
            raise RepoError("只支持仓库主页或 /tree/ 目录链接")
        link_ref = extra[1]
        link_subdir = "/".join(extra[2:])

    final_ref = (ref or "").strip() or link_ref
    final_subdir = (subdir or "").strip() or link_subdir
    if len(final_ref) > 200 or any(ord(ch) < 32 for ch in final_ref):
        raise RepoError("分支或标签名称不合法")
    final_subdir = _clean_subdir(final_subdir)
    return RepoSpec(owner=owner, repo=repo, ref=final_ref, subdir=final_subdir)


def _clean_subdir(raw: str) -> str:
    parts = []
    for item in (raw or "").replace("\\", "/").split("/"):
        if item in ("", "."):
            continue
        if item == "..":
            raise RepoError("子目录不能包含 ..")
        parts.append(item)
    return "/".join(parts)


def _safe_member_path(name: str) -> str:
    value = name.replace("\\", "/")
    if value.startswith("/"):
        raise RepoError(f"压缩包内包含绝对路径：{name}")
    parts = []
    for item in value.split("/"):
        if item in ("", "."):
            continue
        if (item == ".." or item.endswith(".") or item.strip() != item
                or INVALID_PATH_CHARS.search(item)
                or item.split(".")[0].upper() in WINDOWS_RESERVED):
            raise RepoError(f"压缩包内包含非法路径：{name}")
        parts.append(item)
    if not parts:
        raise RepoError("压缩包内包含空路径")
    return "/".join(parts)


def _tarball_url(spec: RepoSpec) -> str:
    base = f"https://api.github.com/repos/{quote(spec.owner)}/{quote(spec.repo)}/tarball"
    return base + (f"/{quote(spec.ref, safe='')}" if spec.ref else "")


async def _validate_download_request(request: httpx.Request) -> None:
    """Check every redirect before HTTPX contacts its destination."""
    if (request.url.scheme != "https" or request.url.host not in DOWNLOAD_HOSTS
            or request.url.port not in (None, 443) or request.url.userinfo):
        raise RepoError("下载地址跳转到了非 GitHub HTTPS 地址，已中止")


async def fetch_repository(
    *,
    spec: RepoSpec,
    workspace: Path,
    extensions: list[str],
    on_stage=None,
) -> list[dict]:
    """Download and extract the archive, returning stored file records."""
    extensions = [item.lower() for item in extensions]
    workspace.mkdir(parents=True, exist_ok=True)
    archive = workspace.parent / ".repo.tar.gz"
    url = _tarball_url(spec)

    if on_stage:
        on_stage("repo.downloading", {"url": spec.web_url, "repo": spec.label})

    downloaded = 0
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=15.0),
            follow_redirects=True,
            max_redirects=5,
            event_hooks={"request": [_validate_download_request]},
        ) as client:
            async with client.stream(
                "GET",
                url,
                headers={
                    "User-Agent": "watcher",
                    "Accept": "application/vnd.github+json",
                },
            ) as response:
                if response.status_code == 404:
                    raise RepoError("仓库不存在，或是不支持的私有仓库")
                if response.status_code == 403:
                    raise RepoError("GitHub 拒绝访问，可能触发匿名访问频率限制，请稍后再试")
                if response.status_code != 200:
                    raise RepoError(f"GitHub 返回 HTTP {response.status_code}")
                final_host = (response.url.host or "").lower()
                if final_host not in DOWNLOAD_HOSTS:
                    raise RepoError("下载地址跳转到了非 GitHub 域名，已中止")
                with archive.open("wb") as stream:
                    async for chunk in response.aiter_bytes(64 * 1024):
                        downloaded += len(chunk)
                        if downloaded > config.MAX_REPO_BYTES:
                            raise RepoError(
                                f"仓库压缩包超过 {config.MAX_REPO_BYTES // (1024 * 1024)} MB 上限"
                            )
                        stream.write(chunk)
        if on_stage:
            on_stage("repo.extracting", {"repo": spec.label})
        return await asyncio.to_thread(
            _extract_archive,
            archive,
            workspace,
            extensions,
            spec.subdir,
        )
    except httpx.HTTPError as exc:
        raise RepoError(f"下载仓库失败：{exc.__class__.__name__}") from exc
    finally:
        try:
            archive.unlink()
        except OSError:
            pass


def _extract_archive(
    archive: Path,
    workspace: Path,
    extensions: list[str],
    subdir: str,
) -> list[dict]:
    stored: list[dict] = []
    extracted_bytes = 0
    with tarfile.open(archive, "r:gz") as tar:
        root = ""
        for member in tar:
            if not member.isfile():
                continue
            name = member.name.replace("\\", "/")
            if not root:
                root = name.split("/", 1)[0] if "/" in name else ""
            if root and name.startswith(root + "/"):
                name = name[len(root) + 1 :]
            if not name or not name.lower().endswith(tuple(extensions)):
                continue
            if subdir and not name.startswith(subdir + "/"):
                continue
            _safe_member_path(member.name)
            path = _safe_member_path(name)
            suffix = PurePosixPath(path).suffix
            if suffix != suffix.lower():
                path = path[:-len(suffix)] + suffix.lower()
            parts = PurePosixPath(path).parts
            if any(part in config.REPO_EXCLUDED_DIRS for part in parts[:-1]):
                continue
            if member.size > config.MAX_FILE_BYTES:
                continue
            if len(stored) >= config.MAX_REPO_FILES:
                break
            source = tar.extractfile(member)
            if source is None:
                continue
            data = source.read()
            extracted_bytes += len(data)
            if extracted_bytes > config.MAX_REPO_BYTES:
                raise RepoError("解压后的源码总量超过上限，请改用子目录缩小范围")
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                continue
            if not text.strip():
                continue
            target = (workspace / PurePosixPath(path)).resolve()
            if not target.is_relative_to(workspace.resolve()):
                raise RepoError(f"压缩包路径超出任务目录：{name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="")
            stored.append(
                {
                    "path": path,
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "line_count": text.count("\n") + 1,
                }
            )
    if not stored:
        hint = "、".join(extensions)
        raise RepoError(f"仓库里没有找到可检测的 {hint} 源码")
    return stored
