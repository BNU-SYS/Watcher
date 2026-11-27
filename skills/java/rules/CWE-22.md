# CWE-22: Path Traversal

Report when a controlled path component can escape an intended directory during actual file access or extraction.

1. Identify the path input, allowed root and read/write/delete/extract operation. Archive entry names can establish the input boundary.
2. Trace concatenation, `resolve`, normalization and validation to the final path. Check parent traversal, absolute replacement and platform separators.
3. Test containment on the path actually used. Component-aware `Path.startsWith` differs from string-prefix checks that accept similarly named siblings. Evaluate symlinks only with a supported link/permission path.

Give an escaping input, violated boundary and file operation. Locate the unsafe operation or ineffective check. Fixed paths, safe mappings and effective containment refute the corresponding path. Record essential unknown roots or filesystem behavior in `limitations`.
