# ODT: structured auxiliary stories

If a footnote, endnote, header/footer, or textbox story contains a table,
`Document.story_blocks` retains all of its blocks in traversal order.
The existing text fields remain unchanged, and `Document.text` does not
duplicate the structure. Paragraph-only stories do not change the old JSON.

Empty tables and paragraphs are retained within a structured story.
Nested textboxes and notes are routed to their own stories rather than mixed
with the parent's text. Repeated ODT rows/cells create independent trees of
auxiliary blocks; modifying one result does not change the adjacent copy.
The number of copied records and cells, and the amount of retained text, are bounded.

No main-text anchors, textbox chains, page-variant identities, or implicit
pagination are added. This preserves the represented structure rather than
calculating layout.

Authored synthetic ODT documents cover every story type, empty and nested
tables, repetition, limits, and compatibility. The actual authored ODT in
`tests/fixtures/odf_story_tables` tests header/footer and textbox tables.
Its provenance and the change in the source RTF footnote's role during
conversion are documented alongside the file; equivalent roles across formats
are not assumed.
