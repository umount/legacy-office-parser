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
are recovered with warnings. Consecutive rows coalesce into a table. Explicit
horizontal and vertical merges in complete ordinary rows reconstruct model spans
and retain covered coordinates. Unsupported or ambiguous merges remain separate
with warnings; see the fidelity audit below for the precise acceptance rules.
Nested table markers flatten with a warning; nested row definitions can split
rows. Tables in secondary stories flatten to tabs/newlines. Shape text stories
are collected into `textboxes` by traversing recognized shape containers;
properties, drawings and legacy shape results remain omitted. Annotations,
equations, layout, styling, numbering generation, alternate-font runs and
HTML-encapsulated mail are outside this version.
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

All tests discussed here use original synthetic fixtures: encodings, codepage
scope, fallback token forms, binary/group isolation, fields, stories, tables,
malformed inputs, relevant limits and deterministic token mutations.

## Practical table/text fidelity audit — 2026-10-21

The development oracle was **LibreOffice 7.4.7.2 40(Build:2)**, invoked headlessly
on seven independently authored synthetic RTF documents. Each invocation used a
unique temporary `-env:UserInstallation=file://...` profile, `SAL_USE_VCLPLUGIN=svp`
and a 45-second subprocess timeout. Output was FODT, inspected with the standard
library XML reader. LibreOffice is optional, development-only: there is no
production/runtime dependency, network service or parser subprocess path.
The sandboxed initial launch exited 1 without output documents; the successful
comparison used the authorized external process launch with the same isolation.
Only synthetic inputs were opened.

### Observed results

- Ordinary two-row table between body paragraphs: both readers retain all six
  text markers, in order, with the same two-by-two cell structure.
- Row properties following cell content: both retain Alpha, Beta and After;
  the parser additionally reports its existing missing-initial-definition recovery.
- Horizontal merge followed by an ordinary three-column row: LO exports an
  explicit two-column span. Before the fix the parser returned two independent
  cells; afterwards it returns `col_span=2` and an empty covered coordinate.
- Vertical merge: LO exports a two-row span. The parser now returns `row_span=2`
  and a covered coordinate in the following row, preserving adjacent text.
- Combined rectangular merge: both now represent a two-by-two span, with all
  neighboring text preserved. An ordinary grid row follows the merge in the
  oracle test so LO retains the physical column boundaries.
- Nonempty horizontal continuation: LO retains Anchor and Continuation as two
  paragraphs in one cell. The parser now joins them with a newline in the anchor
  and clears only the covered cell, retaining each marker exactly once.
- Textbox nested inside a shape: the initial audit confirmed that LO retained
  ShapeText while the parser omitted it. The follow-up below fixes that loss;
  the oracle now requires extraction parity on this fixture.

LO collapses columns merged in every row, so raw cell counts or plain-text
whitespace are unsuitable equivalence oracles. The tests compare known synthetic
markers, explicit ODF spans on a retained grid, and independently specified model
cells. They do not call this parser to generate expected output.

### Implemented boundary

Merge reconstruction happens when an ordinary row ends, after any repeated row
properties have replaced earlier definitions. Definitions and cell allocations
remain subject to the existing cumulative `max_cells` budgets. Cell boundaries
must be present and strictly increasing relative to `trleft` (default zero).
Horizontal continuation markers require a preceding start marker; combined
horizontal groups must agree on their vertical flags. Invalid definitions reject
reconstruction for the entire row before any cells are changed.

Vertical continuations require an explicit start in an immediately preceding
compatible row, the same left/right boundaries and physical column indices,
and empty continuation text. An ordinary intervening row, a body paragraph,
recovery, detected nested-table controls or changed geometry ends the chain.
Nonempty or unmatched vertical continuations retain their text and warn rather
than deleting it. Horizontal merging can still succeed within such a row.
Each story has its own merge state. Missing trailing cells and unterminated rows
retain the existing conservative recovery, without guessed spans.

Original cell fragments are joined once per horizontal group. Only inserted
newlines consume additional text budget; original characters were already
charged. Covered coordinates stay in the shared model and have empty text, so
`Document.text` and flattened story output do not duplicate merged text. No shared
model or renderer changes were necessary. Auxiliary merge state is linear in the
number of row definitions, bounded by existing cell limits; vertical spans update
anchors in place without accumulating or repeatedly copying text across rows.

### Reproduction and evidence

From the package root:

```sh
.venv/bin/pytest -q
.venv/bin/ruff check src/legacy_office_parser/rtf.py tests/test_rtf_fidelity.py
RTF_FIDELITY_LO=1 .venv/bin/pytest -q tests/test_rtf_fidelity.py
```

