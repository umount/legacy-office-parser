# Original synthetic DOC section fixtures

## Clean section-before-table regression

`clean_section_before_table.docx` is an original minimal OOXML document created
by `generate_clean.py`, using the existing nested-fixture paragraph/table helpers.
It contains two body paragraphs, a section boundary, a one-row/two-cell table,
and a trailing paragraph. The second section has a different top margin so that
LibreOffice retains the explicit section boundary instead of coalescing sections.

`clean_section_before_table.doc` is its LibreOffice `MS Word 97` conversion.
The section mark is at CP 32. Expected output: the two body paragraphs remain
outside the intact table, its cells are `Left` and `Right`, the trailing paragraph
is preserved, and warnings are empty. This is the clean interoperability regression.

Regenerate from the repository root:

```sh
.venv/bin/python tests/fixtures/doc_sections/generate_clean.py --convert
```

DOCX ZIP timestamps are fixed; DOC metadata may vary with LibreOffice versions.

## Odd-export diagnostic

`sections_before_table.doc` is an original synthetic benchmark fixture generated
from ODT text and a table and converted to DOC. Master-page assignments produce
80 sections (79 U+000C section marks), including 20 body paragraphs before the
table and out-of-table section marks between individual cells. This unusual
export exposes incomplete table fragments; warnings are expected. It guards
body placement and preservation of all 60 table entries, not a clean table shape.
No private or external document content is included in either fixture.

Format authority:

- [MS-DOC 2.8.26 PlcfSed](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/68a959a6-11e0-4f3e-9a99-76ca8cc4dddc)
- [MS-DOC 2.2.2 PLC](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-doc/a649fcc5-7868-4245-be12-04eea89d916b)
