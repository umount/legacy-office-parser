# DOC comment selections across table boundaries

## Primary requirements

[MS-DOC 2.2.3, Valid Selection](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/8d8fece5-bdbc-4258-8457-916540075e3f)
requires a selection spanning multiple cells at a given depth to include whole
rows at that depth. A selected field delimiter requires the entire field.
Endpoints must belong to the same document part. These requirements do not
justify extending a bookmark to nearby visible text or to projected cells.

[MS-DOC 2.4.3, Overview of Tables](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/5b45f0e7-7760-4fdb-af88-0146de2feb4c)
defines depth-one cell and row marks using U+0007, and deeper cell and row marks
using U+000D with the respective inner-cell and inner-TTP properties. Rows have
1–63 cells followed by a row mark. The row's cell definitions must match its
cell count. Nested tables belong to an enclosing cell at the preceding depth.

[MS-DOC 2.9.8, BKC](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/b59cbd01-2391-4b70-994c-b58104d3f4c0)
requires annotation bookmarks to have `fCol=0`; column indices are ignored in
that case. Column-selection heuristics are therefore not a basis for comment
selection recovery.

## Implemented proof

`whole_row_comment_selections` in `_doc_comments.py` supplements the existing
ordinary-paragraph and same-cell proof. Its inputs are unnormalized main-story
UTF-16 bytes, the source paragraph prepass, section boundaries, a PAPX-coverage
predicate, limits, and an optional aggregate record-budget callback. The returned
index answers `contains(begin, end)` without rescanning text.

The only new accepted ranges begin at the first source CP of an outer row and
end immediately after an outer TTP. Adjacent complete rows may be selected
together, even with different cell counts. Each cell must terminate explicitly;
row definitions must match the observed cells and have strictly increasing
edges. Included nested tables must have complete cells and rows and return to
the enclosing depth before its cell closes. All relevant paragraphs need known
coverage. Source delimiters are checked against the records.

No bookmark is widened. Selection metadata remains a half-open UTF-16 source
interval; it is not a claim that every selected character is visible. Hidden
source text does not shift CPs. Bodies, source reference CPs, and anchor ownership
are unchanged. No output-grid, page-layout, or merge inference is used.

Integration is inside `_Doc._comment_selection_ranges`. A local
import loads the helper lazily when the existing proof rejects a range ending
at an outer TTP. The index is built once per invocation. Existing rejection
warnings and their diagnostic code remain unchanged.

## Conservative limits

This is a sufficient proof for a subset of legal selections, not a complete
implementation of every valid-selection rule. Partial rows, ranges mixing
ordinary text and table rows, and selections consisting solely of inner rows
remain unsupported by the new path. A nested table encountered without an
explicit enclosing-depth start is not used to infer that start. Incomplete or
unknown structure invalidates the candidate table's pending rows. Section marks
inside a candidate table prevent publication. Ordinary text separates row runs.

The existing conservative field policy remains: field delimiters anywhere in
the main-story paragraph content disable the new proof. Full field ownership
validation is outside this change. Surrogate-splitting starts are rejected.
Malformed or noncontiguous prepass records cannot establish new bounds.

## Resources and verification

The helper charges `6 * paragraph_count + 1` records before traversal or index
allocation, both against its explicit limit and the caller's aggregate budget.
It checks decoded source-unit limits, nesting depth, and total observed cells.
The caller supplies only the main-story UTF-16 view. Input OLE stream byte limits
remain at stream access; they do not cap a compressed story after decoding.
The traversal is iterative. Runtime is linear in source units and paragraph
records; retained space is linear in paragraph records. Each indexed range
query takes constant expected time. Overlapping comments do not rescan rows.

`tests/test_doc_comment_complex_selections.py` uses synthetic source records and
synthetic DOC transport fixtures with literal CP expectations. Cases cover full
rows, unequal adjacent rows, complete nested rows, partial spans, missing PAPX
coverage, unknown structure, mismatched definitions, invalid geometry, fields,
sections, incomplete nesting, malformed delimiters, hidden source text,
surrogate boundaries, and resource limits. Tests also assert preserved comment
body/reference ownership and repeated queries against a single charged index.

Compressed-story regressions cover independently bounded main/comment stories
and a main story whose decoded UTF-16 is larger than its compressed OLE stream.
Decoded comments and notes use their existing aggregate character budget; actual
OLE streams and stored PLC/metadata bytes retain the stream-byte limit.
