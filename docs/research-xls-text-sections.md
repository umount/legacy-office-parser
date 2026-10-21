# XLS: ordinary fourth-section text affixes

## Primary contract and scope

Microsoft's [Format Cells settings](https://learn.microsoft.com/en-us/troubleshoot/microsoft-365-apps/excel/format-cells-settings)
defines the fourth section for text, `@` as the text placeholder, quoted literal
text, and backslash escaping. Its example surrounds `@` with a quoted prefix and
suffix. [MS-XLS FORMAT](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/300280fd-e4fe-4675-a924-4d383af48d3b)
provides the BIFF format-string record contract.

The implementation accepts exactly one unquoted, unescaped `@`, with zero or
more quoted or escaped literal fragments on either side. Quoted/escaped `@` and
semicolons remain literal characters. Empty quoted fragments are allowed around
the placeholder. The existing 64-character limit and quote/escape-aware section
split remain in force. All numeric sections must validate before a string is
formatted; the format must have exactly four sections and ordinary sign routing.
Numeric cells use their numeric sections without acquiring the text affixes.

Literal-only text replacement, multiple placeholders, bare affixes, colors in the
text section, fill/alignment operators, locale/date interpretation, and malformed
syntax remain unsupported. They retain the existing raw-string behavior. Empty
fourth sections still hide strings; absent sections and plain `@` preserve them.
Negative conditional numeric values retain their prior raw-value fallback, and
conditional formats do not gain string-affix interpretation. Boolean and error
cells remain unchanged. No execution or field evaluation is involved.

## Retained values and bounded display expansion

`text_affixes` returns only the bounded prefix and suffix after validating the
whole mask. When either affix is nonempty, the XLS reader charges the full new display
length before allocating it, in addition to the retained raw-string charge.
Empty-affix identity formatting does not allocate or charge a duplicate string. LABEL and cached formula STRING already charge raw text during
decoding; each SST reference already charges its raw string on use, in addition
to the source SST charge. Affix charges are added for every occurrence, including
repeated references. No retained raw charge is removed or replaced.

The original typed value, string type, and formula-cache marker remain intact.
Only `SpreadsheetCell.text` changes. Shared models and API need no edits.
Dedicated tests cover exact text budgets and one-below rejection for LABEL,
formula caches, and repeated SST references, plus syntax, format length, and
numeric-routing controls. The independent `test_xls_text_api.py` covers public
OLE autodetection, `parse_xls`, JSON, and CLI output for LABEL and formula caches.

## Original preserved-XLS oracle

`tests/test_xls_text_sections_ole.py` contains the fixture generator and literal
expected outputs. The new `tests/fixtures/xls_text_sections/` folder retains the
authored seed XLSX, patched XLS, and independently observed CSV. Nine string
cases cover prefix, suffix, both affixes, escapes, literal semicolons and `@`,
empty quoted fragments, and Unicode. Three numeric controls verify that the
fourth section does not change positive, negative, or zero displays.

The generator exports harmless unique Unicode seed formats through LibreOffice,
then patches only equal-length FORMAT character bytes. It verifies the complete
patched Workbook stream and resolves each actual cell XF to its exact intended
FORMAT. Masks are not padded or normalized before testing. The public parser and
LibreOffice CSV conversion read the same patched XLS; the latter must leave its
input bytes unchanged. All 12 cell displays agree. A SHA-256 assertion protects
the persisted XLS; regenerated containers are validated independently because
container metadata may vary. No private corpus is involved.

```sh
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_xls_text_sections.py tests/test_xls_text_api.py
PYTHONPATH=src OFFICE_CORPUS_LIBREOFFICE=1 .venv/bin/python -m pytest -q tests/test_xls_text_sections_ole.py
```

LibreOffice is an opt-in fixture oracle only; it is never called by the parser.
