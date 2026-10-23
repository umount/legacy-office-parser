# XLS (BIFF8)

## Supported

- Sparse typed cells, ordered sheets, merges, hidden-sheet flags and stored
  formula results; formulas are never recalculated.
- Segmented shared strings, Unicode continuation boundaries, NUMBER/RK/MULRK,
  cached FORMULA/STRING values and separate raw/display representations.
- Composable decimal, grouping, percentage, comma-scaling and scientific masks;
  mandatory/optional/alignment digits, literal and currency affixes, sign and
  conditional sections, and separate text sections. Alignment emits one space;
  width-dependent fill characters are omitted.
- Fixed-denominator fractions and nearest variable fractions with one to three
  denominator digits. Raw numeric values remain unchanged by display rounding.
- Explicit `display_locale` in `parse_xls`, `parse` and the CLI: named separators
  or `NumberLocale` for custom separators. Defaults remain invariant; literal
  punctuation is never translated and process locale is never consulted.
- Normalized calendar/clock values in both 1900 and 1904 systems, including
  date masks with literals and ordinary Gregorian locale tags. Elapsed masks
  such as `[h]:mm:ss` preserve numeric serials and do not wrap at midnight.

## Boundaries

General formatting is width-free: integral values below 100000000000 lose `.0`;
other values keep their numeric spelling. Decimal/fixed-fraction rounding uses
half-up; optional decimal masks retain their explicit decimal point even when
all optional digits disappear. These are documented extraction policies, not
pixel-identical Excel or LibreOffice rendering.

Masks are bounded to 64 characters, decimal precision to 15 places and fraction
denominators to 999. Unsupported constructs (including engineering notation,
alternative calendars, multi-section dates and implicit locale-specific built-ins)
retain raw values with diagnostics. Conditional formatting rules in worksheet
records are not applied; conditions inside number-format masks are supported.
Hidden display text never removes the typed value. Print headers/footers, charts
and macro sheets are not extracted. Older BIFF and encryption are unsupported.
See the [numeric/date contract](OUTPUT_FORMAT.md#xls-numeric-display-subsets).

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
