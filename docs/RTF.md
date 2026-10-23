# RTF

## Supported

- Scoped groups, Unicode/fallback bytes, font codepages, paragraphs, headings,
  tables and nested tables; supported hidden/deleted text is omitted.
- Structured auxiliary stories, notes, headers/footers and explicit legacy
  textbox/WordArt text. Fields contribute stored visible results, not commands.
- Explicit WordArt supports the verified CP1250/1251/1252/1253/932 subset.
  Suppressed destinations stay suppressed; codepage selection is scoped.
- Absent metadata, styles, field results and empty auxiliary destinations do
  not block body text. A single literal terminal NUL after the root is tolerated
  with a warning; arbitrary trailing data is not.

## Limits and remaining work

Old shapes with only fallback text remain unsupported unless source ownership
can be established. The absence of primary text alone does not prove that the
fallback is active. Full revision semantics, generated lists, images, embedded
objects and layout are outside scope. Parsing uses shared depth/text/record
budgets, including skipped destinations and binary payloads.

## References

- [Microsoft RTF syntax](https://learn.microsoft.com/en-us/previous-versions/office/developer/office2000/aa140284(v=office.10)): groups, destinations and escapes.
- [RTF 1.7 specification](https://latex2rtf.sourceforge.net/RTF-Spec-1.7.pdf): Unicode, tables and drawing text; hosted copy of Microsoft's specification.

Tests are in `tests/test_rtf*.py`, with literal synthetic regressions and optional
LibreOffice readback. The reader is independently written; consulted WordCraft
and striprtf versions/licenses are listed in [provenance](../THIRD_PARTY.md).
