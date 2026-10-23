# DOC (Word 97–2003)

## Supported

- Piece-table text with original UTF-16 source positions; paragraphs, headings,
  nested tables, merges, supported styles and hidden/deleted runs.
- Separate notes, comments, textboxes and headers/footers. Structured bodies
  are retained without duplicating them in the main text.
- Header section/variant identities, inheritance, first-page and even/odd
  applicability from document/section settings. All stored variants retain
  their text; no physical page placement is inferred.
- Comment ranges through partial rows, multiple nested rows at any supported
  depth, and verified section boundaries. Source bookmark rules validate exact
  UTF-16 endpoints; output grids and normalized text never determine ranges.
  Verified fields may be selected whole; partial delimiter spans stay unresolved,
  without disabling unrelated selections.
- Conditional table visibility with row/column bands and corner precedence,
  irregular grids and proven horizontal/vertical merge ownership.

## Limits

Physical pagination, drawing ownership, ink, images and embedded OLE extraction
are outside this text-parser scope. Pre-Word-97 and encryption need separate
decoders. Missing field ownership can leave affected comment ranges unresolved;
comment bodies remain available. Unknown or inconsistent style/merge ownership
uses known unconditional properties with diagnostics rather than guessing visibility.

An absent optional story must not block main text. Zero-length header stories
accept bounded zero-CP tables; empty notes/comments accept zero-entry tables
without inventing relationships. Nonempty invalid ranges and limits still fail.
See [optional-part policy](OPTIONAL_PARTS.md).

## References

- [MS-DOC](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/): FIB, CLX, PAPX/CHPX and source stories.
- [Tables](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/5b45f0e7-7760-4fdb-af88-0146de2feb4c): nesting, cell and row markers.
- [Bookmarks](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/82702014-0081-40af-8d4e-421db135f3ff): source selection constraints.
- [Sections](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/68a959a6-11e0-4f3e-9a99-76ca8cc4dddc): section CPs and terminal sentinel.
- [Header settings](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/8465bee7-6c79-45a9-812e-58b0c5fd6cdc): section first-page and document even/odd selection.
- [Formatting precedence](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/d8b66123-1a3d-4e06-94c5-5ab16e9b6417): table conditions and style overrides.

Tests are in `tests/test_doc*.py`; authored fixtures include source/readback
inspectors. LibreOffice can lose comment ranges during export/readback, so raw
source endpoints and literal expectations take precedence. Source attribution
is recorded in [THIRD_PARTY.md](../THIRD_PARTY.md).
