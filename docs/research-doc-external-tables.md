# DOC: external table properties

## Implemented (2026-10-21)

`src/legacy_office_parser/doc.py` traverses `sprmPTableProps` (`0x646B`)
and `sprmPHugePapx` (`0x6646`) iteratively. The shared chain traversal checks
Data ranges, the PrcData size (10…0x3FA2 bytes), repeated offsets in the active
chain, `Limits.max_depth`, and the shared `max_records` budget. Data is read
through the standard bounded `read_stream`. The external array must contain
complete Prl records; a zero alignment byte is allowed only in the original
PAPX, not in PrcData.

HugePapx takes effect only as the first Prl in its array. After a reference is
processed, the remainder of the containing array is neither applied nor parsed.
Properties preceding PTableProps are retained; piece-table PRM is applied after PAPX.

`src/legacy_office_parser/_doc_table.py` implements sequential operations:

- TInsert: inserts at the beginning, middle, or end, including creating a row
  from scratch; the number of inserted cells must be positive, with at most
  63 cells, each 0…31680 twips wide, and a total width after insertion of no
  more than 31680 twips.
- TDelete: deletes an existing half-open range; at least one cell must remain.
  The deleted width is subtracted from subsequent boundaries.
- TDxaCol: assigns a width to each cell in the range; subsequent boundaries
  shift by the difference in widths. Zero width and valid empty ranges are
  not treated as errors. The total-width restriction specific to TInsert is
  not applied to TDxaCol without a basis in the specification.
- TMerge / TSplit / TVertMerge immediately change the flags of the current
  definitions. Subsequent insertions and deletions move these flags with the
  cells; new cells receive zero values for the supported flags. A subsequent
  TDefTable replaces the definitions and previous merge flags; later PRM
  operations modify the resulting state. There is no longer a queue of stale
  merge indices.
- TDxaLeft / TDxaGapHalf are taken into account when creating cells through
  TInsert: the coordinate origin is left − gap. Subsequent changes shift the
  boundaries; the absolute coordinates of a new TDefTable do not receive the
  indentation a second time.

## Primary sources and decisions

The Microsoft MS-DOC pages were checked directly, rather than relying solely
on third-party converters or corpus results:

- [2.6.2 Paragraph Properties](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/484822ee-a9d9-4af4-8423-29fda67a6a58):
  both reference types, termination of the original array, the first-HugePapx
  rule, minimum length, and termination of mixed chains.
- [2.9.210 PrcData](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/473fd992-c824-4655-8880-3186bd432f80):
  signed cbGrpprl, the upper bound of 0x3FA2, and a whole number of Prl records.
- [2.4.3 Overview of Tables](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/5b45f0e7-7760-4fdb-af88-0146de2feb4c):
  definitions through TDefTable/TInsert/TDelete, correspondence between
  definitions and actual cell marks, and fallback for readers without PTableProps.
- [2.6.3 Table Properties](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/b39a6648-501c-4361-8366-4f042f579469):
  sequential operations, new properties inherited from the style,
  TDxaLeft/GapHalf, TSplit, TIstd, and preferred widths.
- [2.9.324 TInsertOperand](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/082d49fd-8f96-4fd9-ac6e-61bd7c00b90d):
  insertion position, count, and limits.
- [2.9.123 ItcFirstLim](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/61341a2c-b8da-4e52-ba62-b2b0d5efadc4):
  a half-open range, including a valid empty range when first < cell count.
- [2.9.322 TDxaColOperand](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/fa2550bf-647e-4cfd-b468-090c6850a213):
  the width of each selected column, including the corresponding spacing.
- [2.9.321 TDefTableOperand](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/de06ec41-a0ac-4046-9096-cdfaa0091ad9):
  absolute boundary coordinates; missing TC80 records receive defaults.
- [2.9.343 VertMergeOperand](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/cf7489ac-7eee-404d-8844-8ebbd279b77d):
  the current cell index and operand format.

### Fallback policy

Following a reference is not, by itself, proof that the geometry is supported.
PTableProps is processed tentatively, retaining the prior state and the remainder
of the original array. If the resulting state contains no cell definitions,
the tentative changes are rolled back and the inline remainder is applied with
a warning. This extraction policy uses the option to **not process**
PTableProps; it does not claim that MS-DOC requires this heuristic choice.
Definitions that existed before the reference and remain afterward also count
as a supported basis. Nested fallback is attempted before outer fallback.

When definitions are present, the external result is accepted and the original
tail is ignored entirely: new TInsert operations are not mixed with a fallback
TDefTable. An invalid reference, length, operand, cycle, or exhausted limit is
an error, not a reason to conceal corruption through fallback. Reusing a
previously rejected reference in another fallback is not considered a cycle.

## Exact limitations

- This is structural extraction, not a Word layout engine. TIstd and conditional
  table styles are not evaluated; the warning is retained. New cells therefore
  receive defaults for the supported flags, rather than the full set of table
  style properties.
- F614 (TTableWidth), TCellWidth, TWidthBefore/After, TWidthIndent, and enabled
  TFAutofit produce a warning: preferred/automatic layout is not evaluated.
  The warning is deliberately retained even when explicit geometry is present:
  a reference alone does not prove that it matches the displayed widths. A
  mode that disallows all warnings may reject such documents.
- The left − gap origin does not model additional adjustments for borders,
  margins, or spacing. Relative definition coordinates are used to compare
  rows without calculating full page layout.
- Deleting a merge anchor or inserting an ordinary cell inside a merge does
  not invent a new anchor; an orphan continuation is retained as an ordinary
  cell with a warning. Content in covered cells is not discarded.
- Unknown properties still prevent a full layout guarantee. The old `0x6645`
  and TDefTable10 (`0xD606`) remain unsupported and produce a warning.
- A mismatch between the number of cell marks and definitions does not create
  invented text or cells. Zero-width and incomplete grids are not normalized;
  differing outer row boundaries retain their physical coordinates. Vertical
  merging requires matching explicit boundary intervals.
- PrcData minimum-length validation is stricter than in the old HugePapx
  implementation. Cycle and depth regressions use valid 10-byte nodes to
  exercise those conditions rather than fail early on length validation.

## Validation

`tests/test_doc_external_tables.py` independently constructs WordDocument,
1Table, and Data with FIB/CLX/PLC/PAPX; only the OLE transport is replaced.
64 tests exercise the public parse_doc_bytes entry point, normalization and
coordinates, merges, insertions/deletions/widths, origin/gap, fallback, mixed
chains, cycles, sizes/truncation, and budgets. Assertions on internal boundaries
are supplemented by end-to-end checks of Cell.col_span/row_span/covered/text.
The test does not import fixture builders from existing DOC tests.

The original OLE fixture and its generator are in `tests/fixtures/doc_external/`
and `tools/generate_doc_external_fixture.py`; `tests/test_doc_external_ole.py`
checks the public API and invalid references. The LibreOffice comparison confirms
the authored data and structure using its reader's inline fallback.

For five private documents, character/table counts and the existing set of
reference differences are unchanged. Two documents contain 71 processed
PTableProps references; this is a reference count, not a count of missing tables.
Complete equality is not claimed. Private documents and their contents are
not published.

All references discussed here address the Data stream within the current DOC;
there are no network requests or reads of resources named by the document.
