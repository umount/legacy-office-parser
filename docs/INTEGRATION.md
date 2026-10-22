# Integrating structured extraction

The [output format reference](OUTPUT_FORMAT.md) defines the fields and omission rules.
Use `Document.to_dict()` or the Python models when preparing rows and chunks for
search or language models. `Document.text` is a convenient projection, but it
does not preserve every distinction available in the structured result. Retain
source coordinates, story identity, and warnings alongside generated text.
Parsing does not calculate formulas or retrieve external resources.

## XLS: construct rows from sparse cells

An XLS adapter should consume `sheets[].cells`, group cells by `row`, and label
each value using its actual `column`. Emit rows as repeated `column: value`
fields so that each row or chunk carries its column meaning. Use the same row
serialization and header-selection policy as an existing external XLSX adapter;
only the extraction-specific mapping should differ. Do not reconstruct this
structure by splitting `Document.text` or its address/text lines.

Cell `row` and `column` are one-based. Cells are sparse: an absent coordinate does
not create a placeholder cell, and the next present cell must not shift left.
Sort present cells by `(row, column)` when ordered traversal is needed. Sheet
`rows` and `columns` describe extents, not a requirement to allocate that many
rows or columns. Never allocate a giant dense grid to fill missing coordinates.

Keep these cell fields separate:

- `text` is the extracted display string. Prefer it for display-oriented row
  text, including supported number formats and literal replacements.
