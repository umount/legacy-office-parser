# Original DOC with unequal row boundaries

Derived solely from the project-authored `../ordinary_table.doc` by
`tools/generate_doc_offset_fixture.py`. The first row starts at 100 twips
instead of zero; all remaining explicit edges, cell marks and text are unchanged.
No personal data is included. Generation is deterministic and tested.

The expected union grid has four positions: the first row omits the first
position, and the first cell of each remaining row spans two positions.
The actual empty source cells stay distinct from omitted/covered positions.
`tests/test_doc_omitted_grid.py` asserts the full authored structure via public API.

LibreOffice 7.4.7.2 preserves all text and grid dimensions but exports the
leading absent position as an empty DOCX cell. That representational difference
is reported, not suppressed or used as an extraction expectation.
