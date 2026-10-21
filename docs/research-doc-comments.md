# DOC comments: passive text, authors, and source ownership

Research and implementation: 2026-10-22. Bounded passive DOC comment extraction
uses primary MS-DOC specifications and original fixture data. LibreOffice 7.4.7.2
is used only as an independent fixture reader/exporter, never as a runtime
dependency. No macros, fields, or links are evaluated.

## Extraction gap addressed

Before this change, `_Doc.parse()` skipped story index 3 and emitted
`Comment story text is omitted; the output model has no comments field.`
The source text budget already included this story. The existing structured
footnotes/endnotes model provided the shared-body design used here.
`SlideComment` belongs to presentations and cannot express a DOC source range.

The new original fixture demonstrates actual lost text and ownership: three
comments with two authors, two equal bodies, a point comment, a ranged comment
preceded by an astral character, and a two-paragraph comment on text in a table
cell. The previous parser preserved main text but none of the comment bodies.
The implementation closes this bounded text/structure gap without adding layout.

## Primary record definitions

All offsets below are zero-based indices in the FIB fc/lcb pair array, not fixed
absolute file offsets. Use the existing FIB reader and selected Table stream.

- [FibRgFcLcb97](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/0c9df81f-98d0-454e-ad84-b612cd05b1a4):
  pairs 4/5 locate `PlcfandRef`/`PlcfandTxt`; 36 locates the author XST array;
  37 locates annotation bookmark metadata; 42/43 locate bookmark starts/limits.
  Pair 19 describes comment-story fields. Author names are unique, each length
  is below 56 UTF-16 units, and the array has at most 0x7FFF entries.
  Annotation bookmarks belong to main text. Comment-story length is `ccpAtn`;
  its global start follows main, footnote, and header stories.
- [PlcfandRef](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/9d82ca25-ff21-488c-bee2-dd654935c65a):
  N records occupy `34*N + 4` bytes: N+1 four-byte CPs, then N 30-byte
  `ATRDPre10` records. Used CPs are distinct main-story references to U+0005
  with effective `sprmCFSpec=1`. Ignore the last CP when locating references.
- [ATRDPre10](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/f2327847-8ba3-4b9c-b9a3-b0bdfac1206c):
  byte offsets 0..19 contain initials, 20..21 the author index, 22..25 two
  unused words, and 26..29 the bookmark tag. The tag is an identifier, NOT an
  index into bookmark arrays. `0xFFFFFFFF` denotes a zero-length selection;
  other values link to an ATNBE tag. Author index zero is valid.
- [LPXCharBuffer9](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/12dc49ca-7704-44f1-8136-c0cd721c5a35):
  the initials buffer has a two-byte length up to nine and 18 bytes of UTF-16
  storage. Decode only the declared units; ignore unused storage. It is not a
  null-terminated string. Empty initials do not imply a missing author.
- [PlcfandTxt](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/ac1c69d1-b6b9-4d2c-8cc6-4300e0ee5921):
  N bodies have N+2 CP slots and no payload records. Body boundaries are local
  to the comment story and pair with reference records by ordinal. Each body
  begins with U+0005/CFSpec and ends with CR at table depth zero. The penultimate
  CP is `ccpAtn-1`; the final slot is ignored as a boundary. Ranges must be valid
  selections. Do not reuse the note decoder unchanged: it lacks the required
  body-start marker and table-depth checks.
- [SttbfAtnBkmk](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/22d288b9-4d91-4dc6-a2e4-0bb847a1b6a1):
  extended STTB header is `FFFF, cData, 000A`; each entry has a zero-length
  string and ten-byte ATNBE payload. Its stated document bookmark limit is
  0x3FFB, although the field description permits `cData <= 0x3FFC`.
  Conservatively enforce the tighter document limit, and document this discrepancy.
- [ATNBE](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/c2871575-34c4-410d-ad94-c556e8bca8e0):
  two-byte annotation class 0x0100, four-byte unique `lTag`, and four unused
  bytes (`lTagOld`). Match the reference tag to `lTag`, then use that metadata
  entry's ordinal to select the corresponding bookmark-start entry.
