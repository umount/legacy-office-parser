# legacy-office-parser

**Faithful text and structure from office documents for LLMs.**

A Python library for preparing DOC, XLS, PPT, RTF and OpenDocument
(ODT, ODS, ODP) files for language models. It preserves content and relationships:
reading order, table rows and cells, merged cells, values, slide titles and notes.
Results are available as text and structured JSON.

One API and one runtime dependency: `olefile` for binary OLE containers.
Extraction requires neither LibreOffice nor Java nor network access. Macros,
scripts and commands are never executed; links and external resources are not opened.

## What matters for LLMs

- Text retains its order. Empty and merged cells must not shift data into
  neighboring columns. Nested tables are available as separate blocks.
- Spreadsheet cells separate the typed value, type, display text and formula
  flag. For example, the fraction `0.125` and the text `12.50%` convey related
  but distinct information. Number-format support grows through verified cases.
- Formulas use stored results; extraction does not trigger calculations or
  external data updates. A stored result may be stale.
- Warnings report some unsupported constructs and extraction limitations;
  they are not an exhaustive inventory of omissions. Successful parsing alone
  does not establish extraction completeness.

Quality means complete and faithful data relevant to the model. Exact layout,
styling and pagination are outside the scope. During development, LibreOffice
serves as one reference reader alongside independent expected results for
documents authored for this project.

## Supported formats

Version 0.24.0 adds proven DOC header/footer and textbox identities, complete-row
comment selections, additional row-only table visibility, and bounded XLS display
formats. It preserves typed values and explicit fallbacks for unverified cases.
Full compatibility with arbitrary documents has not been established; see
[coverage and limitations](docs/TESTING.md).

- DOC 97–2003: paragraphs, nested tables and merges; separate text stories and
  inherited style visibility and heading levels; comments with authors and source references.
- XLS BIFF8: sheets, sparse typed cells, merges and stored formula results;
  percentages, decimals, digit grouping and scientific notation; explicit text
  labels before/after numbers and strings, sign-based sections, and verified
  fixed-denominator fractions. Older BIFF versions are
  unsupported.
- PPT 97–2003: current slides, titles, text, WordArt, ordinary text from active
  masters, stored static dates/footers, notes and comments.
- RTF: code pages and Unicode, paragraph heading levels, tables with ordinary rectangular
  merges, nested tables, shape text, explicitly enabled Unicode WordArt and auxiliary text stories. Ambiguous merges
  produce warnings.
- ODT: paragraphs and explicit heading levels, nested tables, notes, frames and headers/footers from selected
  master pages; ODS: sheets and cells; ODP: slides and notes. OTT/OTS/OTP
  template MIME families map to the corresponding document family.

Macros, scripts, active objects and document commands are never executed.
Formulas are not recalculated: stored values are returned with formula flags.
The package does not follow links or load external resources or templates.
Visible link text remains ordinary text. Rendering, exact styling and pagination
are outside the scope. Check `warnings`: successful parsing does not mean every
construct in the document was extracted. See [support and limitations](docs/TESTING.md).

## Extraction quality

On verified extraction cases, the parser matches the content and structure
checked against LibreOffice. In specific documented cases, it preserves tables
or repeated content lost during LibreOffice conversion. Version 0.20 passed
4,483 tests, 7,400 deterministic mutations and local LibreOffice reference checks.
This is measured coverage, not a claim of complete office-suite compatibility.
Apache OpenOffice has not been tested separately.

See [achievements and alternatives](docs/COMPARISON.md) for the evidence,
previously reviewed libraries and the limits of these comparisons.

## Installation and usage

From a local checkout:

```sh
python -m pip install .
```

```python
from legacy_office_parser import parse, parse_xls, Limits

# Detect the format from content, not the filename extension.
document = parse("example.odt", limits=Limits(max_file_bytes=32 * 1024 * 1024))
print(document.text)
structured = document.to_dict()

workbook = parse_xls("example.xls")
for sheet in workbook.sheets:
    for cell in sheet.cells:
        print(sheet.name, cell.address, cell.value_type, cell.value, cell.is_formula)
```

