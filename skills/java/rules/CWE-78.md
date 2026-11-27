# CWE-78: OS Command Injection

Report when controlled input changes an executed command through an interpreter, executable selection or another supported command-processing contract.

1. Trace input to process execution and determine the executable and argument boundaries. Check explicit shells such as `sh -c`, `cmd /c` or PowerShell.
2. Give an input that changes interpreted command syntax. Check allowlists, fixed mappings and interpreter-specific quoting on the final command.
3. Inspect the invoked program's contract when it interprets an argument as a command. Ordinary `ProcessBuilder` arguments and `Runtime.exec(String)` require evidence of such interpretation.

Identify the input, interpreter, constructed command and effective bypass. Locate execution, including `.start()` in a multi-line builder expression. Mere option injection or metacharacters in a literal argument supply insufficient evidence.