- `value` and `value_type` retain typed extracted data independently of that display.
  Recognized XLS dates use an ISO-style string, not the original numeric serial;
  see [date/time semantics](OUTPUT_FORMAT.md#xls-dates-and-times). Keep
  them in structured metadata for arithmetic, filtering, or provenance.
- `is_formula` indicates a formula cell. Its value is a stored result and may be
  stale; extraction does not recalculate it. For XLS, `formula` is generally
  `None` because binary formula tokens are not translated into expressions.
- An empty `text` can deliberately hide a retained value. Do not silently replace
  it with `str(value)`. A present empty display, an absent cell, numeric zero,
  boolean false, and a missing stored value are different states.

Header detection is adapter policy, not a parser guarantee. Do not assume that
row 1 is a header. Supply a column-to-label mapping after applying the same
policy used for XLSX: it may consider a configured header row, multiple header
rows, repeated headers inside the sheet, or no header at all. Reuse labels for
every emitted data row. If a repeated source header is skipped, identify it
explicitly; do not drop a row merely because its values resemble column names.
Blank or duplicate labels need stable coordinate-qualified fallback labels.

This example accepts a mapping and header-row selection chosen by the caller.
It groups only present cells and preserves empty displays and raw cell metadata:

```python
from itertools import groupby


def spreadsheet_rows(sheet, column_labels, header_rows=()):
    skipped = set(header_rows)
    ordered = sorted(sheet["cells"], key=lambda cell: (cell["row"], cell["column"]))
    for row_number, group in groupby(ordered, key=lambda cell: cell["row"]):
        cells = list(group)
        if row_number in skipped:
            continue
        fields = []
        for cell in cells:
            column = cell["column"]
            label = column_labels.get(column) or f"Column {column}"
            fields.append(f"{label}: {cell['text']}")
        yield {
            "sheet": sheet["name"],
            "row": row_number,
            "text": "\n".join(fields),
            "cells": cells,
        }
```

For example, cells at columns 1 and 3 produce labels for columns 1 and 3; they
do not become columns 1 and 2. Repeating labels on each row keeps their meaning
when rows are chunked independently. The example is a minimal serialization
policy: consumers needing reversible text serialization should escape embedded
newlines and separators or keep a structured list of label/value pairs.

Merges are explicit in `sheets[].merges`, with one-based inclusive
`start_row`, `start_column`, `end_row`, and `end_column` bounds. Keep ranges as
metadata rather than expanding every covered coordinate. If the adapter chooses
to propagate a merged header's label, treat that as header policy and retain the
original range. Do not duplicate merged data values into absent cells or infer
merges from blank displays. Selection of hidden sheets is also adapter policy.

## Text documents: build heading paths from paragraph metadata

`Paragraph.heading_level` is an integer from 1 through 9 for an identified heading, or `None` for an ordinary body paragraph. In JSON, body
paragraphs omit `heading_level`; read an absent key as `None`. Heading text stays
in `text`, and `kind` remains `paragraph`. `heading_path` is adapter-generated
metadata, not a field emitted by the parser.

For main-story paragraphs, maintain a stack of `(level, text)` entries. For a
nonempty heading at level `L`, pop entries whose level is greater than or equal
to `L`, then push the new heading. Attach a snapshot of the resulting path to
that heading and subsequent body chunks. Ignore empty or whitespace-only
headings: they must not clear or otherwise modify the stack. Body paragraphs do
not change it.

Do not synthesize missing levels. A level 1 heading followed by level 3 produces
a path containing those two headings, with no invented level 2 entry. A later
level 2 heading replaces the level 3 entry. Keep level numbers separately when
consumers need to distinguish a skipped level from a contiguous hierarchy.

```python
def text_main_blocks(document):
    stack = []
    for block in document.get("blocks", []):
        if block["kind"] == "paragraph":
            level = block.get("heading_level")
            if level is not None and block["text"].strip():
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, block["text"]))
        yield {
            "block": block,
            "heading_path": [text for _, text in stack],
            "heading_levels": [level for level, _ in stack],
        }
```

Call this example for DOC, RTF or ODT main-story blocks. It deliberately treats a table as
one main-story block: the table receives the enclosing heading path, but headings
inside its cells do not change the context for later main-story paragraphs.
If traversing `Cell.blocks`, including nested tables, keep any heading stack
local to that cell or explicitly defined table scope. Do not flatten cell
paragraphs into the main-story stack.

Likewise, `story_blocks` content such as notes, headers/footers, textboxes, and
comment bodies needs separate context. If an adapter attaches the main path at
an anchored note/comment reference, copy that path as metadata; local headings
must not mutate the main stack. Story identity and source references should stay
available even when text is chunked together. Avoid ingesting both a structured
story and its equivalent combined string projection as separate content.

Heading metadata is supported for DOC, RTF and ODT paragraphs. This contract
does not infer headings for spreadsheet cells or presentation slides. Do not guess levels
from font size, boldness, numbering, capitalization, slide titles, or paragraph
position. Missing metadata is also not evidence of a heading. Preserve
warnings and consult [DOC heading coverage](research-doc-headings.md) and
[RTF/ODT evidence](research-rtf-odt-headings.md). RTF can infer levels from exact
built-in heading style names when outline metadata is absent; that fallback emits
a warning and cannot recover an explicit body override lost by an upstream writer.

## Resource profiles for large documents

`Limits.max_records` bounds cumulative parser work and retained structural
records, not just the number of visible paragraphs. DOC counts formatting
operations, formatting runs, paragraph metadata and pending table entries.
Exceeding the default 200,000 records is a controlled refusal; it does not by
itself indicate malformed input.

A consumer handling large documents can choose a larger, explicit profile:

```python
from legacy_office_parser import Limits, parse

large_document_limits = Limits(max_records=500_000)
document = parse(source, limits=large_document_limits)
```

This changes only the record ceiling. File, stream, text, table and nesting
limits remain in effect. Choose the profile before parsing, and run the worker
with an external memory limit and timeout. Do not retry with successively
unbounded limits or disable format validation after a failure. Process memory
and elapsed time depend on the document and runtime; a successful corpus run
is not a resource guarantee for arbitrary input.


## Numeric search and cached formulas

XLS numeric displays use the supported invariant formatting subset described in
OUTPUT_FORMAT.md. They do not infer a locale from document language. Preserve
both `text` and typed `value`; a consumer may add a canonical numeric search token
for visible numeric cells, alongside units/display text, using a matching query
normalization policy. Do not parse localized numbers by blindly deleting commas,
and do not substitute a raw value for an intentionally empty/hidden display.

Stored formula results can be stale or uncomputed. All-zero caches alone do not
identify that condition: valid formulas can return zero. Do not label values
unreliable solely from that pattern, and do not use an office application's
recalculated output as proof that the parser misread the source cache.
