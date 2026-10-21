# Nested DOC tables

Format source: [MS-DOC, 2.4.3 Overview of Tables](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/5b45f0e7-7760-4fdb-af88-0146de2feb4c).

PItap/PDtap, together with table-membership flags, specify the depth.
At the first level, U+0007 terminates a cell, while a separate U+0007 with
PFTtp terminates a row. At nested levels, U+000D with PFInnerTableCell and
PFInnerTtp serves these respective roles. A row terminator must not become
an additional empty cell.

The parser maintains a level stack without recursively invoking the builder.
Each level independently assembles rows, merges, and its grid; decreasing the
depth finalizes only the levels being exited. A cell may begin with a nested
table without a preceding paragraph at the cell's own depth. `Cell.blocks`
preserves paragraph/table order, while `Cell.text` holds the text projection.

The same builder is used for notes, headers/footers, and textboxes.
Structured stories are stored in `Document.story_blocks`, but this does not
add note identifiers, header/footer variants, or textbox positions.
Ordinary stories without tables retain their previous string-only representation.

An unfinished row is retained with a warning. An inner marker without nested
depth is rejected as contradictory structure. Limits account for depth,
records, all cells, and simultaneously retained text projections; the projection
size is checked before its parts are joined into a string.

Conditional table styles, every possible reason for separating adjacent tables,
and complete Word geometry are outside this implementation. Those features
require dedicated examples and regressions, rather than text-based heuristics.
