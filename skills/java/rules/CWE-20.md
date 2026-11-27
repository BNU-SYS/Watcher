# CWE-20: Improper Input Validation

## Report only when

An accepted input violates a required constraint and causes a concrete local failure or documented output-invariant violation.

## Review steps

1. Identify the input boundary, required constraint and consuming operation. Public parser/utility arguments and deserialization callbacks can establish local boundaries. Support attacker reachability separately.
2. Trace guards, conversions and early exits on the actual value used. Inspect ranges, lengths, sign, field relationships and structured path grammar. Successful parsing alone establishes only the parsed syntax or type.
3. Follow generic type information through parsing. Replacing a `Type` or `ParameterizedType` with a raw `Class` can lose required nested element constraints. Demonstrate the resulting mismatch.
4. Check fields restored by `defaultReadObject()` before use, including directory and NUL constraints. For path normalization, inspect UNC host/prefix validation separately from later dot-segment handling.
5. Inspect regex validation as a consuming operation. Repeated groups with overlapping quantifiers can cause superlinear backtracking. Construct a long near-match that fails late, and check effective length bounds, disjoint structure or atomic/possessive behavior. Establish the resource-exhaustion consequence for hostile input.

## Evidence and exclusions

Give a concrete invalid input, violated constraint, unsafe use and consequence. Locate the ineffective check or use. Prefer a more specific requested CWE for the same root cause. Missing validation syntax, invented business rules and hypothetical downstream behavior supply insufficient evidence. Record essential unknowns in `limitations`.
