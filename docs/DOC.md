# DOC (Word 97–2003)

## Supported

- Piece-table text with original UTF-16 source positions; paragraphs, headings,
  nested tables, merges, supported styles and hidden/deleted runs.
- Separate notes, comments, textboxes and headers/footers. Structured bodies
  are retained without duplicating them in the main text.
- Header section/variant identities and inheritance when source records prove
  them. Textbox identities refer to live source records, not rendered shapes.
- Comment ranges: ordinary paragraphs across verified sections, complete outer
  rows, same-section text/whole-row mixtures, and one complete depth-two inner
  row without a deeper table. Endpoints are never widened.
- Conditional table visibility for proven rectangular and row-only contexts,
  including restricted horizontal/vertical merges with empty continuations.

## Limits and remaining work

Partial/multiple/deeper inner-row selections, cross-section table selections,
unproven conditional styles, drawing ownership and page-dependent header choice
remain limited. Ink, images and embedded OLE documents are not extracted.
Pre-Word-97 and encrypted files require separate decoders.

An absent optional story must not block main text. Zero-length header stories
accept bounded zero-CP tables; empty notes/comments accept zero-entry tables
without inventing relationships. Nonempty invalid ranges and limits still fail.
See [optional-part policy](OPTIONAL_PARTS.md).

## References

- [MS-DOC](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/): FIB, CLX, PAPX/CHPX and source stories.
- [Tables](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/5b45f0e7-7760-4fdb-af88-0146de2feb4c): nesting, cell and row markers.
- [Bookmarks](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/82702014-0081-40af-8d4e-421db135f3ff): source selection constraints.
- [Sections](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/68a959a6-11e0-4f3e-9a99-76ca8cc4dddc): section CPs and terminal sentinel.

Tests are in `tests/test_doc*.py`; authored fixtures include source/readback
inspectors. LibreOffice can lose comment ranges during export/readback, so raw
source endpoints and literal expectations take precedence. Source attribution
is recorded in [THIRD_PARTY.md](../THIRD_PARTY.md).
