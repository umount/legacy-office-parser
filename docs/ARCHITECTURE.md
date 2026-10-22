# Principles and architecture

## Purpose

The library has one job: office document → faithful data for LLMs.
It preserves text, reading order, cell and merge relationships, types and values,
titles and notes. Public interfaces are the Python API and command line.

Macros, scripts, commands, active objects and formulas are not executed.
The parser does not follow links, download files or open resources referenced
by a document. Stored formula results may be stale; the model retains the
formula flag. Exact styling and implicit pagination are not goals. Format
properties are read to the extent needed for faithful content and structure.

“External DOC properties” means records in the Data stream of the same OLE file.
It does not mean access to an external file or network resource.

## Principles

1. Minimize dependencies. `olefile` reads the container; the standard library
   handles binary structures, RTF, ZIP and XML. Do not add an entire office suite
   for a single parser.
2. Extract shared code only when duplication warrants it. Currently this means
   OLE access, limits, errors and models. A plugin system, universal format
   registry, custom dependency injection and a separate server are unnecessary.
3. Correct content comes first. Do not infer tables from words and numbers or
   scan arbitrary “text-like” bytes instead of reading structures.
4. The current file state matters more than the amount of extracted text.
   Stale or deleted PPT records must not appear in the current presentation.
5. Unsupported content produces a warning or error. An empty or simplified
   result must not be presented as guaranteed complete.
6. Keep the public contract small and typed. Do not expose internal binary
   structures. Text documents, spreadsheets and presentations share a wrapper
   with structures appropriate to each kind.
7. Apply limits before large allocations and inside parsing loops. A file-size
   limit does not bound total process memory. `max_depth` and `max_records`
   also bound the OLE directory graph before the container library traverses it
   recursively.
8. No background threads, network access or execution of embedded content.
9. Tests check expected document content and actual errors, not just mirror
   implementation branches.
10. One package contains modules for the agreed formats only. Existing
    implementations serve as technical references and sources of needed parts;
    the provenance of adaptations is recorded.

## Layers

`api.py` reads bounded input and detects the format from its contents:
OLE streams, the RTF signature or the OpenDocument ZIP package MIME type.
`doc.py`, `xls.py`, `ppt.py`, `rtf.py` and `odf.py` implement the formats.
`_ole.py` and `_odf_package.py` handle containers; specialized helpers stay
alongside their format module.
`models.py`, `errors.py` and `limits.py` define the shared contract without
infrastructure. `cli.py` is a thin adapter to the same API, printing JSON or text.

Paths and `bytes` are accepted consistently. Filename extensions do not replace
content checks. DOCX, RTF named `.doc` and other formats must not silently enter
the binary DOC parser.

## Model

DOC/RTF/ODT store ordered `Paragraph | Table` blocks. Tables contain rows and cells
with text, `row_span`, `col_span` and `covered`; coordinates covered by a merge
do not shift neighboring columns. `Cell.blocks` preserves paragraph and nested
table order, while `Cell.text` provides their flat projection. Auxiliary stories
are separate from the body. DOC, RTF and ODT retain tables from these stories in
optional `Document.story_blocks`, whose keys match the story text fields.
Projections remain in string fields, so `Document.text` does not traverse the
tree again. Empty `story_blocks` is omitted from JSON. The text budget counts all
retained strings, including nested-cell and structured-story projections.
DOC builds table levels iteratively using PItap and distinct cell/row markers;
depth and record counts are bounded.

For DOC, `Document.notes` references note block ranges and main-story paragraph
or cell paths. Source CP is not an offset into cleaned text. Bodies are not
copied; visibility flags describe the reference. Paths are calculated after
tables are fully assembled, using traversal memory proportional to depth.

PPT/ODP store `Slide(number, title, text, notes, hidden)`, including empty slides.
XLS/ODS store `Sheet` with a sparse list of `SpreadsheetCell` and separate
`CellRange` merge ranges. Coordinates are one-based. Value, type, display text
and formula are separate; formulas are not evaluated. XLS applies a limited
subset of numeric masks only to `text`, retaining the original numeric `value`.
Formats outside the supported grammar return the original number with a warning.
The package does not include a full Excel formatting engine.

`Sheet.drawings` retains ordinary ODS drawing text separately from cells,
in source sheet order. These are neither anchor coordinates nor cell values.
For sheets, `Document.text` includes cell addresses, appends drawings after the
cells of the same sheet and does not expand an empty grid.
`Document.warnings` reports detected limitations. `Document.text` is a convenient
flat representation, not a replacement for structured data.

Conditional DOC table visibility is applied before text cleaning, only after
verifying table boundaries and rectangular structure. Unsupported conditional
properties do not receive guessed results. See `research-doc-conditional-styles.md`.

`Slide.comments` contains `SlideComment(text, author, initials)` for the active
slide. `Document.text` includes comment text after notes; authorship remains
structured. Empty lists are not serialized. All strings and records count
toward shared limits; macros and external links are not executed.

`Document.comments` stores DOC comment metadata and references into
`story_blocks['comment_text']` through `CommentBodyRange`. The combined
`comment_text` projection appears once in `Document.text`. Source reference CPs
and optional selection ranges use UTF-16 units, independently of output text.
The final container path is resolved after table assembly. Metadata, paths,
source strings and retained projections remain bounded; unresolved ownership
cannot turn arbitrary comment-story bytes into active comments.

XLS empty format sections affect display text only. Hidden strings still consume
the raw-value budget, including repeated SST references, and typed values remain
in JSON. RTF WordArt uses a bounded observer for explicitly enabled standalone
shapes; it neither reopens suppressed destinations nor recovers unproven fallback
stories.

## Process boundary

The parser is synchronous. The calling process sets timeouts, forced termination
and system memory limits. The package does not create its own process pool.

DOC comment reply metadata is optional. A retained parent is identified by its
original ordinal, with a validated preorder depth; missing ancestry clears the
relationship without losing the body. Relationships never recursively render
text. Public validation uses a bounded ancestry stack, and unknown metadata does
not invent branch boundaries. Literal XLS displays preserve raw strings and
charge distinct replacement text separately under the shared output budget.
