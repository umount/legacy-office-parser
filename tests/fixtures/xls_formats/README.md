# Original XLS numeric-format fixture

All labels and numbers were authored for this project. No personal documents,
downloaded workbooks or parser output were used to define expectations.

`numeric_formats.ods` is the hand-authored XML source;
`numeric_formats.xls` is its LibreOffice BIFF8 export. The seven numeric cells
cover percentages (positive/negative/zero), two decimal places, digit grouping,
scientific notation and a saved numeric formula result. The formula is the
constant `1/4`, with no links or resources. Runtime parsing only reads its cache.

Expected text and raw numbers are independently specified in
`tests/test_xls_formats_ole.py`. The original baseline rendered `0.125` for
`12.50%`; preserving the raw value alone did not preserve the meaning of the
text projection. Both representations are checked separately.

Regenerate with:

```sh
.venv/bin/python tools/generate_xls_formats_fixture.py
```

The ODS XML is deterministic. XLS metadata can vary by LibreOffice version;
semantic expectations, not binary equality, are the oracle. Initial conversion:
LibreOffice 7.4.7.2. Generation uses an isolated profile and a bounded process.

The opt-in test (`OFFICE_CORPUS_LIBREOFFICE=1`) exports the authored XLS to CSV
with **Save cell contents as shown**, then checks every displayed value against
the authored expectations and the parser. This supplements XLSX comparison,
which primarily verifies raw values and types.
The [LibreOffice CSV filter documentation](https://help.libreoffice.org/latest/en-US/text/shared/guide/csv_params.html)
defines token 9 as displayed-content export and token 10 as formula export;
these are set to true and false, respectively. Only this original fixture is
passed to the display oracle. The converter is a development tool, not a
runtime dependency.
