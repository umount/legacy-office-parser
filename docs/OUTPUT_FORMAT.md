# Output format

This document describes the Python extraction model and its JSON representation.
For chunking, heading paths, spreadsheet header selection, deduplication, and
resource profiles, see [Integrating structured extraction](INTEGRATION.md).
Those are consumer policies, not additional output fields.

## Contents

- [Versioning and output changes](#versioning-and-output-changes)
- [Python API and CLI JSON](#python-api-and-cli-json)
- [Document and format families](#document-and-format-families)
- [Paragraphs and headings](#paragraphs-and-headings)
- [Text-document tables and cells](#text-document-tables-and-cells)
- [Sheets and sparse spreadsheet cells](#sheets-and-sparse-spreadsheet-cells)
- [Slides and slide comments](#slides-and-slide-comments)
- [Auxiliary stories, notes, and DOC comments](#auxiliary-stories-notes-and-doc-comments)
- [DOC auxiliary-story identities](#doc-auxiliary-story-identities-024)
- [Plain-text projection and interpretation](#plain-text-projection-and-interpretation)
- [Text normalization and decoding](#text-normalization-and-decoding)
- [Visibility and revision state](#visibility-and-revision-state)
- [Lists, hyperlinks and embedded objects](#lists-hyperlinks-and-embedded-objects)
- [Warning stability](#warning-stability)
- [OpenDocument detection, MIME types, and templates](#opendocument-detection-mime-types-and-templates)
- [ODF visibility and tracked changes](#odf-visibility-and-tracked-changes)
- [ODF whitespace, Unicode, and control characters](#odf-whitespace-unicode-and-control-characters)
- [ODF lists, links, and embedded objects](#odf-lists-links-and-embedded-objects)
- [Inline text objects on ODP slides](#inline-text-objects-on-odp-slides)
- [XLS numeric display subsets](#xls-numeric-display-subsets)
- [XLS dates and times](#xls-dates-and-times)
- [Older binary formats and error boundaries](#older-binary-formats-and-error-boundaries)
- [Failures and exception boundaries](#failures-and-exception-boundaries)
- [Limits and refusal versus omission](#limits-and-refusal-versus-omission)
- [Execution, state, and worker isolation](#execution-state-and-worker-isolation)
- [Determinism and serialized ordering](#determinism-and-serialized-ordering)

## Versioning and output changes

This reference describes package **0.27.1**. The package version is available as
`legacy_office_parser.__version__`; it is not embedded in `Document.to_dict()`.
Store the exact package version alongside persisted results. Published version
tags identify immutable releases; a branch name is not a reproducible dependency.

For the pre-1.0 series, the compatibility policy is:

- A **minor release** (`0.x` to `0.(x+1)`) is required for intentional removal or
  renaming of public fields, changes to field types or meanings, changed omission
  rules, or changes to public API signatures. Such changes must be documented.
  New extraction features and additive structured metadata also use a minor
  release. Consumers should tolerate additional fields when reading JSON.
- A **patch release** may correct extraction, ordering, decoding, visibility,
  bounds handling or metadata to match the documented contract. It may accept a
  previously rejected input, reject an invalid input, or change extracted content
  and diagnostics for affected files. Documentation-only corrections do not
  change runtime output. Patches do not intentionally redesign the public model.
- Warning messages are human-readable diagnostics, not stable codes; their text
  or presence can change in a patch. Diagnostic codes have stable meanings; new
  codes may be added, but changing an existing meaning requires a minor release. An error classification correction can
  also change the exception for a previously mishandled input.

**Schema compatibility does not imply identical extracted content.** A patch
can change an output hash. Pin exact versions and record the release, effective
limits, input hash and consumer normalization policy in cache provenance. Decide
whether to regenerate stored content from the release's affected formats and
behavior changes; neither “patch” nor “unchanged fields” establishes that old
results remain equivalent. Changes to defaults must be recorded explicitly.

Recent output history:

- **0.27.1:** empty DOC header/note/comment stories accept bounded zero-entry
  service tables with diagnostics instead of rejecting available main content.
  Nonempty-story validation and resource limits remain enforced.
- **0.27.0:** ODP frames may select a direct inline ODF text document and
  project its supported body into the owning slide destination. DOC gains exact
  single complete depth-two comment-row ranges after enclosing-table validation.
  XLS General display behavior is unchanged; its width-free limits are clarified.
- **0.26.0:** ODF sheet/slide hidden flags resolve document-owned styles and
  family defaults, with a coded diagnostic for unresolved definitions. DOC gains
  exact ordinary main-story comment ranges across verified section boundaries
  and row-only conditional visibility for a proven vertical-merge subset. XLS
  optional-decimal numeric displays accept percent or scaling separately; raw
  caches and existing fourth-section string behavior remain unchanged.
- **0.25.0:** explicit RTF WordArt gains CP1250/CP1253 decoding; ODP frames
  select one supported text representation rather than concatenate alternatives;
  integral XLS General values below twelve digits omit the decimal suffix; DOC
  comment selection ranges can combine safe ordinary text with complete outer
  rows in one section. Explicit `normalize_text` removes U+00AD by default, with
  `drop_soft_hyphens=False` available; U+200B remains. Public model fields and raw
  numeric values are unchanged.

- **0.24.0:** DOC auxiliary-story identities, validated header inheritance,
  complete-row comment selections, row-only conditional table visibility,
  bounded variable-denominator fractions and optional-decimal displays.

- **0.23.0:** supported inherited/stored visibility filtering, optional
  display-text normalization, coded diagnostics, ODF templates and individual
  RTF/ODT note bodies. Supported fixed-denominator XLS fraction displays are added.
  See [development sequence](NEXT_STEPS.md) for validation and remaining limits.

- **0.22.0:** `heading_level` is populated for supported RTF and ODT paragraphs,
  including cells and auxiliary stories. These can gain `Cell.blocks` or
  `story_blocks` where formerly only text projections were retained. RTF exact
  built-in style-name inference and unrepresentable ODT heading levels produce
  warnings. Existing plain-text results in the checked corpus are unchanged.
- **0.21.1:** one terminal NUL after a complete RTF root is accepted with a
  warning; arbitrary trailing data is still rejected. Reserved DOC textbox
  sentinel coordinates no longer reject otherwise valid live text ranges.
  Previously rejected documents can now produce output. Defaults are unchanged.
- **0.21.0:** optional paragraph `heading_level` (1–9) for DOC, with supporting
  cell/story blocks. Body paragraphs omit the JSON key.
- **0.20.1–0.20.2:** internal refactoring; no intended output changes.

Earlier feature history and measured limits are recorded in
[the extraction register](EXTRACTION_GAPS.md) and [validation history](TESTING.md).

## Python API and CLI JSON

`parse(source)` detects the format from content. The explicit readers
`parse_doc`, `parse_xls`, `parse_ppt`, `parse_rtf`, `parse_odt`, `parse_ods`, and
`parse_odp` return the same `Document` model. Each accepts a filesystem path
(`str` or `Path`) or `bytes`, with an optional `Limits` instance. Public readers
validate the result and enforce resource limits; constructing a dataclass by
hand does not perform that validation.

Python models are dataclasses containing strings, numbers, booleans, lists,
other models, and optional values represented by `None`. `Document.to_dict()`
recursively produces dictionaries and lists, with the omissions described below.
Use it rather than `dataclasses.asdict()` when matching the CLI contract.

`legacy-office-parser input.odt --json` writes this dictionary as JSON to stdout
with Unicode preserved and non-finite numbers disallowed. `None` becomes JSON
`null`. Warnings are included in JSON and also printed to stderr. Without
`--json`, stdout contains `Document.text`. Both modes append a final newline.
Exit status is 0 on success, 2 on a handled error, or 3 when `--strict` finds
warnings. Strict mode still writes the extracted output before returning 3.

**Computed properties are not JSON fields:** neither `Document.text` nor
`SpreadsheetCell.address` is included by `to_dict()` or CLI JSON. The result
contains no computed heading path, source filename, or contract-version field.

## Document and format families

`Document.format` is one of these seven strings:

- `doc`: binary Word; main `blocks`, auxiliary stories, and supported DOC note
  and comment relationships.
- `rtf`: Rich Text Format; main `blocks` and supported pooled auxiliary stories.
- `odt`: OpenDocument Text; main `blocks` and supported pooled auxiliary stories.
- `xls`: binary Excel; `sheets` with sparse typed cells and merge ranges.
- `ods`: OpenDocument Spreadsheet; `sheets`, including supported sheet-owned
  floating text in `drawings`.
- `ppt`: binary PowerPoint; `slides`, including supported slide comments.
- `odp`: OpenDocument Presentation; `slides` with extracted title, text, and notes.

A shared model does not promise that every format populates every field.
The document fields are:

- `format: str`: detected family, as listed above.
- `blocks: list[Paragraph | Table]`: ordered main-story blocks for text documents.
- `slides: list[Slide]`: presentation slides in extraction order.
- `sheets: list[Sheet]`: workbook sheets in extraction order.
- `footnotes`, `endnotes`, `headers_footers`, `textboxes`: strings containing the
  respective pooled auxiliary text; default `""`.
- `warnings: list[str]`: extraction limitations and diagnostics; default `[]`.
- `diagnostics`: a computed list of `Diagnostic(code, message)` objects, serialized
  as dictionaries when warnings exist. See [diagnostic codes](DIAGNOSTICS.md).
- `story_blocks: dict[str, list[Paragraph | Table]]`: optional structured auxiliary
  stories. Supported keys are `footnotes`, `endnotes`, `headers_footers`,
  `textboxes`, and `comment_text`.
- `notes: list[Note]`: individual note-body metadata for DOC, RTF and ODT.
  Source CPs and structural reference anchors are currently available only for DOC.
- `comments: list[Comment]`: document comment metadata, currently from DOC.
- `comment_text: str`: combined DOC comment-body projection; default `""`.
- `auxiliary_stories: list[AuxiliaryStory]`: proven DOC header/footer and textbox
  body identities; empty lists are omitted. See the auxiliary-story contract below.

JSON always retains `blocks`, `slides`, `sheets`, `warnings`, and the four core
auxiliary strings, including when empty. It omits empty `story_blocks`, `notes`,
`comments`, and `comment_text`. Python still exposes their empty defaults.

This is a complete `to_dict()` result for a synthetic ODT model containing two
paragraphs (not a claim about warnings for any particular input package):

```json
{
  "format": "odt",
  "blocks": [
    {"text": "Overview", "heading_level": 1, "kind": "paragraph"},
    {"text": "Example body.", "kind": "paragraph"}
  ],
  "slides": [],
  "footnotes": "",
  "endnotes": "",
  "headers_footers": "",
  "textboxes": "",
  "warnings": [],
  "sheets": []
}
```

## Paragraphs and headings

A `Paragraph` has `kind: "paragraph"`, `text: str`, and
`heading_level: int | None`. A retained level is an integer from **1 through 9**,
not a boolean. `None` means no retained heading level and is omitted from JSON;
it does not prove that the source was visually an ordinary paragraph. Text and
`kind` remain unchanged when a level is present. Empty paragraphs can be retained.

Heading support currently applies to DOC, RTF, and ODT paragraphs, including
retained cell and auxiliary-story paragraphs:

- DOC uses supported paragraph outline properties and style resolution.
- RTF uses explicit outline levels and supported paragraph-style inheritance.
  Source levels 0–8 become output levels 1–9; source level 9 denotes body text.
  Separately, a compatibility fallback recognizes exact built-in `heading N`
  or `Heading N` paragraph-style names, where N is one digit from 1 through 9,
  when that style has no explicit outline level. This name-based inference
  emits a warning; it is distinct from explicit outline metadata. Localized
  names, name prefixes, arbitrary style numbers, and visual formatting are not
  this fallback.
- ODT uses `text:h` and `text:outline-level`. An absent level defaults to 1.
  Invalid values retain text without a heading level. A positive level above
  9 is valid ODF but unsupported by this output model: the text is retained,
  `heading_level` is omitted, and an unsupported-metadata warning is emitted.
  Levels are not clamped to 9. Paragraph styles and visual appearance do not
  turn `text:p` into a heading. Consumers must preserve associated warnings.

There is no heading metadata on spreadsheet cells or slides. Font size,
boldness, a slide title, or position alone is not a general heading contract.

## Text-document tables and cells

A `Table` has `kind: "table"` and `rows: list[list[Cell]]`. Rows and their cells
are ordered lists; there is no table name, column-width, or layout model.

A `Cell` has:

- `text: str`: the cell's complete plain-text projection, default `""`.
- `row_span: int`, `col_span: int`: spans, default 1.
- `covered: bool`: a covered coordinate within a merge, default `false`.
- `blocks: list[Paragraph | Table]`: optional retained ordered content, including
  nested tables or paragraphs whose heading metadata needs preservation.
- `omitted: bool`: a grid position with no source cell, default `false`.

JSON omits `blocks` when empty and `omitted` when false. It retains `text`, both
spans, and `covered` even at their defaults. DOC can mark absent positions in its
shared table grid with `omitted: true`; these are different from a present empty
cell and from a covered merge position. An omitted position has empty text, no
blocks, unit spans, and is not covered.

When `blocks` is present, it and `text` represent the same cell content at
different levels of detail. Do not concatenate them. An absent `blocks` key is
not a claim that a nonempty cell has no content. Nested structure is optional;
plain cells may use only `text`.

The following JSON fragment is one table block. It demonstrates a nested table,
a heading in its cell, and an absent outer grid position:

```json
{
  "rows": [[
    {
      "text": "Inner",
      "row_span": 1,
      "col_span": 1,
      "covered": false,
      "blocks": [{
        "rows": [[{
          "text": "Inner",
          "row_span": 1,
          "col_span": 1,
          "covered": false,
          "blocks": [{"text": "Inner", "heading_level": 2, "kind": "paragraph"}]
        }]],
        "kind": "table"
      }]
    },
    {"text": "", "row_span": 1, "col_span": 1, "covered": false, "omitted": true}
  ]],
  "kind": "table"
}
```

## Sheets and sparse spreadsheet cells

A `Sheet` has `name: str`, `cells: list[SpreadsheetCell]`,
`merges: list[CellRange]`, `hidden: bool`, `rows: int`, `columns: int`, and
`drawings: list[str]`. Defaults are empty lists, false, and zero dimensions.
Only an empty `drawings` list is omitted from sheet JSON. Supported ODS drawing
text belongs to its sheet, in source order; it is not a cell, slide, or global
textbox and carries no inferred coordinates.

`rows` and `columns` are extents, not the length of the sparse cell list. Cell
`row` and `column` are **one-based**. Missing coordinates do not allocate cells
or shift later columns. A `SpreadsheetCell` has:

- `row: int`, `column: int`: source coordinates.
- `value: str | float | int | bool | None`: typed extracted data or cached result.
  Recognized XLS dates are converted to strings as described below; this is not
  an unconditional raw-source-value field.
- `value_type: str`: format-dependent type label. XLS uses labels such as
  `number`, `string`, `boolean`, `error`, and `empty`; ODS also uses its source
  labels such as `float`, `percentage`, `currency`, `date`, and `time`.
- `text: str`: extracted display text, possibly empty even with a stored value.
- `formula: str | None`: source expression when available; XLS binary formula
  tokens are not translated into expression strings.
- `is_formula: bool`: whether the cell is a formula cell. It can be true even
  when `formula` is null or a cached result is unavailable.

All these cell fields are included in JSON, including null values and false
flags. Python's computed `address` gives an A1-style address; JSON contains the
numeric coordinates instead. Date/time representations depend on the source
and supported formatting; do not assume every `value` is a Python date object.
No formulas are executed or refreshed; cached results can be stale. A numeric
cached zero is not replaced with a recalculated string or empty value.

For XLS General, integral values with absolute value below 100,000,000,000
display without a fractional suffix: raw `1.0` has text `"1"`. Both signed zeros
display as `"0"`, retaining the sign in the raw value. Explicit `0.0` formatting
continues to display `"1.0"`. Larger/fractional General values retain their
existing raw text projection; width-dependent General rendering is not modeled.
See [General evidence](research-xls-general-integers.md).

Supported XLS numeric masks use invariant decimal `.` and grouping `,`
separators, independently of machine locale or document language. This is a
stable extraction convention, not a reconstruction of the user's Excel locale.
Explicit supported currency literals remain part of their masks. Unsupported
locale-qualified masks retain the documented raw-value fallback and warning;
there is no `display_locale` argument or language-based locale inference.

For numeric search, consumers can derive an additional locale-independent token
from a numeric `value`, retaining `text` for its units and display meaning.
Do not remove commas from arbitrary display strings: commas may be decimal
separators or literal content. Respect the application's visibility policy;
an empty/hidden display must not automatically expose its raw value.

A formula's cached zero or empty value is not evidence that it was never
calculated. The library does not emit an "uncomputed" diagnosis merely because
all formula caches on a sheet are zero/empty. Recalculation by a reference office
application is not a stored-cache oracle.

See [XLS dates and times](#xls-dates-and-times) for the date conversion contract.

A `CellRange` contains integer `start_row`, `start_column`, `end_row`, and
`end_column`: **one-based, inclusive** merge bounds. Merges are separate metadata;
consumers should not expand them into a dense grid or duplicate stored values.

This fragment is a synthetic ODS sheet with a cached formula value at C2:

```json
{
  "name": "Data",
  "cells": [{
    "row": 2, "column": 3, "value": 42, "value_type": "float",
    "text": "42", "formula": "of:=6*7", "is_formula": true
  }],
  "merges": [{"start_row": 1, "start_column": 1, "end_row": 1, "end_column": 2}],
  "hidden": false,
  "rows": 2,
  "columns": 3
}
```

## Slides and slide comments

A `Slide` contains `number: int` (one-based), `title: str`, `text: str`,
`notes: str`, `hidden: bool`, and `comments: list[SlideComment]`. Strings default
to `""`, hidden defaults to false, and comments default to `[]`. Only an empty
comments list is omitted from slide JSON. Title, body, and speaker notes are
separate strings; these do not expose paragraph heading levels or a shape tree.

A `SlideComment` has required `text: str`, plus `author: str` and `initials: str`
defaulting to `""`. All three fields are retained in JSON. Supported PPT comments belong to their slide;
they are different from DOC's document-level `Comment` objects. Missing comment
metadata is not permission to infer an author or a location.

## Auxiliary stories, notes, and DOC comments

The pooled strings remain available even when `story_blocks` retains the same
content. A structured story can contain paragraphs and tables, including nested
cell content. DOC, RTF, and ODT can retain structure when tables or headings
require it; DOC note/comment relationships also retain body blocks. A missing
structured key does not imply an empty corresponding string.

Currently **only DOC extraction populates per-note and document-comment
reference relationships**. RTF and ODT now publish individual `Note` body ranges
alongside their pooled strings. Their ordinals follow encountered note bodies
within each kind; `source_cp` and `anchor_path` are null and `reference_kind` is
unknown. Do not invent reference positions from these body ranges. Use the ranges
in `story_blocks`, rather than splitting strings on blank lines.
Likewise, pooled headers/footers and textboxes do not establish page placement,
frame anchors, or a relationship to the nearest main-story paragraph.

A `Note` contains:

- `kind: "footnote" | "endnote"` and `ordinal: int`: a positive ordinal,
  not reconstructed printed numbering. DOC source ordinals may have gaps; RTF/ODT
  ordinals identify encountered retained bodies within each note kind.
- `body: NoteBodyRange`: `story` is `footnotes` or `endnotes`; `block_start` and
  `block_end` identify a **zero-based, half-open**, nonempty range in that
  `story_blocks` list. The story must agree with `kind`. An empty retained RTF/ODT
  body has an empty paragraph block; it does not contribute pooled text. Retained
  body blocks and their text projections both consume output budgets.
- `source_cp: int | None`: source character position, not an output-text offset.
- `reference_kind: "automatic" | "custom" | "unknown"`: reference classification,
  not a retained citation-label string.
- `anchor_path: list[str | int] | None`: an optional structural output anchor.
- `visibility: list[str]`: reference visibility flags: `hidden`, `deleted`,
  `field_hidden`, `field_instruction`, or `unknown`. The model default is
  `["unknown"]`; an empty list carries no such flags and is retained in JSON.

A DOC `Comment` contains `ordinal`, `body`, `source_cp`, `anchor_path`, and
`visibility` with analogous meanings. Its `CommentBodyRange.story` is always
`comment_text`. It also has `author: str | None`, `initials: str | None`,
`selection_start: int | None`, `selection_end: int | None`,
`reply_depth: int | None`, and `parent_ordinal: int | None`.

Selections, when verified, are half-open **source UTF-16 CP ranges**, never
slices of normalized paragraph text or `Document.text`. Both selection bounds
are null when unavailable. Known reply roots have depth 0 and null parent;
known replies identify a retained parent's ordinal. Unavailable reply ancestry
omits both reply fields from JSON. When depth is known, JSON retains the depth
and parent, including a null parent for a root. Other optional note/comment
fields remain explicit nulls when unavailable.

DOC selections additionally support exact complete outer-table rows, including
fully closed nested tables. In one section, safe ordinary paragraphs can be
combined with complete outer rows; ordinary endpoints may lie inside a paragraph,
while table endpoints must coincide with proven row boundaries. One complete
inner row at depth two is also supported if it has no deeper table and its entire
enclosing outer table validates. Multiple inner rows and mixed inner/outer spans
remain unsupported, as do partial rows and fields. See
[inner-row evidence](research-doc-comment-inner-rows.md). Ordinary non-table main-story
paragraphs may cross verified section boundaries; spans combining sections and
tables remain unsupported. Manual page breaks do not establish section ownership.
Source intervals are never widened. See [row evidence](research-doc-comment-complex-selections.md)
and [mixed-selection evidence](research-doc-comment-mixed-selections.md), plus
[ordinary-section evidence](research-doc-comment-section-selections.md).

An `anchor_path` walks from the document through `blocks`, table `rows`, and
cell `blocks`, using **zero-based list indices**. For example,
`["blocks", 0, "rows", 1, 2]` identifies the third cell of the second row of the
first main-story table. A path ends at a retained paragraph or non-omitted cell.
It does not identify a character within that object. Current validation requires
an anchor to have a `source_cp`; paths do not address auxiliary stories.
Do not substitute a CP for a normalized-text offset or invent an anchor when it
is null. Normalization, omitted content, and flattened cells prevent that mapping.

This fragment is one synthetic DOC note record; it requires a containing
`story_blocks.footnotes` list with at least one body block and a paragraph or
cell at `blocks[0]`:

```json
{
  "kind": "footnote",
  "ordinal": 1,
  "body": {"story": "footnotes", "block_start": 0, "block_end": 1},
  "source_cp": 7,
  "reference_kind": "automatic",
  "anchor_path": ["blocks", 0],
  "visibility": []
}
```

## DOC auxiliary-story identities (0.24)

`Document.auxiliary_stories` contains `AuxiliaryStory` records for proven DOC
header/footer slots and live textbox ranges. The empty list is omitted from JSON.
Text stays in the existing pooled strings and `story_blocks`; metadata must not
be appended again to a text projection.

- `source`: `header`, `main_textbox` or `header_textbox`. Textbox source does not
  identify a drawing, page, or particular header slot.
- `ordinal`: one-based slot/record position in that source PLC. Reusable textbox
  records leave gaps. Ordinals are not printed numbers or shape IDs.
- `story`: `headers_footers` or `textboxes`.
- `block_start`, `block_end`: zero-based half-open range into that story's blocks.
- `source_start`, `source_end`: half-open UTF-16 CPs relative to the named source
  subdocument, not offsets into normalized text. Header guard marks are excluded.
- `kind`: `header`, `footer`, `footnote_separator`, `endnote_separator` or `textbox`.
- `variant`: `even`, `odd`, `first` for headers/footers; `separator`,
  `continuation_separator`, `continuation_notice` for separators; null for textboxes.
- `section`: one-based source section for headers/footers, otherwise null.
- `inherited_from`: source ordinal of the prior retained body used by an empty
  header/footer slot, otherwise null. The reference resolves to a nonempty source
  range of the same kind/variant; body text is not copied. A first-section absent
  variant has an empty range and no reference. An explicitly empty paragraph is a
  present body and overrides inheritance.

Header identities require validated section and header PLCs. Missing metadata
retains the pooled text with a diagnostic, without guessed identities. A present
malformed PLC raises `InvalidDocumentError`; limits are never bypassed by fallback.
Header/page-selection flags and layout are not interpreted: a stored variant is
not proof that it appears on a rendered page. The legacy pooled projection retains
its guard/separator whitespace; body ranges exclude guard-only blocks.

Retained body blocks, their pooled projections, and identity records consume the
existing budgets. Normalization preserves identities/source coordinates while
normalizing display text. Textbox CPs include the stored final paragraph mark;
reserved and reusable ranges have no bodies. Absent textbox PLCs retain their
existing unverified whole-story fallback without source identity records.

## Plain-text projection and interpretation

`Document.text` is a convenience projection, not a reversible serialization:

- DOC/RTF/ODT: nonempty main block projections, followed by nonempty footnotes,
  endnotes, headers/footers, textboxes, and comment text, joined with blank lines.
  Tables use tabs between cell projections and newlines between rows.
- XLS/ODS: sheet name, nonempty cell displays as `address + tab + text` in
  coordinate order, then nonempty sheet drawing strings, joined with newlines;
  sheets are separated by blank lines.
- PPT/ODP: nonempty title, text, notes, and slide-comment texts joined with
  newlines; slides are separated by blank lines. Comment authors are metadata,
  not part of this projection.

Structured auxiliary blocks and note/comment metadata are not appended again.
Hidden sheet/slide flags do not themselves filter the projection. Text alone
loses distinctions such as absent versus empty cells, typed values, headings,
merge ownership, note boundaries, and source references.

Metadata is optional and source-owned: keep sheet drawings with their sheet,
slide comments with their slide, and story blocks with their named story.
Do not infer missing identities, chronology, coordinates, or layout from list
proximity. Limits also count retained structure and its projections; a plain-text
length alone is not a complete output-budget calculation.

Preserve and inspect `warnings`. Successful parsing means supported extraction
completed within limits, not that every source construct was represented. An
empty warning list is not proof of complete fidelity, and warning wording is
not a machine-readable feature inventory. Unsupported constructs can be omitted;
malformed, encrypted, unsupported, or over-limit inputs can raise parser errors
instead of returning a document. Formula execution, external-link fetching,
macros, and active embedded content are not part of extraction.

## Text normalization and decoding

Use [normalize_text](NORMALIZATION.md) for an independent display-text-normalized
copy, with optional NFC and default removal of U+00AD SOFT HYPHEN. Set
`drop_soft_hyphens=False` to preserve it. U+200B ZERO WIDTH SPACE is retained;
consumer tokenization must respect its possible word-boundary meaning.
The following describes raw parsing; source values,
formulas and reference metadata remain outside the cleanup operation.

Raw parsed strings are Unicode, but **no Unicode normalization (NFC/NFD/NFKC/NFKD) is
performed**. There is no universal LF-only, control-free or NUL-free guarantee.
JSON escaping does not sanitize strings: decoding JSON restores their original
characters. The CLI is not a terminal-control sanitizer. Consumers needing NFC
or a restricted character set must apply and version their own normalization.

Normalization is format-specific:

- DOC ordinary paragraph/cell markers become structure. In the ordinary cleaner,
  VT/FF and supported line controls become LF, object/reference markers are
  omitted, and unsupported C0 controls are omitted with a warning. However,
  supported symbol properties can supply a literal control code, including NUL,
  which is retained with a warning rather than reinterpreted as structure.
  DEL/C1 and private-use characters are not universally filtered.
- RTF literal CR/LF used to format the source are ignored; `\line` and `\tab`
  generate LF and TAB, and paragraph/table controls generate structure. Escaped
  CR, NUL, VT and other control characters can survive as text. Ignoring a single
  terminal NUL **after** the root group is separate from text sanitization.
- Other format readers apply their own structural transformations; the shared
  model validator does not impose a final normalization or character filter.

There is no package-wide `.strip()` policy. Leading/trailing whitespace can carry
content; some format-specific projections trim boundaries or omit empty strings.
`Document.text` inserts separators and omits empty block projections. Retain
structured fields when whitespace or empty paragraphs matter. Applying `.strip()`
everywhere is a consumer transformation, not a required repair or a lossless step.

RTF uses the effective document/font codec, including supported legacy code pages
such as cp1251. Undecodable byte sequences become U+FFFD with a warning; unsupported
code pages fall back to Windows-1252 with a warning. Unpaired Unicode surrogate
units are replaced with a warning. These diagnostics are deduplicated, not
per-character counts. A replacement warning can also be triggered by an encoded
literal U+FFFD. Fallback does not establish correct linguistic decoding.

DOC UTF-16 pieces use replacement with a warning on invalid sequences. Compressed
DOC pieces use the format's fixed FcCompressed character mapping, not an arbitrary
system locale or cp1251 decoder. Unsupported language/encoding cases remain
limited; consult warnings. Structural corruption may instead raise a parsing
error: recovery with replacement is not guaranteed for every invalid input.

## Visibility and revision state

Extraction is **not a rendering of accepted revisions, a visible-only transcript,
or a redaction operation**. Supported hidden/deleted runs are filtered, but the
coverage is format- and construct-specific. Not every omission emits a warning.

- DOC filters supported hidden, direct revision-deleted and field-hidden runs.
  Supported hidden properties resolve through paragraph/character styles, direct
  formatting and verified table-style contexts. Row-only conditional rules also
  cover proven unequal grids and horizontal merges with empty continuations;
  a separate proven vertical subset requires equal grids, explicit same-column
  restart/continuation groups and empty continuation cells, with no horizontal
  merges. Origin text uses its own row conditions. Other vertical configurations
  and unproven column/corner contexts retain fallback.
  See [row-condition evidence](research-doc-conditional-rows.md) and
  [vertical-row evidence](research-doc-conditional-vertical-rows.md). Unproven conditional contexts
  use the documented fallback and warnings. Hidden/deleted structural paragraph
  or cell marks can retain boundaries; revision-driven paragraph merging is not
  implemented. Inserted text is not removed merely because it is an insertion.
- RTF filters supported direct and inherited paragraph/character-style `\v`
  and `\deleted` properties, including additive styles and direct/group overrides.
  Missing/cyclic definitions produce diagnostics and use proven properties.
  Table/section styles, `\webhidden` and complete revision-history semantics are
  not implemented. Structural boundaries remain even when their text is hidden.
- DOC note/comment `visibility` describes the **reference**. A hidden or deleted
  reference does not necessarily remove its separately stored body from
  `story_blocks`, pooled strings or `Document.text`.

Keep the separate visibility rules for ODF below. Hidden spreadsheet sheets and
presentation slides remain in the model and text projection with their flags.
ODF sheet/slide flags resolve automatic styles within the owning XML part,
common parent styles and same-family defaults. Embedded definitions cannot
supply host styles. Missing, duplicate or cyclic definitions retain a false
hidden flag with `odf_sheet_slide_visibility_style_unresolved`; unresolved chains
do not inherit a hidden default. See [scope evidence](research-odf-hidden-style-scopes.md).
Consumers requiring complete exclusion of all hidden/deleted material must not
assume that a successful parse or an empty warning list proves that condition.

## Lists, hyperlinks and embedded objects

There is no semantic list model or general reconstruction of generated numbering.
DOC does not synthesize labels from list definitions. RTF can retain stored visible
labels (for example ordinary `listtext`/`pntext` groups), while list definitions do
not generate text. Literal bullets/numbers already in text can survive. Do not
infer complete list hierarchy or numbering from paragraph order.

DOC and RTF fields retain supported stored result/display text and suppress field
instructions. A hyperlink URL in its instruction is not appended automatically;
a URL already present as visible text remains text. Field results are not evaluated
or refreshed, and targets are never fetched. No hyperlink relationship model is
published.

Embedded OLE documents are not recursively parsed. DOC object markers and RTF
picture/object payloads are omitted; an RTF object's skipped fallback result is
not an independently parsed document. Recognized textbox/WordArt text is a separate,
bounded extraction feature. Explicit supported RTF WordArt accepts Windows-1250,
1251, 1252, 1253 and 932 through the existing strict property grammar; malformed
properties are omitted whole. Legacy fallback-only shape ownership remains
unproven. Reading an OLE container is distinct from executing or
extracting every embedded object it contains. ODF package-local text-object behavior
is described below; no external resource is opened.

## Warning stability

`warnings` remains a list of human-readable strings. `Document.diagnostics` and
JSON `diagnostics` add stable codes at the emission sites; see the
[code catalog](DIAGNOSTICS.md). Preserve unknown future codes. Message wording may
change, codes do not represent occurrence counts or severity, and neither list
is an exhaustive inventory of omissions. Caller-added uncoded warnings receive
`unclassified_warning`. No runtime string matching determines a code.

`--strict` still checks the warning list. It cannot certify complete extraction.

## OpenDocument detection, MIME types, and templates

OpenDocument input must be a supported ZIP package. The supported MIME-to-format
mapping includes ordinary packages and their template variants:

- `application/vnd.oasis.opendocument.text` and `text-template` → `odt`.
- `application/vnd.oasis.opendocument.spreadsheet` and `spreadsheet-template` → `ods`.
- `application/vnd.oasis.opendocument.presentation` and `presentation-template` → `odp`.

Detection does not use the filename extension. The package's `mimetype` member
is authoritative when present; otherwise the manifest entry for `/` supplies the
MIME. A nonempty manifest root MIME that disagrees with `mimetype` is rejected.
The MIME must be supported and the `office:body` child must match its family.
The explicit ODF readers also require their expected family.

**Template MIME types are accepted in the post-0.22 development version.**
`text-template`, `spreadsheet-template` and `presentation-template` map to
`odt`, `ods` and `odp` respectively. Their original family is not a separate
output `format`; use `parse` or the corresponding explicit ODF reader. Ordinary
and template MIME families have the same bounded extraction and body validation.
A mismatch between `mimetype` and the manifest remains invalid, even when both
MIMEs map to the same output family. Filename extensions do not override content.
Templates are read passively; document creation rules, macros and external
resources are not executed.

The parser reads ZIP members in memory; it does not extract an archive directory.
Only stored and deflated ZIP compression is supported. Flat XML ODF input is not
an alternative accepted input to the public ZIP-based ODF readers.

## ODF visibility and tracked changes

Supported explicit hidden sections, stored hidden-paragraph field states and
inherited paragraph/text-style `text:display` properties are checked before text
and detached stories are collected. Common/default/automatic styles keep their
scopes; embedded text documents do not redefine their host's visibility styles.
The hidden-section filter applies to ODT, ODS and ODP. Explicit visible overrides
are respected. Original regression cases and boundaries are described in
[stored visibility](research-visibility.md).

Conditional expressions are not evaluated. Unknown, duplicate or cyclic styles
produce diagnostics; the parser uses available properties without claiming a
complete rendered view. Hidden sheet/slide flags remain metadata and do not
remove those sheets or slides. Hidden row/column rendering is not reconstructed.

`text:tracked-changes` deletion payloads are not traversed as ordinary content.
Ordinary inserted content remains; there is no accept/reject operation or revision
graph reconstruction. ODF annotations remain omitted. Output is not a redaction
service or proof that every character would be visible in an office renderer.

## ODF whitespace, Unicode, and control characters

In ODF paragraph/heading inline text, runs of raw XML space, tab, carriage return,
and line feed collapse to a single ordinary space, including across supported
span boundaries. Leading and trailing raw whitespace is dropped. Explicit
`text:s` expands to its positive `text:c` count (default 1), `text:tab` produces
`\t`, and `text:line-break` produces `\n`; these explicit characters, including
leading and trailing spaces, are retained subject to limits. Thus raw XML tabs
and newlines are not equivalent to their explicit ODF text elements.

This is not general Unicode whitespace normalization: nonbreaking spaces,
soft hyphens, zero-width characters, and bidi controls can survive. No shared
NFC/NFKC normalization or general control-character scrub is applied. For example,
`e` followed by U+0301 remains decomposed, and U+007F is retained in valid XML.
XML-forbidden characters such as literal U+0001 cause `InvalidDocumentError`
rather than being stripped or repaired. DTD/entity declarations are rejected;
this parser does not resolve external entities. XML decoding and line-ending
handling occur before the paragraph whitespace rules.

These paragraph rules do not promise identical normalization for all stored
attributes, spreadsheet values, or other format families. ODS date/time values
are source attribute strings, not Python date/time objects. No blanket claim of
sanitized or source-offset-preserving output should be attached to `Document.text`.
Projection separators are additional formatting: text-document blocks/stories
use blank lines, table cells use tabs, table rows use newlines, and ODF cell
paragraphs use newlines. Empty structured paragraphs can survive even when a
plain-text projection omits their empty contribution.

## ODF lists, links, and embedded objects

Supported list wrappers are flattened in source traversal order. Item paragraphs
and supported nested content are retained; there is no list/item model, list-depth
field, numbering continuation, or synthesized bullet/number prefix. Literal
bullet/number characters present in source text can remain. Nested list items
therefore do not establish an output hierarchy merely from consecutive paragraphs.

A supported `text:a` contributes its displayed inline text, subject to the inline
visibility rules. Its target URI, relationship identity, and link boundaries are
not retained as metadata or appended to the label. The URI is not dereferenced.
Supported drawing-link wrappers similarly do not create an output hyperlink model.

ODT has a narrow passive inline-object exception: a `draw:object` alternative in
a frame can contribute the direct `office:document` text body when it declares
`application/vnd.oasis.opendocument.text`, has the required single-document/body
shape, and has no `xlink:href`. Its supported text and structure are pooled into
`textboxes`/`story_blocks.textboxes`; supported embedded notes use the pooled note
stories. A warning explains the loss of object identity, anchors, and embedded
page layout. Embedded styles/masters are not imported as an independent rendering
scope. In a frame, the first supported representation wins, even when empty;
other alternatives must not be assumed to be concatenated. ODP frames likewise
select only the first supported direct text box, table or recognized inline text
document, even when empty or
hidden. Separate frames retain identical text independently. Unsupported
embedded objects remain omitted; no fallback follows a selected-content error.

This does not mean recursive extraction of arbitrary embedded files. Linked or
package-referenced objects, OLE payloads, images and their replacement/attached
text, scripts, and unsupported embedded document families are not executed or
opened as child documents. ODS does not share inline text-object support. ODP
has a narrower display projection described below, without ODT pooled stories.
Supported ODS floating labels are sheet-owned `drawings`, not embedded-object
extraction. Unsupported content encountered by traversal generally produces a
warning; warnings are not a complete inventory of unvisited package members.

## Inline text objects on ODP slides

A frame may select a recognized direct inline ODF text document instead of a
text box or table. The first supported alternative wins even when empty or hidden.
Supported body text is projected into the owning slide's current title/text/notes
destination, without also adding it to pooled textboxes. Embedded presentation
attributes cannot reroute host content. Document styles remain locally scoped.

Any object reference (including package-local or empty `xlink:href`) is excluded;
metadata, masters and scripts are not traversed. Embedded footnotes and drawings
inside paragraphs keep the existing ODP diagnosed omissions. Object layout and
identity are not represented. The projection has a stable diagnostic code.
An original schema-valid example is retained; LibreOffice 7.4 does not import its
ODP object, so no positive reader-parity claim is made. See
[ODP object evidence](research-odp-inline-text-objects.md).

## XLS numeric display subsets

`SpreadsheetCell.value` and its type retain the stored data. `text` is the
supported display; a stored formula result is not recalculated. Unsupported or
ambiguous formats keep the raw numeric display with a diagnostic.

In addition to the existing fixed-denominator subset, exact masks `# ?/?` and
`# ??/??` (built-in IDs 12/13) recognize reduced rationals with denominators up
to 9/99 that round to the identical stored binary64 value. The magnitude cap is
1,000,000; general nearest-fraction approximation is not inferred. Literal
alignment spaces, negative signs and integer padding remain in display text.
Source numeric bits and cached-formula markers remain unchanged. Other masks,
affixes and locale combinations retain fallback. See
[fraction evidence](research-xls-variable-fractions.md).

Fixed cores `0.#{1,15}` and `#,##0.#{1,15}` additionally retain a nonintegral
rounded decimal result with trailing optional zeros removed. Integral results,
zero and rounding carry keep fallback because decimal-point suppression is not
established by the primary evidence used here. One percent token or trailing
scaling commas are supported separately; the nonintegral-result rule is applied
after scaling and rounding. Combining percent and scaling, currency/locale tokens
and mixed mandatory/optional percent cores remains unsupported. Fourth-section
string-helper acceptance is unchanged. See
[optional-decimal evidence](research-xls-optional-decimals.md) and
[scaling evidence](research-xls-optional-decimal-scaling.md).

General uses a deterministic extraction projection rather than cell-width-driven
rendering. Beyond the supported whole-number suffix cleanup, values retain their
raw numeric spelling (including Python exponent spelling); this path currently
emits no unsupported-format diagnostic. It does not silently round near-integers
or cached values to fit a display width. See
[General boundaries](research-xls-general-display-boundaries.md).

## XLS dates and times

XLS interpretation depends on the cell XF/number format and the workbook date
mode, not simply on a number resembling a date. A recognized supported date/time
format converts the serial to a string and sets `value_type="date"`.
**Both `value` and `text` contain that converted string; the original numeric
serial is not retained in another output field.** There are no Python
`date`, `datetime`, or `time` objects in this representation. The same numeric
interpretation path applies to supported cached numeric formula results;
formula expressions are not evaluated.

Examples from synthetic BIFF8 workbooks:

- 1900 mode, serial 61 with built-in date format 14:
  `value == text == "1900-03-01"`, `value_type == "date"`.
- 1904 mode, serial 0 with format 14: `"1904-01-01"`.
- 1904 mode, serial 1.5 with format 14: `"1904-01-02T12:00:00"`.
- Time-only format 20, serial 1.5: `"12:00:00"`, still with type `date`;
  the day component is discarded, not represented as an elapsed duration.

The 1900 system uses a base of 1899-12-31 and adjusts serials from 60 onward for
Excel's fictitious leap day. For calendar-date output, the interval
`60 <= serial < 61` in 1900 mode is unrepresentable and stays numeric with a
warning. Time-only formats are exempt from that calendar-date rejection. The
1904 system uses 1904-01-01 without that adjustment. Missing DATEMODE defaults
to 1900 mode; values other than 0 or 1 are rejected as invalid.

Date-only results use `YYYY-MM-DD` when the interpreted time is midnight.
Otherwise results use a timezone-free ISO-style datetime string. Time-only
results use an ISO-style clock string. Formatting uses millisecond precision
with trailing fractional zeroes removed. These are normalized interpreted
values, not a reproduction of the source's exact date mask, locale, AM/PM label,
calendar display, or timezone. A date-only source mask can still produce a
full datetime if its stored serial has a time fraction.

Supported built-in date/time IDs are 14–22, 45, and 47. Format 46 (elapsed time)
and locale-dependent IDs 27–36 and 50–58 fall back with a warning. A bounded
custom-format recognizer accepts plain date/time tokens and supported separators;
not every Excel date format is recognized. Unsupported/ambiguous formats, missing
XFs, negative date serials, and out-of-range dates retain the raw numeric value,
set `value_type="number"`, and emit warnings; the fallback display is `str(value)`.
Non-finite numeric input is rejected. Ordinary supported numeric formatting
retains the number in `value` and only changes `text`, which differs from the date
conversion behavior above. ODS follows its own source-value/display rules.

## Older binary formats and error boundaries

The XLS reader supports BIFF8. An older recognized BOF, including a BIFF5 version
0x0500 in a valid OLE `Book` or `Workbook` stream, raises
`UnsupportedFormatError` (currently `only XLS BIFF8 is supported`). `Book` is an
accepted stream name, not evidence that old BIFF versions are supported.

The DOC reader explicitly rejects Word 6/95 signature 0xA5DC with
`UnsupportedFormatError` (currently `Word 6/95 DOC is not supported`). Newer DOC
FIB layouts and supported version values are validated separately; this is not
a DOC95 compatibility reader or fallback text scraper.

These are outcomes after the applicable container/stream checks succeed.
Malformed or truncated OLE containers, missing/wrong-type streams, bad signatures,
invalid layouts, or resource limits may fail earlier with a different parser
error. A `.doc` or `.xls` filename alone does not guarantee a particular exception.
Public automatic and explicit readers were checked for the recognized older
signatures. The CLI handles parser errors with status 2 and diagnostics on stderr;
it does not convert unsupported legacy versions through an external office suite.

## Failures and exception boundaries

Missing optional document parts do not, by themselves, invalidate available
content. See [optional-part policy and audit](OPTIONAL_PARTS.md). For DOC with an empty header story (`ccpHdd == 0`), an aligned header
PLC whose defined CPs are all zero is ignored with `doc_empty_header_plc_ignored`,
even if its slot count does not match the section count. No header text or source
identities are inferred. Empty footnote/endnote/comment body tables also recover
when the story and reference-entry count are zero and the body table has only
one zero boundary plus its undefined terminal CP. They emit
`doc_empty_note_plc_ignored` or `doc_empty_comment_plc_ignored`, without creating
notes or comments. Present independent metadata still receives validation.
The undefined terminal CP is ignored as usual. Source
size and record limits still apply; nonzero defined CPs and malformed PLC byte
alignment remain invalid rather than establishing a missing optional part.


The public readers return a `Document` on successful extraction. Recognized
format failures use this hierarchy, exported by `legacy_office_parser` and
defined in `legacy_office_parser.errors`:

```text
ValueError
└── ParseError
    ├── InvalidDocumentError
    ├── UnsupportedFormatError
    ├── EncryptedDocumentError
    └── LimitExceededError
```

- `InvalidDocumentError`: recognized malformed structure, invalid container or
  syntax, required data missing, or an explicit format/body mismatch. An unknown
  non-ZIP/non-RTF byte string can also produce this error when OLE detection fails;
  format detection does not classify every unrecognized input as unsupported.
- `UnsupportedFormatError`: a recognized unsupported format, variant, or package
  feature, such as an unsupported ODF MIME type or ZIP compression method.
- `EncryptedDocumentError`: detected encryption. Detection is not decryption and
  there is no password parameter.
- `LimitExceededError`: a checked resource ceiling or implementation safety
  ceiling prevented extraction. This can happen with otherwise valid input.
- `ParseError`: common base for those controlled parser failures. Because it is
  a `ValueError` subclass, catch it before a broader `ValueError` handler when
  distinguishing parse failures from invalid options.

Classify controlled failures by class, not by matching exception messages.
Messages and the first detected problem can change as validation evolves.
A document violating several rules has no promised error-priority ordering.

**Not every possible failure is a `ParseError`.** The public API does not wrap
all exceptions around the complete read, parse, validate, and serialize flow:

- Sources are `str` paths, `pathlib.Path` paths, or immutable `bytes` content.
  Other objects, including `bytearray` and open file-like objects, raise
  `TypeError`. A bytes value is content, not a bytes filesystem path. Arbitrary
  `os.PathLike` objects are not explicitly accepted unless they are also `Path`.
- Opening or reading a path can propagate `OSError` subclasses such as
  `FileNotFoundError`, `PermissionError`, and `IsADirectoryError`. An embedded
  NUL in a path can raise ordinary `ValueError`. These are source-access failures,
  not evidence of malformed document bytes.
- Invalid `Limits` construction raises ordinary `ValueError`. The documented
  `limits` argument is `Limits | None`; other types raise `TypeError` before source access. False-like values are not
  silently replaced with defaults.
- Selected container/decoder exceptions are translated internally, but there is
  no universal conversion of dependency failures or implementation defects.
  Resource exhaustion can still produce `MemoryError`; Python recursion failures
  are not universally translated. `KeyboardInterrupt` and `SystemExit` are not
  controlled parse errors.
- `Document.text`, `Document.to_dict()`, and external JSON encoding are separate
  operations. `to_dict()` iteratively serializes model trees and rejects cycles with
  `InvalidDocumentError`. It does not validate caller-modified semantics or bound
  arbitrary expanded output size. Downstream JSON encoding has its own limits.

With supported arguments, available input bytes and a functioning runtime, an
unexpected exception caused solely by document parsing is an implementation or
dependency defect to report, not an additional supported content-error category.
Do not silently classify such failures as malformed input. This distinguishes the
intended parsing-error contract from the environmental and argument failures above.

A parser exception returns no partial `Document`. Successful extraction can
still include supported fallbacks and omissions; inspect `warnings`. Neither
successful return nor an empty warning list establishes complete source fidelity.

### CLI behavior

The CLI catches `ParseError`, `OSError`, and `ValueError` inside its extraction
and output block, emits diagnostics to stderr, and returns status 2. Ordinary
argument-parser failures occur earlier through `argparse` and raise
`SystemExit(2)` when `main()` is called directly. Other exception classes are not
universally caught; the CLI is not an all-failures-to-status-2 boundary.

On successful extraction it writes plain text or JSON to stdout, then writes
warnings to stderr. With `--strict`, warnings produce status 3 **after output has
been written**; without strict mode the same result has status 0. Each printed
output has a final newline. A downstream stdout failure can happen during a
write, so exit status alone does not promise atomic publication of output.

## Limits and refusal versus omission

`Limits` is a frozen, slotted dataclass. Every field must be a positive Python
integer; booleans are rejected. `max_file_bytes` and `max_stream_bytes` must also
be strictly less than the running interpreter's `sys.maxsize`. Raising a limit
changes a ceiling, not format coverage or the requirement for valid structure.

All defaults are listed here; byte units are bytes, not decimal megabytes:

- `max_file_bytes = 67_108_864` (64 MiB): input size. Path reads request at most
  this value plus one byte so an oversized input can be rejected.
- `max_stream_bytes = 67_108_864` (64 MiB): internal stream/member size. Applies
  to OLE streams, ODF ZIP members, and relevant RTF stream/binary bounds; the RTF
  reader also checks the complete input against this ceiling.
- `max_text_chars = 10_000_000`: format-specific source, decoded/expanded text,
  retained output, and relevant metadata/projection budgets. It is not simply
  `len(Document.text)` or the size of JSON in bytes.
- `max_records = 200_000`: parser record/work and structural-metadata ceilings.
  Accounting varies by format and can include tokens, formatting work, directory
  nodes, and expanded structures. It is not a count of visible paragraphs.
- `max_depth = 32`: supported nested container, group, XML, table, and related
  traversal bounds. The exact depth unit depends on the format and operation.
- `max_cells = 100_000`: table/spreadsheet cell budgets, including expanded
  copies and relevant merge accounting. Nested cells can count independently.
- `max_slides = 10_000`: presentation slide count.
- `max_sheets = 256`: spreadsheet sheet count.
- `max_rows = 1_048_576`: spreadsheet dimensions/coordinates and applicable ODF
  row, repeat, and span bounds.
- `max_columns = 16_384`: spreadsheet dimensions/coordinates and applicable ODF
  column, repeat, and span bounds.
- `max_archive_entries = 4_096`: ODF ZIP inventory entry count.
- `max_uncompressed_bytes = 134_217_728` (128 MiB): aggregate declared
  uncompressed ODF ZIP inventory size.

ODF inventory checks apply to all ZIP entries, including members not ultimately
rendered as text. This does not mean that every member is extracted to disk or
parsed: selected members are read in memory, and their reads are bounded too.
The ZIP central directory has already been decoded when its entry count is
checked; this is not a guarantee that no allocation precedes a budget check.

Source text, expanded repeats, nested retained blocks, and their string
projections can consume different budgets. DOC source text positions use UTF-16
units in relevant checks; output string accounting uses Python string lengths.
ODF also charges XML text and attributes. A limit can therefore be reached even
when the final visible text would be short. A per-file limit is not a cap on
aggregate memory across concurrent documents.

When an enforced extraction budget is exceeded, the parser raises
`LimitExceededError`; it does not return a document cut to the requested number
of characters, rows, or cells. Partial output is not the recovery API. Limits
are not progressively relaxed by the library after a failure.

There are also fixed support/safety bounds. For example, ODF XML and relevant
style traversals cap effective depth at 256 even with a higher `max_depth`, and
eligible RTF WordArt property text is bounded by
`min(65_536, max_text_chars)`. Some fixed syntax bounds produce
`InvalidDocumentError`, such as an oversized RTF numeric parameter, rather than
`LimitExceededError`.

**Unsupported-feature omission is distinct from budget refusal.** Bounded
observers can stop retaining a candidate that will not be extracted. An
oversized RTF WordArt property that is ultimately disabled, hidden, malformed,
or otherwise ineligible can be discarded with warnings while the surrounding
text is returned. The eligible oversized counterpart raises
`LimitExceededError`. No truncated WordArt prefix is published. Similarly,
unsupported numeric display formats can fall back to a stored numeric value
with warnings, and bounded style-name recognition can stop without assigning a
heading. These behaviors must not be described as either guaranteed complete
extraction or a promise that every oversized source feature aborts the document.

The library supplies no elapsed-time limit, resident-memory limit, cancellation
parameter, or total concurrent-work budget. It reads source data and builds
in-memory structures; it is not a streaming-output interface. Caller-selected
large limits do not remove Python/dependency constraints. Choose resource
profiles before parsing and impose process-level limits where required. See
[Integrating structured extraction](INTEGRATION.md) for consumer policies.

## Execution, state, and worker isolation

Parsing is local and passive. The implementation uses Python code, standard
library facilities, and `olefile`; it does not launch an office application,
converter, shell, or document-provided program. It does not execute formulas,
macros, or embedded scripts, refresh cached fields, or fetch hyperlink targets
and other external document resources. Available cached labels/results can be
retained. ODF rejects DTD/entity declarations and reads selected ZIP members
into memory rather than extracting an archive to a filesystem directory.

The parser creates no temporary files or directories and performs no document
output writes. The API reads a caller-supplied path, if used; the CLI writes to
stdout/stderr. Normal Python imports may read code/dependency files and write
bytecode caches according to interpreter settings. That runtime behavior is
separate from parser-owned temporary or document files.

Path input is not a path-access sandbox. The caller selects the path, and normal
OS resolution and access permissions apply; the API does not restrict paths to
an approved root or reject every special-file type before opening. Slow or
blocking source reads are not covered by a parser timeout. Passing an immutable
bytes snapshot separates source acquisition from document parsing and prevents
concurrent changes to a path's contents from changing that parse's input.

Parser counters, output buffers, caches, and warnings are attached to newly
created parser/model instances. The inspected implementation has no shared
cross-document result cache or persistent parsing session. It does contain
module-level mutable dictionaries and sets used as format lookup tables and
membership constants; their read-only use is a convention, not enforced
immutability. Do not mutate internals, codec registrations, dependency settings,
or global interpreter state while parsing.

Public parsing collects warnings in the result; some private DOC helpers have
`warnings.warn` defaults when invoked independently. Private-helper behavior is
not a promise that the public API modifies Python's global warning filters.
The numeric XLS renderer uses explicit local Decimal contexts for its supported
numeric formatting rather than changing the caller's decimal precision.

Independent calls can be scheduled by an application in worker processes.
There is no built-in pool or cross-process coordination. Create/import workers
using the appropriate platform rules; pass supported sources and `Limits`, and
receive ordinary returned models or serialized data. Do not share active
internal parser instances. Process startup, pickling, worker termination,
worker crashes, and pool exceptions belong to the caller's execution layer and
are not converted into `ParseError` by the library.

Observed per-call state isolation supports concurrent independent use, but this
is not a formal thread-safety guarantee across all formats, Python builds, or
dependency versions. Returned models are mutable; sharing and mutating the same
`Document` while another thread reads or serializes it is caller-controlled.
Processes provide a clearer resource/failure boundary for untrusted workloads;
using a pool by itself does not impose a memory or time limit.

## Determinism and serialized ordering

For identical input bytes, reader selection, `Limits`, package code, Python
runtime, dependency versions, and relevant interpreter configuration, extraction
is designed to be repeatable. It does not deliberately insert current timestamps,
random identifiers, or host paths into the result. Date conversion uses stored
spreadsheet serials and epochs; extraction does not consult the current time to
refresh fields. Pin the execution environment when reproducibility matters.

This is not a promise of byte-identical output across library releases, Python
versions, codec/dependency implementations, platforms, or changed resource
profiles. Changed coverage, validation, formatting, or warning behavior can
change results. Altered codecs, monkeypatching, mutable source paths, and
caller-mutated models also invalidate an identical-input comparison.

Lists carry the model's ordering semantics: main blocks and retained stories
follow extraction order; table rows/cells retain structural positions; sheets
and slides follow their extracted order; current spreadsheet parsers sort
sparse cells by `(row, column)`. Warning strings are generally deduplicated in
encounter order. They are human-facing diagnostics, not stable ordered codes.

`to_dict()` builds ordinary insertion-ordered dictionaries through an iterative
model traversal, applies documented omissions, and appends coded diagnostics. CLI JSON uses
`json.dumps(..., ensure_ascii=False, allow_nan=False)` with default separators
and without `sort_keys=True`, followed by a newline. It includes neither computed
`Document.text` nor computed spreadsheet addresses. The current object-key order
can be observed, but consumers must address keys by name rather than depend on
positions or treat JSON as a canonical byte serialization.

For content comparisons, parse JSON and compare the relevant structured values.
If serialized hashing is needed, define a consumer-owned normalization and
encoding policy, record versions and limits, and preserve the semantic ordering
of arrays. Sorting object keys alone does not guarantee stability across changed
extraction semantics, numeric rendering, or warning text.
