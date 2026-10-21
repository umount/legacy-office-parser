# RTF extraction research and scope

## References inspected before implementation

- Microsoft, **Rich Text Format specification 1.6**, May 1999:
  [index](https://learn.microsoft.com/en-us/previous-versions/office/developer/office2000/aa140277(v=office.10))
  and [RTF Syntax](https://learn.microsoft.com/en-us/previous-versions/office/developer/office2000/aa140284(v=office.10)).
  The official syntax page establishes scoped groups, case-sensitive control
  words, delimiters, escaped symbols and optional destinations. Some legacy
  section links redirect to the Learn homepage. The 1.9.1 download (Microsoft
  download ID 10725, March 2008) was located, but its original download is no
  longer available; this work does not claim to have reviewed that full edition.
  Microsoft's published Unicode/fallback rules were also checked against the
  [Microsoft 1.7 specification hosted by latex2rtf](https://latex2rtf.sourceforge.net/RTF-Spec-1.7.pdf).
  Specifications are factual references; no Microsoft sample reader code copied.
- [WordCraft](https://github.com/storytold/wordcraft), commit
  `e05b7fe86f3b85454000dffc321de638d7009817`, MIT.
  Local checkout: `crates/formats/src/rtf.rs` (not `crates/rtf`). Inspected
  `Reader`, font/codepage dispatch, Unicode handling and `parse_full` tokenizer.
  Useful design references: scoped state, destination inheritance, font codepage
  precedence and explicit row/cell boundaries. No Rust source was translated or
  copied. Existing package attribution is in `licenses/WORDCRAFT-MIT.txt`.
- [striprtf](https://github.com/joshy/striprtf), release tag **v0.0.29**,
  [source](https://github.com/joshy/striprtf/blob/v0.0.29/striprtf/striprtf.py),
  BSD-3-Clause, copyright Joshy Cyriac; current `master` also inspected on
  2026-10-21. Its source credits the gilsondev RTF stripping gist. Reviewed for
  text and table extraction: stacked Unicode state, destination
  suppression, charset selection and accumulated hex bytes. Its regex pipeline,
  picture preprocessor, hyperlink substitution and source tables were not
  copied/adapted. Neither striprtf nor its dependencies are required or vendored.

`rtf.py` is an original standard-library implementation. Names, numeric charset
identifiers and control semantics are RTF format facts. No third-party code or
fixtures were incorporated, so no additional copied-code license text is needed.

## Extraction contract

`parse_rtf_bytes(data: bytes, limits: Limits) -> Document(format='rtf')` accepts
uncompressed RTF version 1, optional UTF-8 BOM and leading ASCII whitespace.
UTF-16-encoded or compressed RTF is rejected with `InvalidDocumentError`.
Trailing whitespace is accepted; other data after the root is rejected.

The iterative byte lexer handles exact-length opaque binary tokens, groups,
control words/symbols, bounded literal runs and hexadecimal escapes. The reader
keeps group-scoped codepage/font, Unicode fallback and destination state. All
fallback tokens (including controls and complete binary tokens) count as one;
raw bytes count individually and braces terminate fallback. Signed UTF-16 units
are combined into scalars; unpaired surrogates become U+FFFD with a warning.
Contiguous raw and hex bytes use a bounded incremental decoder, including across
scratch-buffer boundaries. Font `cpg` overrides `fcharset`, which overrides the
document codepage. Undefined/default charsets inherit the document codepage;
unsupported charsets/codepages and bad byte sequences produce warnings.

Body paragraphs preserve tabs, soft line breaks and explicit empty paragraphs.
Field results are retained, instructions omitted. Headers/footers, footnotes and
endnotes go into existing separate model fields. Metadata destinations (including
`info`, title and author) are deliberately omitted: the shared model has no
metadata field. Unknown optional destinations cannot reopen a skipped parent.
Pictures, objects and their fallback results are suppressed, including opaque
binary data. Hidden and deleted text are omitted. `upr` selects its Unicode
alternative; an absent Unicode alternative is not recovered from ANSI.

Tables preserve row/cell structure, empty positions and multiple paragraphs per
cell. Missing trailing cells are filled from row definitions. Incomplete rows
are recovered with warnings. Consecutive rows coalesce into a table. Merged cells
remain separate positions with an explicit warning; spans are not inferred.
Nested table markers flatten with a warning; nested row definitions can split
rows. Tables in secondary stories flatten to tabs/newlines. Shape containers,
annotations, equations, layout, styling, numbering generation, alternate-font
runs and HTML-encapsulated mail are outside this first version. Standalone
`shptxt` can be retained as textbox text, but text inside skipped shapes is not.
This is focused extraction, not full RTF compatibility or rendering.

## Limits and validation

File/stream byte limits are checked before parsing; binary lengths are checked
before advancing without allocating payloads. Group pushes, lexical records,
cell definitions/allocations and output appends are budgeted. Text includes
secondary stories; synthetic separators stored in story strings are charged.
The existing `Document.text` convenience property's generated body separators
are not included in `max_text_chars`. Scratch decoding is bounded to 4096 bytes
(or the smaller text budget). Control names are capped at 32 letters; numeric
parameters exceeding ten digits are rejected deliberately rather than allocating
arbitrary precision integers. Syntax errors use `InvalidDocumentError`; budget
errors use `LimitExceededError`; both are `ParseError` subclasses.

All committed tests are original synthetic fixtures: encodings, codepage scope,
fallback token forms, binary/group isolation, fields, stories, tables, malformed
inputs, each relevant limit and deterministic token mutations. Read-only local
smoke checks on 2026-10-21 parsed the authorized 1 MB sample (one table, six rows,
24 cells) and synthetic contract sample. No sample bytes or extracted text were
copied into the package, tests or this research note. Smoke results establish
successful extraction, not comparison against an authoritative renderer.
