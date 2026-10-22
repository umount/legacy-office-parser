# Output format

This document describes the Python extraction model and its JSON representation.
For chunking, heading paths, spreadsheet header selection, deduplication, and
resource profiles, see [Integrating structured extraction](INTEGRATION.md).
Those are consumer policies, not additional output fields.

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
- `story_blocks: dict[str, list[Paragraph | Table]]`: optional structured auxiliary
  stories. Supported keys are `footnotes`, `endnotes`, `headers_footers`,
  `textboxes`, and `comment_text`.
- `notes: list[Note]`: individual note-body/reference metadata, currently from DOC.
- `comments: list[Comment]`: document comment metadata, currently from DOC.
- `comment_text: str`: combined DOC comment-body projection; default `""`.

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
- `value: str | float | int | bool | None`: typed stored data or cached result.
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
No formulas are executed or refreshed; cached results can be stale.

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
relationships**. RTF and ODT expose pooled footnote/endnote stories, not
individual `Note` records with reference anchors. Do not split their strings on
blank lines to manufacture note boundaries or associate them with text positions.
Likewise, pooled headers/footers and textboxes do not establish page placement,
frame anchors, or a relationship to the nearest main-story paragraph.

A DOC `Note` contains:

- `kind: "footnote" | "endnote"` and `ordinal: int`: a positive source ordinal,
  not reconstructed printed numbering. Retained ordinals may have gaps.
- `body: NoteBodyRange`: `story` is `footnotes` or `endnotes`; `block_start` and
  `block_end` identify a **zero-based, half-open**, nonempty range in that
  `story_blocks` list. The story must agree with `kind`.
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
