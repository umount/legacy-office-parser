# RTF

## Supported

- Scoped groups, Unicode/fallback bytes, font codepages, paragraphs, headings,
  tables and nested tables; supported hidden/deleted text is omitted.
- Structured auxiliary stories, notes, headers/footers and explicit legacy
  textbox/WordArt text. Fields contribute stored visible results, not commands.
- Legacy `shprslt` textboxes are read when their owning shape has no native
  `shpinst`, `shptxt` or child-shape representation. Presence wins even if the
  native representation is empty, hidden or later in the file. Independent
  shapes remain independent; duplicate result branches are ambiguous and skipped.
- Required column breaks preserve text boundaries. Numeric codepage identifiers
  use available Macintosh, ISO-8859 and KOI8 aliases as well as Windows encodings.
- Explicit WordArt supports the verified CP1250/1251/1252/1253/932 subset.
  Suppressed destinations stay suppressed; codepage selection is scoped.
- Absent metadata, styles, field results and empty auxiliary destinations do
  not block body text. A single literal terminal NUL after the root is tolerated
  with a warning; arbitrary trailing data is not.

## Limits and remaining work

Shape results are read only through their legacy `do` / `dptxbxtext` structure;
stray text, modern shapes inside a legacy result and opaque destinations remain
suppressed. A native representation without text is not replaced by its fallback.
Full revision semantics, annotation bodies, generated lists, images, embedded
objects and layout are outside current coverage. Parsing uses shared depth/text/record
budgets, including skipped destinations and binary payloads.

## References

- [Microsoft codepage identifiers](https://learn.microsoft.com/en-us/windows/win32/intl/code-page-identifiers): numeric encoding IDs.
- [Microsoft RTF syntax](https://learn.microsoft.com/en-us/previous-versions/office/developer/office2000/aa140284(v=office.10)): groups, destinations and escapes.
- [RTF 1.7 specification](https://latex2rtf.sourceforge.net/RTF-Spec-1.7.pdf): Unicode, tables and drawing text; hosted copy of Microsoft's specification.

Tests are in `tests/test_rtf*.py`, with literal synthetic regressions and optional
LibreOffice readback. The reader is independently written; consulted WordCraft
and striprtf versions/licenses are listed in [provenance](../THIRD_PARTY.md).
