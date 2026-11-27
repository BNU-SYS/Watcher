### CWE-78: OS command injection

- Establish the origin of the untrusted value: a function parameter, request data, configuration, environment variable, filename, or a value derived from them.
- Identify the shell execution sink: `os.system`, `os.popen`, `subprocess.*` with `shell=True`, `asyncio.create_subprocess_shell`, or an explicit `sh -c`/`cmd /c` argument list.
- Establish that the untrusted value reaches the command string without effective quoting or allowlisting: an f-string, `%`, `format`, `+`, `.join`, or interpolation into an argument that a shell will parse.
- Do not report a fixed constant command, an argument list executed with `shell=False`, a value passed only as a separate `argv` element, or a value transformed by `shlex.quote`/`shlex.join` or validated against a strict allowlist.
- `shell=True` alone is not a defect; require the untrusted interpolation. `os.system` always uses a shell, so a concatenated value is sufficient.

#### Example

```python
import os

def ping(host):
    os.system("ping -c 1 " + host)   # host reaches the shell unquoted
```

#### Finding location

- The primary operation is the command-construction expression where the untrusted value is interpolated, or the `os.system`/`os.popen` call that receives it. Cite the shell sink in `explanation`.