- [Plcfbkf](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/82702014-0081-40af-8d4e-421db135f3ff),
  [FBKF](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/4dfad7b0-37bb-443a-8933-3bb79d2c5994),
  and [Plcfbkl](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/1c65c62e-2c88-4a85-8207-c7ec735fa7d8):
  starts have `8*M+4` bytes, limits `4*(M+1)`. FBKF contains a two-byte
  `ibkl` and two-byte BKC. `ibkl` selects the limit CP; it is not necessarily
  the same ordinal as the start. Limits are exclusive. Overlapping bookmarks
  may share CPs, so the strict distinct-reference rule is inappropriate here.
  Validate start <= limit and the main-story bounds; do not pair by sorting
  endpoints. Bookmark selection/table constraints need their own validation.
  [BKC](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/b59cbd01-2391-4b70-994c-b58104d3f4c0)
  requires `fCol=0` for annotation bookmarks; column-index fields are then
  ignored. An annotation with `fCol=1` is invalid, not a supported column range.

The source reference CP identifies the annotation marker, not the beginning of
the text being commented on. Nor is it an offset into normalized `Document.text`.
In the authored fixture the first range starts at CP 10 and its reference is
CP 20; the emoji makes Python character offsets differ from UTF-16 CPs.

## Optional metadata and ordering

[FibRgFcLcb2002](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/fce09f81-704b-460d-9bca-f7dc121aed66)
adds pair 112, `AtrdExtra`. Check effective FIB version and array length before
access; absence in older files is not an error.
[AtrdExtra](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/1b6a50f8-de0c-4020-bce0-06e24660c928)
is parallel to the base comment records and describes a preorder comment tree.
[ATRDPost10](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/19181fe7-a62a-4e70-9a5f-a0cb1ebe0921)
is 18 bytes: DTTM at 0, padding at 4, depth at 6, signed relative parent-record
offset at 10, and flags at 14. A parent is `current_index + diatrdParent`, not
an absolute byte offset; nonzero depth/parent expresses a reply. An ink flag
signals content that cannot be reconstructed as ordinary text.

Preserve stored comment/reference/body ordinal alignment before any filtering.
Do not deduplicate equal body strings or reorder by author, tag, timestamp, or
bookmark start. The implementation retains a flat list in stored order with an
explicit warning
for unmodeled reply/ink semantics; it does not label every entry a root comment.
Extra-array sizes and counts are checked before reading. A bounded ancestor stack
validates preorder depths and relative parents, rejecting forward/cyclic or
inconsistent references. Dates, reply-tree output, and ink rendering are not
implemented. No dates are synthesized.

## Public model and runtime integration

`Document.comments` contains `Comment` records and defaults to an empty list.
`Document.comment_text` is their shared text projection, appended once to
`Document.text` after the existing stories. Both fields are omitted from JSON
when empty. `story_blocks['comment_text']` stores the body blocks once.

`CommentBodyRange(story='comment_text', block_start, block_end)` references a
half-open range of those blocks. `Comment` carries a positive stored ordinal,
author, initials, source reference CP, nullable selection_start/selection_end,
a nullable anchor_path, and note-compatible visibility flags. Ordinal gaps are
preserved when an unproven body is omitted. No duplicate body text, normalized
text offsets, page coordinates, or inferred author names are stored in records.

The reference path targets the final Paragraph or Cell containing the marker.
It does not assert that the entire selection belongs to that container. Raw
half-open selection CPs are separate. Point comments use equal endpoints at the
reference CP; unresolved selections use null endpoints.

The bounded decoder builds reference/body descriptors and author/tag maps before
main extraction. Source markers are observed before cleaning text, as for notes.
Notes and comments share the existing identity-based anchor capture/resolution;
there is no separate main-text scan per comment. Resolve paths
only after table/frame partitioning and grid normalization. Do not relocate a
covered-cell anchor to a merge origin or treat omitted cells as source cells.
Existing note behavior and exact source CPs are preserved by regressions.

Parse each proven comment body through a fresh table assembler and field-state
boundary. Check the leading marker and final paragraph/table depth using effective
CHPX/PAPX, including applicable styles and piece modifiers. Filter body visibility
independently from reference visibility. Hidden/deleted/field-instruction markers
must not shift ordinal pairing. Unknown conditional-style context propagates
`unknown` just as it does for notes. Body fields expose only existing stored
results; never evaluate instructions. The reserved final comment-story CP is
excluded from the projection and all
body ranges; it is not an extra comment or part of the last body. Unlike notes,
comments have no legacy whole-story projection whose trailing newline must be
preserved. Unknown final-paragraph PAPX coverage omits that body with a warning
rather than assuming table depth zero.

## Active ownership, stale data, and failure policy

Only the current selected FIB/CLX and referenced comment tables establish
ownership. Never scan raw CFB bytes, old text pieces, unused author strings, or
bookmark names looking for comments. Annotation bookmarks are distinct from
protection bookmarks and do not justify new table-boundary heuristics.