Nested cell content is available in `Cell.blocks`; `Cell.text` remains its full
text projection. For tables in auxiliary DOC, RTF and ODT stories,
`Document.story_blocks` contains blocks under `footnotes`, `endnotes`,
`headers_footers` and `textboxes`. The corresponding strings remain available
for the text API. Empty `story_blocks` is omitted from JSON; `Document.text`
does not duplicate structured stories. For RTF/ODT, `Document.notes` identifies individual body ranges without
inventing source anchors or printed citation labels. For DOC, it links individual
note bodies to source references. `body` identifies a block range in
`story_blocks`; `anchor_path` points to a main-story paragraph or cell.
`source_cp` is a position in the source DOC, not an index into normalized text.
`visibility` records hidden, deleted or unknown reference visibility. Empty
`notes` is omitted from JSON. Printed note numbering and frame placement are
not reconstructed.

For DOC, `Document.comments` stores authors, initials and source relationships.
Each `Comment.body` references a block range in `story_blocks['comment_text']`;
`Document.comment_text` is the combined projection, included once in
`Document.text`. `source_cp` locates the reference in source UTF-16 units;
`anchor_path` identifies its final main-story paragraph or cell. Selection bounds
are half-open source CP ranges when verified, otherwise `None`.
`reply_depth` and `parent_ordinal` expose verified reply ancestry without
recursively repeating text. Known roots have depth zero; absent or unavailable
ancestry omits both fields from JSON and is never guessed from authors or text.
Ink and page placement are not reconstructed. Empty comment lists are omitted
from JSON.

Supported literal-only fourth XLS sections can replace displayed text while
retaining the original value. Empty sections produce an empty `SpreadsheetCell.text`,
while `value`, `value_type` and `is_formula` remain available in structured data.
An empty display is omitted from `Document.text`; it does not mean the cell's
stored value is absent. General conditional hiding and arbitrary text masks are
not supported.

The package also provides `parse_doc`, `parse_ppt`, `parse_rtf`, `parse_odt`,
`parse_ods` and `parse_odp`. Each accepts a path or `bytes` and returns `Document`.
Spreadsheet cell coordinates and merge boundaries are one-based. Missing cells
are not expanded into a dense grid.

Ordinary ODS drawing text is stored in `Sheet.drawings`, in source order,
separately from cells and associated with its owning sheet. `Document.text`
appends it after the cells of that sheet; an empty field is omitted from JSON.
In DOC tables, positions in the shared grid that are absent from a source row
have `Cell.omitted=True`; this differs from an empty cell or `covered=True`
within a merge. JSON includes `omitted` only when it is `true`. The text
projection uses tabs and does not convey this distinction; use the structured
result to recover relationships accurately. `formula` contains the source
expression when the format/parser provides it; `is_formula` is also retained
for XLS, whose binary formula tokens are not translated into expressions.

```sh
legacy-office-parser example.doc --json
legacy-office-parser example.ods --json --strict
```

CLI exit codes: 0 means a result was produced; 2 means an error; 3 with `--strict`
means the result contains warnings. Structure and text limits are enforced
inside the parsers; the calling process sets the system memory limit and timeout.

The [output format reference](docs/OUTPUT_FORMAT.md) defines the Python and JSON
result, field meanings, omission rules, release compatibility, errors and limits,
text/visibility behavior and format-specific limitations.
For adapters that build labeled spreadsheet rows or heading paths, see the
[structured integration guide](docs/INTEGRATION.md). It covers sparse cells,
repeated column labels, retained values, and story-local heading context.

## Development

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check src tests tools
python -m build
```

Keep private files and reports in the Git-ignored `tmp/` directory.
Public fixtures contain only documents authored specifically for testing.
Multilingual strings quoted in fixture documentation are literal test data and
remain in their original languages.

## Documentation

- [Explicit text normalization](docs/NORMALIZATION.md)
- [Stable diagnostic codes](docs/DIAGNOSTICS.md)
- [Development sequence](docs/NEXT_STEPS.md)
- [DOC and XLS iteration](docs/DOC_XLS_NEXT.md)
- [Output format: Python and JSON contract](docs/OUTPUT_FORMAT.md)
- [Structured integration guide](docs/INTEGRATION.md)
- [Achievements and alternatives](docs/COMPARISON.md)
- [Plan and status](docs/PLAN.md)
- [Principles and architecture](docs/ARCHITECTURE.md)
- [DOC/PPT research and WordCraft comparison](docs/RESEARCH.md)
- [XLS](docs/research-xls.md), [RTF](docs/research-rtf.md), [OpenDocument](docs/research-odf.md)
- [Validation and limitations](docs/TESTING.md)
- [Remaining extraction gaps](docs/EXTRACTION_GAPS.md)
- [Performance](docs/PERFORMANCE.md)
- [Sources and provenance](THIRD_PARTY.md)