Observed results: **501 passed, 1 skipped** in the complete default suite;
**21 passed** with the development oracle enabled; Ruff passed for both changed
Python files. The default skip is the explicitly opt-in LibreOffice test. Seven
selected independent new regressions were also run against the saved pre-change
parser: all seven failed (horizontal, vertical/combined, continuation text,
Unicode/field paragraphs, repeated definitions, three-row chains, merge budget).
They pass against the changed parser. Existing RTF tests remain unchanged.

### Remaining limitations

Full LibreOffice parity is **not established**. Nested table definitions remain
flattened and can interfere with outer-row structure. Annotations and equations
are still omitted; missing Unicode `upr` alternatives
are not recovered from ANSI. Layout/styling and arbitrary irregular or incomplete
merge geometry are outside this change. Nonempty vertical continuations are
preserved separately with warnings instead of assuming how to attach their text.
Rows using different physical grids are conservatively refused for vertical
merging; column grids are not normalized across the whole table. Consecutive rows
without a separating body paragraph retain the existing table-coalescing policy.
Story tables flatten spans to text. Only the described synthetic cases were
compared with this LO version, not a general real-world compatibility corpus.

## Follow-up: shape text stories — 2026-10-21

### Reference and narrow implementation

Rechecked Microsoft's RTF specification, the
[Word 97–2000 drawing-object section and shape properties](https://latex2rtf.sourceforge.net/rtfspec_7.html).
It places `shptxt` inside `shpinst`, describes `shprslt` as the legacy drawing
representation, permits nested `shpgrp` containers, and puts the entire linked
textbox story in the first box. Property groups use `sp`, `sn` and `sv`. These
format semantics informed the implementation; no sample parser code was copied.

A group-scoped `shape_container` flag distinguishes traversal from visible text.
`shp`, `shpinst` (including starred form) and `shpgrp` allow traversal; only
`shptxt` starts a text sink. Container text and layout controls do not produce
body output. Property groups, `shprslt`, pictures, objects, background drawings
and unknown optional destinations remain hard skips. A skipped ancestor always
wins, including when it contains a recognized shape or text destination.
Binary payloads retain the existing exact-length opaque lexer path and limits.

Shape stories use the existing `Document.textboxes` field. Paragraphs, fields,
Unicode, inherited codepages, hidden/deleted runs and simple tables reuse the
ordinary text path. Shape stories are isolated from body tables and headers;
merged story tables flatten as before. Inherited hidden/deleted status is not
cleared on entering `shptxt`. Surrogates cannot join across story boundaries.
Legacy `shprslt` is always skipped, whether before or after the primary story,
so it cannot duplicate text. Separate real stories with identical text are both
retained: there is no heuristic content deduplication.

### Synthetic comparison and regression evidence

The existing shape fixture now requires ShapeText in both the LO textbox and
parser output. A second original fixture follows the specified nesting:
`shp` → starred `shpinst` → properties plus `shptxt`, with a sibling `shprslt`
containing a legacy textbox representation. Its two paragraphs, CanonicalText
and Second α, appear exactly once in both readers. The surrounding body remains
BeforeAfter. FODT comparisons select `draw:text-box` paragraphs directly: using
all ancestor `itertext()` calls would count drawing text twice in the oracle
itself. The suite now converts eight synthetic RTF files in one invocation.

LibreOffice remains development-only, version 7.4.7.2, with a unique pytest
temporary profile, headless conversion and a 45-second timeout. The commands
listed above are unchanged. Final observed results:

- RTF tests: **113 passed, 1 skipped** (the opt-in oracle).
- Fidelity suite with `RTF_FIDELITY_LO=1`: **41 passed**, including LO comparison.
- Complete suite at the final workspace snapshot: **615 passed, 2 skipped**.
- Ruff on the two changed Python files: passed.
- Eight selected new shape regressions against the saved pre-shape parser: all
  eight failed; they pass with this change. They cover the original loss,
  property isolation, fallback ordering, grouped stories, text fidelity,
  body/header isolation, opaque binary data and output budgets.

Additional cases exercise hard-skipped ancestors, nested groups, identical
independent stories, property payloads excluded from text budgets, story separator
budgets, cell/depth/record limits, malformed binary lengths and surrogate
boundaries. No existing shared tests, tools or model files were edited.

### Remaining shape limitations

This extracts text, not drawings or layout. There is no geometry, z-order or
linked-box layout reconstruction. Textbox stories are listed in source traversal
order in the existing aggregate field, rather than placed at body anchors.
Fallback-only `shprslt`, legacy `do` drawings, background shapes and text hidden
under ignored destinations remain unsupported. Missing primary stories are not
reconstructed from pictures or legacy fallback. Arbitrary malformed shapes and
all producer variants have not been compared with LO. Existing nested-table and
other format limitations above still apply; full LO parity is not claimed.
