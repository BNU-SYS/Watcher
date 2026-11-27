### CWE-89: SQL injection

- Establish the origin: identifiable untrusted input (a parameter, `config`, an environment variable, request data, etc.).
- Identify the concatenation method: an f-string, `%` formatting, `str.format`, `+` concatenation, or `.join`.
- Identify the execution entry point: `cursor.execute`, `executemany`, `pandas.read_sql`, etc.
- Dynamic identifiers: a table or column name, `ORDER BY`, or `LIMIT` derived from input needs a concrete allowlist or safe mapping.
- Do not report values passed through DB-API placeholders (`%s`, `?`, `:name`) and bound as a separate parameter sequence, fixed trusted query fragments, or SQL text with no execution path.
- Concatenating first and passing the whole string still injects even when a parameterized API is available; do not exclude it for that reason. Ordinary value placeholders cannot bind identifiers, and dynamic identifiers validated against a strict allowlist are not a defect.

#### Example

```python
def find_account(cursor, name):
    cursor.execute(f"SELECT id FROM accounts WHERE name = '{name}'")
```

#### Finding location

- The primary operation is the query-construction expression where the untrusted input is concatenated into the SQL text. Cite the execution call that receives the statement in `explanation`.
