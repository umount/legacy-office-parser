# Original DOC table identity fixture

`first_row_position.doc` derives only from the project's authored
`../ordinary_table.doc`. Run `tools/generate_doc_identity_fixture.py` to reproduce
it byte-for-byte. Generic PAPX rebuilding is adapted from the existing external
fixture generator, but this fixture uses only inline row properties.

The first row receives direct sprmTDxaAbs (0x940E) = 721, a horizontal offset
encoded as twips plus one. The remaining two rows retain their original row
properties. Text, cell marks, grids and other streams are preserved. No PGPInfo
references, private files or external PAPX properties are introduced.

MS-DOC 2.4.3 specifies separate tables when these adjacent row properties differ.
The literal API expectation is the original leading paragraph, one three-cell
header table, a separate two-row/three-column table, and the original trailing
paragraph. `tests/test_doc_identity_ole.py` asserts full nested model equality,
exact text including separators and empty cells, and deterministic generation.

Independent conversion: LibreOffice 7.4.7.2 (40(Build:2)), DOC to DOCX. LibreOffice retained ONE three-row table with nine cells, whereas the parser
returned TWO tables with nine cells. Ordered words and nonspace text match;
structural equality does not. See `lo-comparison.json` for the unmodified
comparison report. This reference discrepancy is recorded honestly, not hidden
or used to rewrite the hand-authored semantic expectation.
