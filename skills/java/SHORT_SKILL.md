# Java CWE Prescreening

Rank requested types by visible operations. Keep plausible local mechanisms for detailed review when caller or dependency context is missing.

- CWE-20: Input validation. Invalid ranges, lengths, formats, paths or generic type constraints reach a consuming operation. Inspect hostile-input regex complexity.
- CWE-22: Path traversal. Controlled path components escape an intended root during file access or extraction.
- CWE-78: Command injection. Controlled input changes executed syntax through a shell, interpreter or executable selection.
- CWE-79: XSS. Controlled content reaches executable browser context without effective context-specific protection.
- CWE-89: SQL injection. Controlled input becomes executed SQL syntax, including concatenation before preparation.
- CWE-94: Code injection. Controlled input becomes executable instructions through evaluation, generation or compilation.
- CWE-352: CSRF. A sensitive browser action uses ambient credentials with ineffective intent checks or predictable anti-CSRF tokens.
- CWE-369: Divide by zero. A feasible zero divisor reaches integral division, remainder or an applicable numeric API.
- CWE-434: Dangerous upload. Uploaded content becomes dangerous through storage, serving, execution or processing.
- CWE-476: Null dereference. A supported null origin reaches a dereference or unboxing without an effective guard.
- CWE-502: Unsafe deserialization. Input constructs unsafe objects or state without effective type, graph or invariant restrictions.
- CWE-611: XXE. XML input can trigger external entity or DTD resolution through the effective parser configuration.
- CWE-772: Resource leak. An owned external resource escapes reliable cleanup without ownership transfer.
- CWE-787: Out-of-bounds write. Unsafe or native operations write beyond a memory region's bounds.
- CWE-835: Infinite loop. EOF, unchanged positions, encoder underflow, an exhausted index stuck at its limit, stale retry state or counter wraparound prevents termination.
- CWE-862: Missing authorization. A protected action lacks a required permission, ownership or tenant decision.
- CWE-918: SSRF. Controlled input directs server-side retrieval beyond an intended destination boundary.
