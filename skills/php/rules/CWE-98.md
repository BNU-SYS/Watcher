### CWE-98: File inclusion

- Trace external input into the path argument of `include`, `include_once`, `require`, or `require_once`. Identify the intended allowed directory and a concrete way to escape it, such as parent traversal, absolute-path replacement, or introducing a remote or stream wrapper (`http://`, `php://`, `data://`).
- Normalization alone does not enforce containment. Check that the validated final path is the path actually used for loading, and that containment uses path-component semantics rather than a vulnerable string prefix comparison.
- Distinguish lexical containment from filesystem resolution. Discuss symlink escape only with evidence that a relevant link can exist or be controlled; do not invent a race, link, or attacker permission to create a finding.
- Fixed trusted paths, safe identifier-to-path mappings, and effective containment checks refute the corresponding traversal path.

#### Finding location

- The primary operation is the `include`/`require` statement whose path argument is built from external input. Explain the resolved path and why containment fails or is absent.
