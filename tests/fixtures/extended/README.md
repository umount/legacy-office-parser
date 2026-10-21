# Original extended-format corpus

These fixtures contain only original synthetic content. No private documents,
external corpora, or parser output were used to author expectations.

- `ordinary_table.rtf` is authored directly with RTF Unicode escapes and table
  controls. Its three-column table includes empty cells and Cyrillic text.
- `ordinary_table.odt` and `merged_table.odt` are unchanged copies of the original
  sources in `../sources/`. The second exercises horizontal and vertical merges.
- `slides_notes.odp` is exported from the unchanged original
  `sources/slides_notes.pptx`: three slides, a blank middle slide, bilingual title
  and body text, and notes belonging only to the third slide.
- `sources/typed_sparse.ods` is hand-authored ZIP/XML. `typed_sparse.ods` is an
  identical copy for testing; `typed_sparse.xls` is its LibreOffice Excel 97
  (BIFF8) export. No formula is evaluated by the tested parser.

The spreadsheet has two visible sheets, `Данные` and `Пустой`. The first has
strings at A1, B1, D1 and A2; 12.5 at B2; TRUE at D2; the date 2024-02-29 at E2;
formula `of:=[.B2]*2` with cached value 25 at F2; `Общий итог` merged across A5:B5;
-7 at D5; and FALSE at C6. Column C in rows 1–2 and entire rows 3–4 are holes.
The second sheet is blank. Coordinates in the expected model are one-based.

## Independent expectations

Document and presentation JSON expectations reuse the pre-existing hand-authored
expectations for the original sources, changing only the target format.
`typed_sparse.expected.json` was written from the cell plan above, independently
of parser results. The generator never reads or writes expected JSON.

Tests cover wrappers with paths and bytes, plus content detection from bytes.
They compare all document fields except warning wording, with these explicitly
bounded format differences:

- Empty layout paragraphs may be omitted; empty table cells and blank slides
  are always retained and compared.
- XLS formatting-only blank cells are checked for empty value/text/formula
  before exclusion. Sheet extents and merge coordinates are still compared.
- Numeric text `25.0` and `25` is equivalent only after checking it represents
  the cell's actual numeric value. Boolean values must be Python booleans.
- ODS keeps the source XML type `float`; XLS uses the model type `number`.
- ODS retains its explicitly authored 1×1 empty table; XLS's blank worksheet has
  zero used rows/columns. Neither representation permits a missing second sheet.
- ODS retains the exact OpenFormula expression. XLS exposes `is_formula=true`
  and the cached result, with `formula=null` because BIFF tokens are not decoded.

There are no xfails or skipped missing public APIs. The tests independently
inspect ODF ZIP members and the XLS Workbook BOF and numeric FORMULA cache.

## Regeneration

From the repository root, with Python 3 and LibreOffice available:

```sh
python3 tools/generate_extended_fixtures.py
python3 -m pytest -q tests/test_extended_fixture_corpus.py
```

Use `--libreoffice` to select an executable and `--timeout` to bound each
conversion. Only the checked-in original sources are read. Each conversion uses
its own temporary LibreOffice profile and process group; timeout kills only that
group. No service is started. Outputs are converted in a fresh staging directory
before copying, so a stale checked-in binary cannot pass export validation.

ODF XML and RTF authored directly by the generator are deterministic. LibreOffice
exports may include version-specific metadata, so binary hashes need not match
across regeneration. Review semantic test results instead. Updating expectations
requires reviewing source content and documented format semantics; never replace
them with a parser dump to resolve a failing test.
