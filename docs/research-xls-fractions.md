# Bounded fixed-denominator XLS fractions

Research date: 2026-10-22. This is an original implementation of a deliberately
small number-format subset, not a claim to implement Excel's entire fraction
formatter. No runtime dependency, conversion process, or network access is added.

## Primary references and independent evidence

- [MS-XLS §2.4.126 Format](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/300280fd-e4fe-4675-a924-4d383af48d3b)
  defines the BIFF FORMAT record and separates fraction, numeric, literal,
  conditional, and date/time grammar. Its display interpretation points to
  ECMA-376. The library's 64-character recognition bound is deliberately narrower
  than the format's source-string allowance.
- [Microsoft: Display numbers as fractions](https://support.microsoft.com/en-us/excel/display-numbers-as-fractions)
  describes nearest-fraction display and explicit fixed denominators. Fixed
  denominators do not reduce to lowest terms. This supports preserving a display
  such as `4/8` for a stored value of 0.5, rather than silently changing it to 1/2.
- [MS-OE376 §2.1.740, numFmts](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oe376/9e991056-0e17-4a61-91be-1592c8b16a30)
  documents the fraction role of the slash in Office number formatting. A slash
  in quoted or escaped text remains a literal; it must not be stripped out and
  reinterpreted as an operator.
- [LibreOffice: Number Format Codes](https://help.libreoffice.org/latest/en-US/text/shared/01/05020301.html)
  distinguishes mandatory zero placeholders from optional/alignment placeholders,
  explains mixed versus improper fractions, and describes forcing a denominator.
  It is corroborating implementation documentation, not a normative Excel oracle.

Actual independent reference runs used LibreOffice **7.4.7.2, 40(Build:2)** on
Linux. The initial 90-case and 154-case exploratory probes included masks outside
the eventual subset, midpoint values, padding, carry, negative values, and large
magnitudes. They informed rejection boundaries; they are not assertions that
unsupported masks should now render. The final reproducible oracle covers 44
supported mask/value/display triples in `tests/test_xls_fractions.py`.

The tests reuse an existing original synthetic XLSX package skeleton, replace its
cell values and masks with newly authored cases, and export harmless unique seed
formats to XLS. They then replace only same-length BIFF FORMAT string bytes with
the exact target masks. FORMAT/XF ownership is checked before comparing parser
output. LibreOffice independently opens those preserved XLS bytes and exports CSV
with formatted text enabled. Expected strings are authored literals, never
computed by the parser. Reimporting a source XLSX or trusting export-normalized
masks alone is insufficient evidence, so the exact BIFF strings are verified.

The oracle creates files in a test temporary directory, uses an isolated office
profile, applies the existing converter resource bounds, and imposes a 45-second
process-group timeout per conversion. None of this is part of production parsing.
No private documents or third-party workbook corpus is used. No binary fixture is
added; the opt-in test can regenerate the reference from original synthetic inputs.

## Accepted subset

A fraction core has this bounded grammar:

```text
["0 "] ("0" | "00" | "000") "/" D
D = a decimal integer from 1 through 999, without a leading zero
```

The optional `0 ` is exactly one mandatory whole-number placeholder followed by
one ASCII space. Without it, display is an improper fraction. Numerator zeros
specify minimum digit width, not a maximum numerator. The denominator is fixed
and unreduced, even when it contains the digit zero. Mandatory zeros remain
visible for zero numerators and zero whole parts.

Examples, independently checked against preserved XLS files:

- `0/8`, value 0.5 → `4/8`; value 1.5 → `12/8`.
- `00/16`, value 0.0625 → `01/16`; value -0.5 → `-08/16`.
- `000/100`, value 0.1875 → `019/100`.
- `0 0/8`, value 1.5 → `1 4/8`; value -0.5 → `-0 4/8`.
- `0 0/8`, value 0.999 → `1 0/8`; value 2.999 → `3 0/8`.
- `0 00/16`, value 0.5 → `0 08/16`.
- `0/999`, value 1,000,000 → `999000000/999`.

Existing supported quoted/escaped affixes, color prefixes, ordinary sign/zero
sections, and validated fourth text sections can surround these cores. Examples
in the live oracle include a quoted label, a negative parenthesized section, a
literal zero section, and an empty zero section. Every section must still be
syntactically supported, including branches not selected by the current value.
Conditional formats containing any fraction core remain unsupported.

No built-in number-format IDs are added. In particular, best-fit fraction IDs
12/13 remain on their existing raw-value fallback path. This change applies to
supported custom FORMAT strings through the existing XLS number renderer;
`xls.py` does not need modification.

## Arithmetic and deliberately unsupported boundaries

Only finite stored values with absolute magnitude at most **1,000,000** are
eligible. With a denominator at most 999, the scaled numerator stays below
10^9. Recognition is bounded by the existing maximum format length of 64
characters. There is no search over candidate denominators, iteration over the
value's magnitude, or workbook-wide cache.

The renderer uses `Decimal(str(value))` inside the existing explicit private
precision-340 Decimal context. It multiplies the magnitude by D, rounds to the
nearest integer numerator, and for mixed forms uses integer `divmod` by D to
obtain the whole and remaining numerator. This preserves carry across a whole
number. Negative display signs precede the existing prefix/whole/fraction text;
rounded zero is unsigned. The raw stored value, including negative-zero bits,
is not modified. There is no ambient locale or Decimal-context dependence.

Midpoint behavior is deliberately **not guessed**. For scaled magnitude `s`,
return unsupported if:

```text
abs(s - floor(s) - 0.5) <= 1e-12 * max(1, s)
```

This conservative guard rejects exact ties and their immediate binary64
neighbors, rather than promising parity at numeric boundaries that the sources
and engine observations do not settle. Away from this guard, ordinary half-up
rounding selects the nearest numerator; the tie rule is never used for an
accepted midpoint. The policy operates on the shortest round-trip decimal
representation and is not a claim of universal binary-rounding equivalence.

Why these restrictions exist:

- Calc displayed 0.0625 with `0/8` as `0/8`, and 0.9375 as `7/8`; both are exact
  scaled midpoints. With `0/3`, 1,000,000.5 displayed as `3000002/3`. A single
  general midpoint direction cannot safely be inferred from these probes.
- Calc displayed `#FMT` for 10^12 with the tested fixed-fraction masks. The
  conservative magnitude bound avoids extending an invented fraction display
  into that unverified range. The library retains raw text there, not `#FMT`.
- Optional `#`/`?` masks have suppression and alignment behavior. For example,
  Calc produced a leading space for 0.5 under `# ?/8` and trailing spaces for an
  integer. These masks are excluded rather than silently normalizing layout.

Unsupported masks or unsupported value/mask pairs return `None` from the helper.
The unchanged XLS path then preserves the original numeric `value` and
`value_type="number"`, emits `str(value)` as text, and adds its existing
`Unsupported or ambiguous date/number format: raw numeric value retained.`
warning. A supported fraction mask can therefore still fall back for a
midpoint or out-of-range value.

Explicit exclusions include variable denominators (`# ?/?`, `0/??`), optional
or alignment numerator/whole placeholders, numerator widths above three zeros,
denominators zero/negative/above 999/with leading zeros, extra spacing, grouping,
percent/scaling/scientific combinations, locale/currency tokens, and conditional
fraction sections. Dates, time formats, and quoted literal slashes are not
fraction masks. Unsupported constructs anywhere in an otherwise usable format
prevent partial interpretation.

## Value, formula, and resource contracts

NUMBER records, RK/MULRK integers, and numeric FORMULA caches share the unchanged
XLS numeric path. Only display `text` changes. Raw numeric bits or integer types,
`value_type`, and `is_formula` are preserved; XLS `formula` remains `None` because
binary formula tokens are not decoded to expressions. Existing cached-formula
warnings remain. No calculation, link fetch, or executable interpretation occurs.

Supported fourth text-section behavior continues through the existing validated
helpers. Literal labels such as `0"/8"` retain their original meaning: for value
2 this displays `2/8`, not the scaled numerator of a real fraction core.

Core output is small: at most nine numerator digits for an improper fraction,
seven whole digits for a mixed fraction, three padded numerator digits, three
denominator digits, and fixed separators/sign. Affixes remain bounded by the
64-character format limit. Existing source/stream/record/character limits still
apply. The cumulative text budget charges the full rendered fraction, including
zero padding, numerator expansion, sign, and literal affixes. A limit violation
raises `LimitExceededError`; it does not truncate the display. Non-finite BIFF
values retain the existing `InvalidDocumentError` behavior.

## Reproducible validation

From the repository root:

```sh
.venv/bin/python -m pytest -q tests/test_xls_fractions.py
XLS_FRACTIONS_LO=1 .venv/bin/python -m pytest -q tests/test_xls_fractions.py -k preserved_xls
.venv/bin/python -m pytest -q tests/test_xls*.py
.venv/bin/ruff check src/legacy_office_parser/_xls_formats.py tests/test_xls_fractions.py
```

The ordinary tests need no LibreOffice. They exercise raw-value and formula-cache
preservation through public OLE/XLS readers, auto dispatch, integer records,
serialized display text, both signs and signed zero, mixed carry, denominator and
numerator bounds, malformed/unsupported masks, whole-format validation, explicit
fallback warnings, finite extremes/subnormals, non-finite rejection, hostile
ambient Decimal settings, and exact display-budget boundaries. The separate
opt-in live test verifies all 44 supported cases against LibreOffice CSV after
checking preserved source FORMAT bytes.

Recorded validation:

- Final focused suite: **163 passed, 1 skipped** (the skip is the opt-in oracle).
- Live oracle: **1 passed**, covering all 44 authored supported cases.
- XLS regression suite: **1,920 passed, 10 skipped**, before adding the final
  focused 64/65-character mask-boundary test; that additional test passed in the
  final focused run.
- Ruff passed.
