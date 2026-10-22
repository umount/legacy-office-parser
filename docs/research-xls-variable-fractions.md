# Bounded variable-denominator XLS fractions

## Scope and primary evidence

This extension recognizes exactly `# ?/?` and `# ??/??`, including built-in
format IDs 12 and 13. It accepts small reduced rationals whose correctly rounded
binary64 value is identical to the stored value. This includes common repeating
fractions such as a stored `1/3`. It does **not** claim a general best-fit fraction
algorithm.

[MS-XLS 2.4.126 Format](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/300280fd-e4fe-4675-a924-4d383af48d3b)
defines the FORMAT record and fraction grammar, and delegates display
interpretation to ECMA-376. [MS-XLS 2.5.165 IFmt](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/9017e247-7995-4a9c-96e8-950df24735a2)
likewise refers to ECMA-376 for built-in identifiers. Microsoft's
[NumberingFormat documentation](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.numberingformat?view=openxml-3.0.1)
reproduces the mappings 12 = `# ?/?` and 13 = `# ??/??` under its all-languages
listing. No locale tags are stripped or interpreted by this extension.

Microsoft's [fraction guidance](https://support.microsoft.com/en-us/excel/display-numbers-as-fractions)
describes nearest-fraction display and reduction to the lowest denominator.
However, its worked example for 123.456 is `123 1/2` for single-digit fractions
and `123 26/57` for double-digit fractions. Independent preserved-XLS Calc
observations instead give `123 4/9` and `123 31/68`. The latter candidates are
closer numerically. Thus a unique globally closest rational is insufficient to
claim parity with all of the consulted Microsoft guidance. This discrepancy
motivates rejecting approximation-required values instead of importing
`Fraction.limit_denominator` or guessing a continued-fraction stopping rule.

Microsoft's [custom-format guidance](https://support.microsoft.com/en-us/excel/review-guidelines-for-customizing-a-number-format)
describes optional digit suppression, alignment spaces for `?`, aligned fraction
examples, and use of a single section for all numbers. The exact emitted space
counts, denominator alignment, integer suppression, and negative signs below
are corroborated by the preserved-XLS oracle; these are bounded observed
compatibility behavior, not a universal rendering or font-layout guarantee.

## Accepted arithmetic and output

Only finite values of magnitude at most 1,000,000 are eligible. Obtain the
absolute stored value's exact integer ratio. For each denominator from 1 to 9 or
99, compute the two neighboring integer numerators by integer arithmetic. Accept
a candidate only if integer true division produces exactly the stored binary64
value. Stop at the first denominator with a match, which gives reduced form.
There are at most 198 candidate checks, independent of the value's magnitude.

Distinct rationals with denominators at most 99 differ by at least 1/9801.
That is much greater than the binary64 spacing throughout the allowed magnitude
range (at most 2^-33). Therefore two distinct rational candidates cannot round
to the same accepted stored value. This establishes uniqueness without choosing
a midpoint policy or a tolerance. No `Fraction.limit_denominator` is used.

For example, stored `1/3` now displays as one third, and 0.2 as one fifth.
A neighboring binary64 value does not qualify merely because it is close.
The renderer preserves the source number; it does not claim to recover how a
user originally entered that number. General approximation and rounded carry
remain outside the proven subset.

For nonzero numerators, emit the nonzero whole part if present, one separator
space, a right-aligned numerator, slash, and a left-aligned denominator. The
width is one or two characters. For exact integers, emit the whole part followed
by four or six alignment spaces. Zero remains visible as `0` with that padding.
A negative nonzero value has one leading minus; signed zero displays unsigned
while its stored numeric bits are preserved.

Examples using Python string notation to expose spaces:

- `# ?/?`, 0.125 → `' 1/8'`.
- `# ?/?`, -0.5 → `'- 1/2'`.
- `# ?/?`, 1 → `'1    '`.
- `# ??/??`, 0.5 → `'  1/2 '`.
- `# ??/??`, 0.1875 → `'  3/16'`.
- `# ??/??`, -1.5 → `'-1  1/2 '`.
- `# ??/??`, negative zero → `'0      '`.

Unsupported values retain the original numeric value and `str(value)` display
with the existing coded unsupported-format warning. Examples include 123.456,
0.999, nonzero subnormals, over-bound magnitudes, and midpoint probes at the
selected denominator bound. For example, 1/18 is rejected by the single-digit
mask but is representable by the double-digit mask. Nonfinite workbook values retain the existing parser error.

Only the complete exact masks are recognized. Variable-fraction affixes,
multiple sections, colors, conditions, locale tags, other placeholder shapes,
and three-digit denominators are excluded. Fixed-denominator fractions continue
through their existing grammar and renderer unchanged. Existing numeric/date
routing automatically consumes the added built-in mappings; `xls.py` needs no
change.

## Resource and raw-value contracts

There is no runtime dependency, office process, external access, or mutable
cache. Input to the public XLS numeric path is bounded binary64 or RK integer
storage. Ratio construction therefore has a fixed finite size; candidate numerators stay
below 100 million. The denominator loop is bounded to at most 99 iterations. Core output has at most 14 characters
including a minus and alignment spaces. Operations use Decimal construction, integer arithmetic, and binary64 division
without ambient Decimal rounding or precision dependence.

Only display text changes. NUMBER and cached FORMULA numeric values retain their
bits; RK and MULRK integer values retain their integer type. Formula flags and
existing cached-formula warnings remain unchanged. Serialization preserves all
alignment spaces. The cumulative output-text budget charges those spaces and
raises on overflow rather than trimming them.

## Independent verification

`tests/test_xls_variable_fractions.py` contains 50 literal mask/value/display
triples. Its opt-in oracle uses `tests/_xls_format_oracle.py`: original synthetic
inputs are exported using harmless unique seed formats, then the exact target
FORMAT strings replace equal-length seed bytes. FORMAT/XF ownership is verified
against the original strings. LibreOffice 7.4.7.2 opens these preserved XLS bytes
and exports formatted CSV; the input XLS bytes must remain unchanged. Expected
displays are authored literals, never parser-generated values or normalized
export formats. The 50-case preserved-source oracle passed.

Ordinary tests cover both built-in and custom masks, NUMBER and FORMULA caches,
RK/MULRK integers, public dispatch, serialization, negative zero, two-digit
padding, exact reduction, finite bounds, denominator limits, midpoint neighbors,
nonfinite errors, hostile Decimal contexts, unsupported syntax, and exact output
budget boundaries. No private input or binary fixture is added.

Run:

```sh
.venv/bin/python -m pytest -q tests/test_xls_variable_fractions.py
XLS_VARIABLE_FRACTIONS_LO=1 .venv/bin/python -m pytest -q tests/test_xls_variable_fractions.py -k preserved_xls
.venv/bin/ruff check src/legacy_office_parser/_xls_formats.py tests/test_xls_variable_fractions.py
```

The live oracle is opt-in, uses isolated profiles and the existing bounded
conversion helper, and is not part of production parsing. Ordinary focused
validation: 300 passed, 1 skipped. Live oracle: 1 passed (50 literal cases).
