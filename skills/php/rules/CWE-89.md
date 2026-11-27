### CWE-89: SQL injection

- Trace an identifiable external input through string concatenation, interpolation, or formatting into SQL passed to an execution API, such as `mysql_query`, `mysqli_query`, `mysqli::query`, `PDO::query`, or `PDO::exec`. Explain which query syntax the input can change.
- Inspect where the SQL is constructed even when a prepared statement is used: preparing an already concatenated string does not undo injection. Conversely, values passed through placeholders and binding APIs are not SQL syntax.
- Dynamic identifiers or clauses need a concrete allowlist or safe mapping; ordinary value placeholders do not bind table or column names. Confirm the validation that actually exists before reporting a bypass. `mysqli_real_escape_string` escapes for one connection charset and does not protect identifiers; `addslashes` is not a reliable substitute. Do not invent database-specific behavior.
- SQL-looking text without a demonstrated execution path, fixed trusted query fragments, and correctly bound values are insufficient evidence.

#### Finding location

- The primary operation is the database call that executes the concatenated or dynamically built SQL, such as `mysqli_query`, `PDO::query`, `PDO::exec`, or a `query`/`exec` method call. Explain the query text and the syntax the input can change.