Failure and uncertainty policy:

1. Missing body or reference PLC: keep the existing omission warning; do not
   promote the entire comment story to active comments. This is deliberately
   stricter than the legacy note whole-story fallback, since there is no legacy
   comment text projection to preserve.
2. Present malformed PLC, truncated author string, out-of-bounds used CP,
   duplicate reference CP/tag, invalid author index, inconsistent reference/body
   counts, or known-wrong required marker: raise `InvalidDocumentError`.
   Never repair by text matching or zip only visible references.
3. If effective marker properties are unknown rather than demonstrably invalid,
   warn and omit that unproven body from the active projection. Other proven
   bodies retain their original ordinals. No active anchor is published for the
   omitted body.
4. Valid body/reference ownership but missing range-bookmark metadata: retain
   body, author, and proven reference anchor with an unknown selection and a
   warning. A dangling non-point tag is not a point comment. Present structurally
   malformed bookmark arrays remain errors.
5. Unassigned prefix/suffix text is not an extra comment. An unexpected body
   prefix means coverage is unproven: warn and do not expose the unexplained
   text as active. The reserved final CP is structural, not orphan body content.

A raw CP range is not a proof that table selection constraints have been
validated. In phase one, restrict published exact selection spans to validated
ordinary text/within-cell ranges with known paragraph/table context; retain
source reference ownership and warn when more complex selection validity cannot
be established. All non-point spans are conservatively omitted if the main story
contains field delimiters; ranges splitting surrogate pairs are also unpublished.
Reject nonzero
annotation BKC.fCol, and use the fCol=0 bookmark rules rather than the rules
for table-column bookmarks.
Cross-paragraph, overlapping, and nested-table selections need independent
regressions before exact selection support is claimed. The fixture below only
proves two ordinary ten-character ranges and one point.

PLC slots, authors, tag maps, body descriptors, and published paths consume the
aggregate record budget before allocation. Bound bytes by
`max_stream_bytes`, source UTF-16 units by `max_text_chars`, body tables by the
existing cell/depth limits, and retained projections by the existing output
budget. Count repeated author strings in emitted metadata according to the API
budget rather than assuming internal string sharing protects serialization.
Author XST units (including unused owners) and every declared initials unit
are cumulatively added to the full DOC source length before decoding, with
`max_text_chars` checked before each allocation. This source bound is separate
from the retained-output bound, which charges repeated emitted authors/initials.
Dictionary joins, a constant number of source scans, and indexed selection lookup
avoid per-comment full-document scans. Selection lookup is O(log paragraphs) per
non-point range; parsing and anchor collection are otherwise linear in source
CPs, metadata, and traversed output. Main markers use dictionary membership,
never membership scans of a growing paragraph-anchor list. Limits raise
`LimitExceededError`; no fallback bypasses them.

## Original fixture and independent readback

Files are under `tests/fixtures/doc_comments/`:

- `authored.fodt`: hand-authored minimal XML; contains no external resources,
  macros, scripts, formulas, or field instructions. This source is reproducible
  as literal bytes and requires no generator dependency.
- `authored.doc`: LibreOffice export of that source, a real CFB file.
- `readback/authored.fodt`: a fresh LibreOffice import/export of the DOC.
- `inspect_fixture.py`: fixture-only raw FIB/CLX/PLC/CHPX inspection and independent
  XML readback extraction. It imports no production parser; it is not a new test
  suite or a general-purpose DOC decoder. The actual tests use its raw/XML
  evidence independently of the runtime decoder.
- `evidence.json`: saved output of that inspection, including exact raw records.

Observed with LibreOffice 7.4.7.2:

- Main/comment counts: 81/78 UTF-16 CPs; other stories are empty.
- References: 20, 38, 61; ignored reference sentinel: 82.
- Body CP array: 0, 17, 34, 77, 78. Bodies are [0,17), [17,34), [34,77).
- Author indices: 0, 1, 0; author strings: Ada Fixture, Ben Fixture.
- Initials: empty for all three. Tags: 0, 0xFFFFFFFF, 1.
- Bookmark starts: 10, 51; limits: 20, 61; `ibkl`: 0, 1.
- Main reference markers and global body starts 81/98/115 have a direct CHPX
  group of exactly `55 08 01` (`sprmCFSpec=1`), independently located through
  the BTE/FKP records. All required source units are U+0005.
- The first two bodies are independently owned copies of `Shared comment.`.
  The third contains `Cell comment: Ελληνικά.` and `Second paragraph.`.
  The Greek literal and emoji are intentional original Unicode evidence.
