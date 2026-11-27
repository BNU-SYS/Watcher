### CWE-79: Cross-site scripting

- Trace external input to a browser-visible output: `echo`, `print`, `printf`, `vprintf`, `print_r`, `exit`, `die`, or interpolation inside an HTML string written to the response. Note that `exit` and `die` write their string argument to the response. Identify the output context: HTML body, attribute value, URL, JavaScript, or CSS.
- Check whether escaping is applied to the value actually written and matches that context. `htmlspecialchars` with `ENT_QUOTES` and an explicit encoding covers HTML text and quoted attribute contexts; it does not make a value safe in a JavaScript or URL context. Escaping applied on another branch, to another alias, or to a value later reassigned does not protect the written value.
- Distinguish output that reaches the response from output written only to logs, local files, or CLI streams. Without a path to the response, do not report a server-side file write or an error stack trace as CWE-79.
- Literals, fixed template fragments, values constrained by an allowlist, and values escaped immediately before output are insufficient evidence.

#### Finding location

- The primary operation is the output statement that writes the unescaped value to the response, such as `echo`, `print`, `printf`, `exit`, or `die`. Explain the output context and why the escaping present, if any, does not cover it.
