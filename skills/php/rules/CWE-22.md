### CWE-22: Path traversal

- Trace external input into a filesystem path consumed by `readfile`, `file_get_contents`, `fopen`, `unlink`, `copy`, `rename`, `scandir`, `mkdir`, `rmdir`, `chmod`, `file_put_contents`, `fpassthru`, or a similar filesystem API.
- Report when the input can introduce `..` segments, an absolute path, or a stream wrapper and no effective containment is visible. String prefix comparisons after concatenation, `basename` applied after resolution, and normalization without a containment check are not effective.
- Fixed trusted paths, a mapping from identifiers to fixed paths, and a resolved-path check that compares path components against an allowed base directory refute the finding.
- Do not report when the value only reaches a log message or a display operation and never reaches a filesystem API.

#### Finding location

- The primary operation is the filesystem call that consumes the externally controlled path. Explain the constructed path, the controllable segment, and why the visible check does not contain it.
