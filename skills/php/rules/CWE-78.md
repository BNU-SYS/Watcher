### CWE-78: OS command injection

- Identify the command execution boundary and the actual command interpretation: `system`, `exec`, `shell_exec`, `passthru`, `popen`, `proc_open`, or the backtick operator. Trace external data into the command string, or into the selection of the executable and its arguments.
- Distinguish ordinary argument values from command interpretation. Show the actual mechanism that changes the executed command or its arguments; do not infer it from the API name alone. Option injection alone is not sufficient for a CWE-78 finding when no command-execution effect is established.
- Distinguish `escapeshellcmd` from `escapeshellarg`. `escapeshellcmd` escapes shell metacharacters but does not stop a value from being taken as an extra option argument; a value placed inside a single command argument needs `escapeshellarg`. Neither constrains which command or which flag is chosen. Account for effective allowlists and quoting rules.

#### Finding location

- The primary operation is the call that starts the external command, such as `system`, `exec`, `shell_exec`, `passthru`, `popen`, `proc_open`, or the backtick operator. Explain the command string and the part the input controls.
