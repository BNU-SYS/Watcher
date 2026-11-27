# CWE-94: Code Injection

Report when controlled data changes program instructions that are actually interpreted or executed.

1. Trace input into generated source, scripts or expressions and identify the interpreter/language.
2. Establish execution through evaluation APIs or a reachable compilation-and-execution flow.
3. Give an instruction-changing input and check data bindings, fixed operation mappings, language restrictions and effective isolation policies.

Locate evaluation or the smallest useful executed-code construction. Distinguish reflection on approved targets, inert source text and effectively bound data. Use CWE-89 or CWE-78 for the same SQL or shell root cause. Record essential unknown interpreter or execution behavior in `limitations` and limit impact to supported capabilities.
