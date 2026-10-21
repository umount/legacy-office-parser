# Bounded XLS numeric display formats

Research and implementation: 2026-10-21. Baseline: main, version 0.6.0,
commit d891de7. No dependencies added.

## Primary references consulted before implementation

- [MS-XLS 2.4.126 Format](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/300280fd-e4fe-4675-a924-4d383af48d3b)
  defines FORMAT strings, their grammar, and locale considerations. Its grammar
  separates literals, conditions, sections, numeric and date/time tokens.
- [MS-XLS 2.5.165 IFmt](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/9017e247-7995-4a9c-96e8-950df24735a2)
  describes identifiers and points to ECMA-376 for built-in formats.
- [Microsoft NumberingFormat documentation](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.numberingformat?view=openxml-3.0.1)
  reproduces the standard's built-in identifier mapping. Numeric IDs selected
  here are 0, 1, 2, 3, 4, 9, 10, 11.
- [Microsoft's custom-format guidelines](https://support.microsoft.com/en-us/excel/review-guidelines-for-customizing-a-number-format)
  explain percent scaling, digit placeholders, scientific notation, grouping
  versus scaling commas, and quoted/escaped literals.

Original implementation using Python's standard library; no implementation
copied or vendored. Format support is deliberately narrower than Excel's grammar.

## Contract

For numeric records and numeric FORMULA caches, only `text` changes. `value`
retains the exact decoded Python int/float, including negative zero; `value_type`
remains `number`. Display rounding never changes raw data. NUMBER, RK, MULRK and
numeric FORMULA caches use the same path. Formula flags and the existing stale
cache warning remain intact. No formula tokens are evaluated, no links followed,
and no external resource is accessed at runtime.

The existing simple calendar/time path remains separate: recognized dates still
use the prior ISO text and `date` value type. This feature does not redefine the
existing date-value contract or attempt to render Excel's date masks literally.

## Accepted subset

- `General` (case insensitive), whether built-in or an explicit FORMAT record:
  preserve `str(value)` without a format warning. No column-width emulation.
- Fixed: `0` or `#,##0`, optionally followed by a decimal point and 1–15 mandatory
  zero placeholders, optionally followed by one percent sign.
- Scientific: `0`, optionally a decimal point and 1–15 mandatory zeros, then
  `E+`, `E-`, `e+`, or `e-`, then 1–3 exponent zero placeholders. Exactly one
  integer mantissa digit; no engineering notation or scientific percentages.

Examples: raw 0.125 with `0.00%` becomes `12.50%`; raw 12345.5 with `#,##0.00`
becomes `12,345.50`; raw 12345 with `0.00E+00` becomes `1.23E+04`. Percent text
includes both the factor of 100 and its percent marker. E- suppresses only the
positive exponent sign; exponents grow beyond their minimum padding as needed.

Decimal rendering uses `Decimal(str(value))` and explicit ROUND_HALF_UP, with a
private precision-340 context. This deterministic policy operates on the shortest
round-trip decimal representation, rather than claiming byte-for-byte parity
with Excel's binary rounding at every boundary. It avoids float overflow during
percent scaling, handles binary64 extremes and subnormals, and ignores callers'
ambient Decimal context. Rounded display zero is unsigned; raw signed zero is
unchanged. Fixed output may round small nonzero values to zero, as requested by
the format; consumers requiring full precision must use `value`.

## Explicit fallback and bounds

Unsupported styles return `str(value)` and one deduplicated document warning:
`Unsupported or ambiguous date/number format: raw numeric value retained.`
Missing XF uses its existing separate warning. Unsupported styles include quoted
or escaped text (including literal percent signs), multiple sections, conditions,
colors, locales, currencies, text/fractions, fill/spacing, optional fractional
placeholders, leading-zero masks, scale commas, repeated percentages and unknown
or missing format IDs. These valid Excel features are intentionally not parsed.

The entire original string must match; no stripping whitespace, quotes, escapes,
or locale tags to turn unsupported syntax into a supported numeric mask. Custom
formats are checked before date heuristics: only bounded date/time tokens
and separators enter the legacy date path. Separator characters (space, slash,
colon, period, comma, hyphen) may also be quoted or individually escaped, so the
existing `yyyy\-mm\-dd` fixture remains a date. Other literal content, mixed
numeric/date masks and elapsed formats fall back. Simple date/time
recognition retains existing ISO semantics and is not a complete date grammar.

Recognition stops at 64 characters, decimals at 15, and exponent padding at 3.
Numeric regexes have bounded quantifiers; date tokens are scanned linearly (no
nested ambiguous repetition). No workbook-sized format cache is introduced.
Finite BIFF numeric output stays below 450 characters even for grouped maximum
binary64 percentages with 15 decimal places. The normal cumulative text budget
charges every emitted character, including rendered formula caches. Existing
record/stream/string limits still apply before formatting. Nonfinite values are
rejected by the existing parser before rendering.

## Validation

`tests/test_xls_formats.py` builds its own BIFF streams without importing existing
test helpers or adding fixtures. It covers built-ins and custom equivalents,
General, positive/negative/zero, rounding and exponent carry, signed zero, literal
percent traps, unsupported masks and IDs, date separation, cached formula results,
RK/MULRK integer preservation, finite extremes, nonfinite rejection, ambient
Decimal context independence, and exact rendered text budgets.

Commands (from repository root):

```sh
.venv/bin/python -m pytest tests/test_xls_formats.py tests/test_xls.py -q
.venv/bin/python -m ruff check src/legacy_office_parser/xls.py src/legacy_office_parser/_xls_formats.py tests/test_xls_formats.py
```

The original `tests/fixtures/xls_formats/numeric_formats.xls` was also checked: B1:B7 matched `12.50%`, `-25.00%`, `12.50`, `12,345.50`,
`1.23E+04`, `25.00%`, `0.00%`, with numeric types and only B6 marked as a formula.
The sole warning was the expected formula-cache warning. The real-file and CLI integration tests independently compare those displays
with LibreOffice CSV; their generator and fixture documentation record provenance.

Full test run: `.venv/bin/python -m pytest -q` — **1305 passed,
19 skipped**. Ruff checks for the three owned Python files passed. The extended
fixture date regression discovered during validation was resolved with safe
quoted/escaped separator tokens; existing tests and expected fixtures were not
modified.
