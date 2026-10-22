# DOC row-only conditional visibility on unequal and horizontally merged rows

This stage changes only `_doc_conditions.py`, with original in-memory binary
probes in `tests/test_doc_conditional_rows.py`. It extends literal conditional
CFVanish, not table rendering. No external documents or converter observations
are used as test oracles.

## Primary evidence and inference

[MS-DOC 2.4.3, Overview of Tables](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/5b45f0e7-7760-4fdb-af88-0146de2feb4c)
permits different cell counts between rows. Each row's definitions must match
its physical cells. Table partitions depend on identity, direction, positioning,
first-cell frames under the default-position rule, and certain bookmarks;
unequal cell edges are not themselves a table boundary.

[MS-DOC 2.4.6.6, Determining Formatting Properties](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/d8b66123-1a3d-4e06-94c5-5ab16e9b6417)
selects the innermost containing row. CNFC 1 and 2 select top/header and bottom
rows; 64 and 128 select horizontal bands. Header/top takes precedence over
bottom, and special rows are excluded from bands. Row-band counting excludes
top/header rows when enabled. Column and corner conditions are separate.
**Inference:** when every inherited conditional entry is row-only, row membership
suffices without mapping unequal physical cells to logical columns.

[MS-DOC 2.9.317, TCGRF](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/11bf5b1c-943f-421d-bbf3-39088cd1b8dd)
identifies horizontal origins by values 2/3 and continuations by 1. Origin
formatting extends across following continuations; continuation contents are
not rendered. The implementation accepts only explicit same-row origins followed
by continuations consisting of a single empty cell paragraph. This is a narrower
proof than the format permits: it avoids assigning visibility to suppressed
source text or references in a continuation.

[MS-DOC 2.9.342, VerticalMergeFlag](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/1af35534-516e-4b58-986e-f2084bd6d56f)
extends origin formatting down a vertical group. This stage does not prove
ownership across rows or resolve row-condition precedence on vertical spans.
Every nonzero vertical-merge field therefore retains the previous fallback.

[Table Properties, 2.6.3](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/b39a6648-501c-4361-8366-4f042f579469)
and [Fatl, 2.9.69](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/c2b2c89f-4ba1-4013-a459-b66caa1171c2)
provide header-prefix, explicit band-size, and option rules. Existing matching,
header-prefix exclusion, and literal override behavior are reused unchanged.
No absent band size is inferred.

## Implementation boundary

The existing complete-row and stable-partition proof remains mandatory. Each
row must still have strictly increasing edges, one more edge than physical cells,
and matching cell flags. Unequal edges or cell counts can now pass a separate
row-only proof. Horizontal merges pass only the restricted ownership proof above.

The old rectangular/unmerged proof continues to support all existing condition
types. The new path requires **all inherited condition keys** to belong to
`{1, 2, 64, 128}`. Even disabled column/corner entries prevent the extension;
this deliberately avoids partial conditional evaluation and guessed overrides.
Column options are masked only after proving that no such conditions exist.

Uncertain cases retain unconditional visibility and mark affected references
unknown through the existing mechanism. The existing coded fallback warning is
reused; its historical wording mentions rectangular context even though the proof
now also accepts the documented row-only subset. The stable diagnostic code is retained for consumers.

Still excluded: vertical merges, orphan horizontal continuations, standalone
horizontal restart flags, nonempty or multi-paragraph continuation cells, malformed
or incomplete rows, degenerate edges, unsupported table-style PAPX/TAPX, relative
conditional toggles, ambiguous bookmark boundaries, invalid direction/options,
and outer rows containing nested tables. Independent inner tables retain their
existing proof. Paragraph/direct formatting still overrides table formatting.

The extension is a linear pass over retained row/cell metadata. It allocates no
CP map, rendering grid, ownership graph, or recursive state. Existing row/depth
budgets precede retention, and condition operations remain charged and cached by
style, matching conditions, and base visibility. Grid expansion still has its
independent output-cell budget.

## Verification and integration

Synthetic cases cover unequal row counts/edges, omitted slots, horizontal origins
2/3, first/last ties, band sizes 1/2/3 and parity, header-prefix exclusions, option
gates, inheritance and direct overrides, direction, multiple origin paragraphs,
reference visibility, partition restarts, malformed ownership, conservative
column/corner fallback, and record/cell budget rejection.

The legacy unequal-grid regression now includes a column condition, preserving
its conservative fallback assertion. New row-only tests assert the expanded
behavior separately.
