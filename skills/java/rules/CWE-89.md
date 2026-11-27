# CWE-89: SQL Injection

Report when controlled input becomes syntax in executed SQL and changes the intended query.

1. Establish input influence and trace concatenation, formatting, aliases and helpers into SQL.
2. Locate `executeQuery`, `executeUpdate` or prepared-statement execution. Inspect SQL construction before preparation as well as subsequent value bindings.
3. Check placeholders, fixed fragments and allowlists. Dynamic table/column names require identifier controls; value placeholders protect bound data.

Give a syntax-changing input, query construction and execution boundary. Locate execution or the smallest useful executed-query range. Effective bindings and fixed mappings refute that path. Record essential unknown origins or database behavior in `limitations`; establish exploitation without inventing driver or multi-statement settings.
