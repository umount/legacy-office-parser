# XLS (BIFF8)

## Supported

- Sparse typed cells, ordered sheets, merges, hidden-sheet flags and stored
  formula results. Both 1900 and 1904 date systems are supported within the
  documented date subset; formulas are never recalculated.
- Segmented shared strings, Unicode continuation boundaries, NUMBER/RK/MULRK,
  cached FORMULA/STRING values and their separate raw/display representations.
- A bounded numeric grammar: decimals, grouping, percentages, scientific masks,
  sign sections, literal affixes, selected conditions, text sections and fractions.
- Optional fractional digits with percent OR comma scaling when the rounded
  result is nonintegral; currency combinations remain restricted.
- Exact variable fractions for `# ?/?` and `# ??/??`: denominator at most 9/99,
  magnitude at most 1,000,000, and identical stored binary64 after conversion.

## Limits and remaining work

General formatting is a width-free extraction policy: integral values below
100000000000 lose `.0`; other values keep their numeric spelling. It is not an
Excel screen renderer and does not round caches to fit a column.

General localization, approximate fractions, negative conditional formats,
integral optional-decimal results and wider alignment/text-section masks remain
limited. Unsupported custom formats keep raw values with diagnostics. Hidden
display text never removes the typed value. Print headers/footers, charts and
macro sheets are not extracted. Older BIFF and encryption are unsupported.
See [numeric/date contract](OUTPUT_FORMAT.md#xls-numeric-display-subsets).

## References

- [MS-XLS](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/).
- [FORMAT](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/300280fd-e4fe-4675-a924-4d383af48d3b): number-format grammar, referring to ECMA-376 §18.8.31.
- [FormulaValue](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/39a0757a-c7bb-4e85-b144-3e7837b059d7): cached value tags; STRING is required only for its string-result tag.
- [Unicode strings](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/173d9f51-e5d3-43da-8de2-be7f22e119b9): rich/phonetic lengths and encoding.
- [General display](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.numberingformat): width-dependent behavior is outside this parser.

Tests are in `tests/test_xls*.py`. `_xls_format_oracle.py` preserves original
FORMAT/XF records during optional LibreOffice comparisons; expected strings are
literal. xlrd 2.0.2 informed string/record interpretation, not a bundled parser;
see [provenance](../THIRD_PARTY.md).