- Source and readback agree exactly on ordered authors, full body paragraphs,
  host-prefix character positions, and the two ten-character ranges. The point
  remains a point, including when LibreOffice wraps its annotation in a span.
- `AtrdExtra` contains three root records, no reply depth or ink flag. This does
  not establish reply, ink, or nonempty-initial fidelity.

The XML probe is intentionally fixture-specific. It does not establish arbitrary
ODF whitespace normalization or nested-table anchor fidelity. The raw probe
records bookmark bytes but does not implement general bookmark validation.
LibreOffice-produced binary/readback metadata may vary on regeneration; only
the original XML source is byte-stable. No broad office-suite parity is claimed.

The fixture's exact main projection is:

```text
Before 😀 RangeAlpha after.

PointBeta tail.

Cell RangeGamma end.

AfterTable.
```

The old output ended here. The current output appends the four comment
paragraphs once, with the two identical bodies retained as separate comments.
The positive fixture alone does not prove stale-content exclusion; synthetic
regressions additionally cover absent ownership PLCs, unassigned prefixes, and
unreferenced Table-stream bytes.

## Reproduction and checks performed

From the repository root, with a fresh isolated LibreOffice profile:

```sh
libreoffice -env:UserInstallation=file:///tmp/doc-comments-lo-profile --headless --convert-to 'doc:MS Word 97' --outdir tests/fixtures/doc_comments tests/fixtures/doc_comments/authored.fodt
libreoffice -env:UserInstallation=file:///tmp/doc-comments-lo-profile --headless --convert-to fodt --outdir tests/fixtures/doc_comments/readback tests/fixtures/doc_comments/authored.doc
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python tests/fixtures/doc_comments/inspect_fixture.py
.venv/bin/ruff check tests/fixtures/doc_comments/inspect_fixture.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -p no:cacheprovider tests/test_doc_comments*.py
PYTHONDONTWRITEBYTECODE=1 OFFICE_CORPUS_LIBREOFFICE=1 .venv/bin/pytest -q -p no:cacheprovider tests/test_doc_comments_ole.py
```

Both real conversions returned exit code 0. Independent source/readback
comparison matched all three comments. The saved and live conversion tests
compare raw ownership with XML authors, complete body paragraphs, selection
text, and final structural reference paths. Converter-generated identifiers
and metadata are not treated as stable expected values.

## Regression coverage and remaining scope

Independent decoder, integration, and real-CFB tests cover:

- All three authored relationships, duplicate bodies/different authors, nonempty
  initials, astral CP offsets, point/range distinction, and JSON/text deduplication.
- Permuted bookmark tags and nonidentity `ibkl`; overlapping equal endpoints;
  invalid/absent owner data; duplicate tags; bounds/truncation at every record type.
- Absent/count-mismatched PLCs, unexplained prefixes, ignored sentinels, stale
  unreferenced Table-stream bytes and declared story text without live ownership
  PLCs; unused author metadata still consumes the source text budget.
- Hidden/deleted references, field instructions/results, unknown CFSpec and
  conditional visibility, marker-to-body ordinal stability, and body visibility.
- Tables in bodies, independent field/table termination, reference anchors in
  nested/covered cells, and frame-induced main-table splits without path drift.
- Aggregate metadata/source/output budgets, many references in one container,
  malformed AtrdExtra counts/parent chains, and explicit unsupported ink/replies.

Supported scope is text, author, verified reference-container ownership, and
bounded ordinary selection spans. Full comment layout, revision acceptance,
resolved-state inference, reply rendering, and ink remain outside this phase.
Arbitrary overlapping/cross-paragraph selections retain source reference
ownership but may have no published selection span. The original fixture does
not establish ink, replies, nonempty initials, or body-table conversion fidelity;
those applicable record/structure cases are covered by independent synthetic
tests, not claimed as LibreOffice parity.


### Validation results

Comment decoder/integration/CFB tests: **94 passed, 1 skipped** normally.
Saved and live LibreOffice CFB comparisons: **2 passed** with conversion enabled.
The combined DOC, comment-model, and passive-runtime suite: **1,077 passed,
4 skipped**. Ruff passed for both runtime files, both new test modules, and the
fixture inspection helper.

A non-timing regression prohibits membership scans on the growing paragraph
anchor list while extracting 128 comments in one paragraph. Other regressions
bound unused author strings before decoding, accumulate initials across records,
include all declared stories in the source-metadata bound, and independently
limit repeated emitted author strings. Shared note/comment paths are charged
before any path copy is published.
