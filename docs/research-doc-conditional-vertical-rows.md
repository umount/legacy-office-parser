# DOC row-only visibility with explicit vertical merge ownership

## Scope

This increment changes only `_doc_conditions.py`, with original synthetic tests.
It extends literal table-style conditional CFVanish to a proven subset of vertical
merges. It does not change `doc.py`, table construction, style decoding, rendering,
source positions, or diagnostic codes. It builds on the row-only proof described
in `research-doc-conditional-rows.md`; the previously deferred vertical subset
below is now admitted. All other exclusions from that note remain.

## Normative evidence

[MS-DOC 2.4.3, Overview of Tables](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/5b45f0e7-7760-4fdb-af88-0146de2feb4c)
requires physical cell marks to remain in vertical merge groups and requires
second/subsequent cells to contain no content other than those marks. It also
defines table partition boundaries and requires the row definitions to match
physical cell counts. Thus a nonempty continuation is not a safe source of
rendered text or reference visibility for this extension.

[MS-DOC 2.9.342, VerticalMergeFlag](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/1af35534-516e-4b58-986e-f2084bd6d56f)
defines clear (0), continuation (1), and restart (3). A continuation contributes
its region but not rendered contents. Restart content and formatting extend
down consecutive continuation cells. Value 2 is not an allowed enumeration value.

[MS-DOC 2.9.317, TCGRF](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/11bf5b1c-943f-421d-bbf3-39088cd1b8dd)
stores the two-bit vertical field after the horizontal merge and text-flow
fields. In the existing decoded flags, its mask is 0x60; restart is 0x60,
continuation 0x20, and reserved value 0x40. Horizontal ownership is separate.

[MS-DOC 2.4.6.6, Determining Formatting Properties](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/d8b66123-1a3d-4e06-94c5-5ab16e9b6417)
selects the innermost row containing a source character position and applies
conditional style properties using its cell's position. CNFC 1/2 are first/header
and last row; 64/128 are horizontal bands. Character/paragraph style and direct
formatting retain their later precedence.

**Derived implementation rule:** source characters in the restart belong to
its own row, not every row geometrically covered by its span. Empty continuation
cells introduce no competing text positions. The parser can therefore apply its
existing row-only condition algorithm to the origin without guessing visibility
from the bottom of the span. Equal grids and physical column indexes are a
conservative ownership restriction imposed by this implementation, not a claim
that the specification forbids unequal-grid vertical merges.

## Accepted subset and fallback

The complete existing table-partition and style-safety proof still applies.
For a partition containing vertical flags, the additional proof requires:

- Identical strictly increasing cell-edge sequences across every row, with
  matching physical cell/flag counts.
- No horizontal merge flags anywhere in the partition.
- Every restart immediately followed by a continuation at the same column.
- Every continuation immediately preceded by a restart or continuation at the
  same column, and consisting of exactly one empty cell paragraph.
- All inherited conditional keys limited to `{1, 2, 64, 128}`.

The preceding/following checks are confined to the already established partition.
They support multiple columns, longer chains, and later independent restarts.
Reserved flags, orphan continuations, standalone restarts, gaps, shifted edges,
mixed merges, nonempty/multi-paragraph continuations, and any column/corner
condition retain unconditional visibility and the existing unknown-reference
fallback. Disabled column conditions are not silently disregarded.

Header-prefix counting, band sizes/options, first/last precedence, RTL handling,
and paragraph/direct overrides reuse the existing matching machinery. No format
properties or text are copied from the origin into a continuation. The latter
has no content whose visibility requires an origin-to-continuation mapping.

## Bounds and synthetic verification

The proof scans retained cells linearly with constant extra state; it creates no
column grid, CP ownership map, or recursion. Each inspected physical cell in a
vertical partition consumes a record-budget step before text cleanup. Existing
input/row/style and output-cell budgets remain applicable. Nonvertical partitions
keep their existing row-only and rectangular behavior.

The new `tests/test_doc_conditional_vertical_rows.py` covers first/last row and
option gates, band sizes/parity, header exclusions, independent restarts, both
DOC direction flags, origin paragraphs and override precedence, invalid ownership,
all column/corner conditions, table-partition boundaries, note source positions
and hidden/unknown visibility, proof-budget rejection, and output-cell thresholds.
All inputs are authored in-memory FIB/CLX/PAPX/style/PLC data. No private files,
external converters, or renderer assumptions are used.

The previous vertical negative in `test_doc_conditional_rows.py` now uses
mismatched continuation edges, preserving a real fallback assertion. The formerly
excluded equal-grid positive has explicit new coverage.

Validation in the isolated tracked-file snapshot based on
`0a7d79539c62256fc6625166b164dc9d252fa1e4`:

- `pytest -q tests/test_doc*.py`: **1610 passed, 7 skipped**, before the final
  three focused cases were added.
- Final `pytest -q tests/test_doc_conditional_vertical_rows.py`: **39 passed**,
  including independent column chains, direct visibility override, and inherited
  column-condition fallback.
- Ruff on `_doc_conditions.py` and both affected test modules: **passed**.

Skipped optional checks are not claimed as executed. This is a normative and
synthetic ownership proof, not a LibreOffice/Word rendering comparison. No
full-project suite or build result is claimed for this isolated change.
