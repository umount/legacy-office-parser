# DOC: rows with differing outer boundaries

## Problem and solution

Skipping normalization for an entire table when rows had differing outer
boundaries also lost verified internal merges. Tables with complete, strictly
increasing boundaries now use the union of exact coordinates. This is the
chosen extraction model, not Word's visual layout algorithm.

Positions before/after a source row are represented as `Cell(omitted=True)`.
They are neither empty source cells nor merge continuations. They must have
empty text/blocks, unit spans, and `covered=False`. Public validation rejects
violations of this invariant; the comparison tool marks such a result as
incomplete. Ordinary JSON does not gain a new false-valued field.

Internal intervals within one physical cell are represented by `col_span` and
covered. Vertical merges are matched against the original intervals before
positions are added; nested tables have independent grids. Even a one-twip
difference is not rounded away. The full increase in position count is checked
against the limit before allocation. Zero width and incomplete boundaries leave
the source structure intact with a warning.

## Validation and limitations

The original OLE test document changes only the first boundary of one row in
the authored source DOC. The expected result is specified manually; the
generator is reproducible. LibreOffice 7.4.7.2 preserves its text and grid
dimensions, but represents the leading omitted position as an empty cell.
The comparison reports this difference explicitly. The result is not adjusted
to match that representation.

Differences remain in the private corpus compared with the DOCX geometry
produced by LibreOffice. Complete agreement is not claimed. Preferred widths,
automatic layout, and conditional styles are not evaluated. Grouping adjacent
tables does not yet account for all positioning and table-identity properties.

## Basis

- [MS-DOC Tables](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/5b45f0e7-7760-4fdb-af88-0146de2feb4c)
- [TDefTableOperand](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/de06ec41-a0ac-4046-9096-cdfaa0091ad9)
- [OOXML gridBefore](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.gridbefore)

Source boundaries describe cell geometry; taking the exact union of coordinates
is our way of preserving relationships without a layout engine.
