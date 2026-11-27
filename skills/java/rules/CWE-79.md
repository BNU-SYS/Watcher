# CWE-79: Cross-site Scripting

Report when controlled content can become executable browser content through ineffective context-specific encoding or sanitization.

1. Establish the HTML, attribute, JavaScript, CSS or URL context. Trace response/template construction and final encoding. Check effective template defaults and response types.
2. For an encoder or sanitizer API, use its documented target context and test a concrete payload against the transformation. An accepted executable URL or unescaped delimiter can establish a local contract violation.
3. For JavaScript encoders, distinguish standalone-source, quoted-string and inline-HTML-script contracts. Check quote/backslash handling and closing-script delimiters against the promised context, using the selected library contract. A generic encoding call requires this context check.
4. Check canonicalization, scheme restrictions and contextual escaping on the final value. Correct HTML text encoding may leave a JavaScript string or URL context exposed.

Give the input, context, transformation and executable result. Locate the unsafe output or ineffective sanitizer. Record missing consumers when they determine interpretation. SAX `characters()` and equivalent text-node APIs carry text. Trace downstream rendering or a raw-output bypass to establish executable HTML. Correct contextual protection refutes the payload. Reflection, logging, storage and JSON data alone require a browser interpretation path.
