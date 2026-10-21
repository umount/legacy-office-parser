# Original external-table DOC

`ordinary_external.doc` is derived only from this project's authored
`../ordinary_table.doc`, whose hand-authored expectations remain
`../ordinary_table.expected.json`. No personal documents were used.

The generator `tools/generate_doc_external_fixture.py` rebuilds a small CFB
container, retains the source text and moves each row's properties into `Data`.
The external groups use TInsert and TDxaCol instead of TDefTable. PAPX refers to
these groups with PTableProps. Original inline properties remain after each
pointer as a compatibility fallback; readers processing the external group
must ignore that fallback. LibreOffice 7.4.7.2 uses the fallback in this fixture,
so the oracle confirms authored content/geometry, not native external decoding.
Synthetic tests separately verify that the native reader ignores contradictory
fallback properties after a processed pointer.

The binary is deterministic. Rebuild with:

```sh
.venv/bin/python tools/generate_doc_external_fixture.py
```

The public API regression preserves the bilingual paragraphs, 3-by-3 table,
leading/interior empty cells and exact authored reading order. An opt-in
LibreOffice test (`OFFICE_CORPUS_LIBREOFFICE=1`) compares all body content and
cell structure. The file is test data, not a general-purpose CFB writer example.
