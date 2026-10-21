# RTF: table structure in auxiliary stories

Tables in headers/footers, footnotes, endnotes, and textboxes are retained
in `Document.story_blocks` under the corresponding key. If at least one
fragment of a story contains a table, all of its blocks are retained in
traversal order, including paragraphs from other fragments. Identical,
independent fragments are not deduplicated. Empty tables are retained too.

The existing `headers_footers`, `footnotes`, `endnotes`, `textboxes`, and
`Document.text` strings remain unchanged: text is not duplicated from the
structured field. The new field is not added to JSON for paragraph-only stories.

The same table parsing is used as for the main text: merges, nested blocks,
and empty positions. The cumulative text budget accounts for both retained
blocks and the string projection. Public limit validation sees all auxiliary
tables; a footnote cannot bypass the cell limit.

This preserves structure but does not add note coordinates in the main text,
header/footer variant identities, rendering order, or textbox positions.

The authored `tests/fixtures/rtf_stories/auxiliary_tables.rtf` contains tables
A/B in a header/footer and C/D in a footnote. Expectations are independent
of the implementation. The optional LibreOffice check compares cells of the
corresponding DOCX tables directly, rather than only their joined strings.
Separate tests cover nesting, merges, repeated stories, empty tables,
JSON compatibility, and the budget for retaining both representations.
