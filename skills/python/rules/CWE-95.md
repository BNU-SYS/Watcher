### CWE-95: Eval / exec code injection

- Establish the origin of the untrusted value: a parameter, request data, environment variable, configuration value, file content, or a value derived from them.
- Identify the execution sink: `eval`, `exec`, `compile` followed by `exec`/`eval`, or `__import__` applied to an input-derived module name.
- Establish that the untrusted value reaches the sink as the expression, statement, or module name, and that no safe parser is used instead.
- Do not report `ast.literal_eval`, `json.loads`, `int`/`float` conversion, or a call whose argument is a fixed literal defined in the same file.
- A constant-looking string that is visibly assembled from an untrusted value is still a finding; do not exclude it because the final expression looks like code.
- Do not report CWE-95 when the dynamic import or class construction is part of a deserialization loader consuming serialized data; report CWE-502 instead.
- Do not report CWE-95 when the sink is a template engine or sandbox formatter; report CWE-1336 instead.
- Report CWE-95 only when source text, a statement, an expression, or a module name is evaluated directly.

#### Example

```python
def evaluate(expression):
    return eval(expression)          # arbitrary code execution
```

#### Finding location

- The primary operation is the `eval`/`exec`/`compile` call that receives the untrusted value. Cite the origin and the absence of a safe parser in `explanation`.
