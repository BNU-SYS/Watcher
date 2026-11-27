### CWE-94: Code injection

- Trace external input into dynamically evaluated code or a dynamically selected callable: `eval`, `assert` on versions that evaluate a string argument, `create_function`, a variable function call such as `$fn(...)`, `call_user_func`, `call_user_func_array`, `forward_static_call`, and variable variables such as `$$name`.
- Establish what the input controls: a code string, a function name, or the argument list. Explain whether the input can select an unintended callable or inject syntax. A callable taken from a fixed internal list, or a name validated against an allowlist, refutes the candidate.
- Require the selected name itself to be externally controlled. A callable that is a visible literal, a closure written in the file, a method on a fixed object, or a variable assigned from a visible literal is not externally controlled merely because it is held in a variable. Do not infer taint from a variable name alone. An undefined variable is not externally controlled.
- When a dynamic construct resolves outside the reviewed scope, record the gap in `limitations` instead of asserting a defect.

#### Finding location

- The primary operation is the evaluation or dynamic-call site itself, such as `eval`, `create_function`, the variable function call, `call_user_func`, or `call_user_func_array`. Explain what the input controls: code, function name, or argument list.
