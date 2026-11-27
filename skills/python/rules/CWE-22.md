### CWE-22: Path traversal, static-file escape and archive extraction escape

- Establish the untrusted path component: a filename, relative path, archive member name, URL-derived path, or static-file request path supplied by a caller or external data.
- Identify the sink: `open`, `Path(...).read_text`/`write_text`, `os.remove`/`rename`, `shutil.copy`/`move`, `send_file`, `send_from_directory`, `zipfile.ZipFile.extract`/`extractall`, or `tarfile.extract`/`extractall`.
- Include static-file servers: `web.static`, `StaticResource`, `web.FileResponse`, `follow_symlinks=True`, and framework helpers that join a request path to a document root.
- Establish that the component is joined to a base directory without a containment check: `os.path.join`, `Path(base) / name`, string concatenation, or an archive member name used directly. `os.path.join(base, "/absolute")` discards `base`; a `..` component or symlink can escape it.
- Canonicalization alone is not a containment check: `Path.resolve()` or `os.path.realpath()` must be followed by a comparison of the resolved target with the resolved base using `is_relative_to(base)`, `commonpath`, or an equivalent component-aware check.
- For a static file server, `follow_symlinks=True` requires the resolved target to remain under the document root; reject `..`, absolute paths and symlink escapes before opening the file.
- In a static-file implementation, if the `follow_symlinks` option skips the `relative_to`/`is_relative_to`/`commonpath` check when true, the true branch has no containment check. Report CWE-22 even when the default is false; callers can enable it.
- Do not report a constant path, a value reduced to its final component with `Path(name).name`/`os.path.basename` when that is the intended contract, or a path validated with `resolve()` plus `is_relative_to(base)`/`commonpath` before use.
- A `startswith` prefix check is not a containment check (`/srv/app` and `/srv/app-evil` share a prefix); report it as ineffective.
- For `extractall`, the archive is untrusted when its origin is a parameter, upload, or download; a member-name check performed after extraction does not protect the write. Use a safe extraction filter or validate every member name before extraction.

#### Required checks for path handling

1. Locate every path join, path-based open/write/remove/copy, archive extraction, and static-file resolution.
2. Identify the base directory and resolve both base and target before comparison; check `is_relative_to`/`commonpath`, not a string prefix.
3. For static-file servers, check both branches of `follow_symlinks`; enabling it must not skip containment.
4. Report the join/sink or the `follow_symlinks` branch that lacks containment, and state the escaping component in `explanation`.

#### Example

```python
import os

def read_upload(base, name):
    return open(os.path.join(base, name)).read()   # name = "../../etc/passwd"
```

#### Finding location

- The primary operation is the path construction that joins the untrusted component, or the `extract`/`extractall` call for archives. Cite the absent containment check in `explanation`.
- For a static-file server, cite the `follow_symlinks=True` resolution/open or the request-path join that lacks a resolved-base containment check.
