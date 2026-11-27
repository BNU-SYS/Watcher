# PHP CWE candidate index

- CWE-89: External input reaches a SQL statement passed to a database execution API without parameter binding, so the input can change the query's syntax or structure.
- CWE-79: External input reaches an HTML, attribute, URL, or script output context without context-appropriate escaping, so the input can execute as markup or script in a browser.
- CWE-78: External input reaches a shell or process-execution API such as system, exec, shell_exec, passthru, popen, proc_open, or backticks without effective argument separation, so it can change the executed command or its arguments.
- CWE-98: External input controls the path passed to include, include_once, require, or require_once, allowing an attacker to load an unintended local or remote file.
- CWE-94: External input reaches a code-evaluation or dynamic-call mechanism such as eval, create_function, a variable function, call_user_func, or a dynamic callback, so attacker-controlled code or function selection is executed.
- CWE-470: External input selects the class, method, or callable used with new, ->, ::, or a callable API, allowing an attacker to invoke unintended code.
- CWE-352: A state-changing operation driven by request parameters is reachable with the victim's existing session credentials and without a verified anti-CSRF token, so another site can trigger it.
- CWE-862: An authenticated request reaches an object or privileged action through a user-controlled identifier without an ownership, role, or permission check, so the user can act beyond their authorization.
- CWE-22: External input reaches a filesystem API such as readfile, file_get_contents, fopen, unlink, copy, rename, scandir, or file_put_contents in a way that .., an absolute path, or a stream wrapper can escape the intended directory.
- CWE-434: An uploaded file's name or extension is attacker-influenced and reaches move_uploaded_file, copy, rename, or file_put_contents without a server-side extension whitelist or a safe generated name, allowing a dangerous file type to be stored.
- CWE-502: External input reaches unserialize, possibly after base64, URL, gzip, or hex decoding, without signature verification or a class allowlist, allowing attacker-controlled objects to be instantiated.
- CWE-918: External input controls the scheme, host, port, or path of an outbound request made with cURL, file_get_contents, fopen, readfile, get_headers, simplexml_load_file, or a stream context, without a destination allowlist.
