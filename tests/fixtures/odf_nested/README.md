# Original nested ODT oracle fixture

`content.xml` was authored from scratch for these tests on 2026-10-21. It contains
only benign synthetic words, two body paragraphs, and three table levels. The
outer cell has a paragraph/table/paragraph sequence; its nested table has two
cells, one containing another paragraph/table/paragraph sequence. Total cells: 4.
No private or third-party fixture was used.

`own_nested.odt` packages this XML with an uncompressed ODT mimetype and a minimal
ODF 1.2 manifest. `own_nested.docx` was generated live from that ODT using
LibreOffice 7.4.7.2 40(Build:2), Office Open XML Text export. It is saved so ordinary
unit tests do not need LibreOffice or any additional Python dependency.

Reproduction from the staging root (use a fresh disposable profile):

```sh
libreoffice -env:UserInstallation=file:///tmp/legacy-office-parser-build/tests/fixtures/odf_nested/lo-profile --headless --convert-to 'docx:Office Open XML Text' --outdir tests/fixtures/odf_nested tests/fixtures/odf_nested/own_nested.odt
.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_document_reference.py tests/test_nested_reference.py
```

The live comparison was complete and equal: one body table, three total tables,
and four total cells on both sides. The parser accepts a four-cell budget and
rejects a three-cell budget for this fixture. The disposable profile is not part
of the fixtures.
