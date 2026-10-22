# XLS all-optional decimal digits: bounded nonintegral subset

Implementation stage: isolated `legacy-optional024`, before the separately owned
variable-fraction changes. No runtime dependency, locale mutation, converter,
network call, or workbook-wide cache is added. Only display text changes;
stored values and numeric formula-cache metadata remain unchanged.

## Evidence and unresolved boundary

[MS-XLS 2.4.126 FORMAT](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/300280fd-e4fe-4675-a924-4d383af48d3b)
defines number-format syntax and delegates interpretation to ECMA-376. It does
not by itself settle every display edge case.

[Microsoft custom-format guidelines](https://support.microsoft.com/en-US/Excel/review-guidelines-for-customizing-a-number-format)
describe optional `#` digits, rounding to the available decimal places, and a
mandatory leading `0`. The consulted primary evidence does not explicitly
resolve decimal-point suppression when all fractional placeholders disappear.

An independent exploratory run on preserved XLS FORMAT strings observed that
LibreOffice 7.4.7.2 removes the point for integral rounded results, including
`1` and carry from `9.999` under `0.##`. This is not an Excel oracle. This stage
therefore returns unsupported whenever an all-optional selected core rounds to
an integer. Zero, signed zero, tiny values rounding to zero, and whole-number
carry all retain raw-value text with the existing format warning. It does not
claim that such masks are invalid Excel syntax.

## Exact new grammar

The additional numeric core is:

```text
integer = "0" | "#,##0"
core    = integer "." HASHES
HASHES  = 1 through 15 consecutive ASCII "#" characters
```

The existing tokenizer still recognizes a single contiguous numeric core with
quoted/escaped literal affixes. Existing colors, sign/zero sections, and already
supported nonnegative conditional routing remain available. Every section is
validated before selecting one. An unsupported unused branch still causes
fallback. A syntactically supported optional branch is no longer an unknown
branch merely because another value would make its display ambiguous.

No new scaling-comma, percentage, currency-token, scientific, optional-integer,
alignment `?`, locale, or mixed-order placeholder forms are accepted. Thus
`0.##%`, `0.##,`, `[$$-409]0.##`, `0.#0`, `#.##`, and `0.##E+00` remain unsupported.
Quoted or escaped percent signs are literal affixes and do not scale a value.
Existing mandatory-decimal formats such as `0.0##`, including their previously
supported scaling/currency combinations, retain their old behavior.

## Display algorithm and contracts

1. Validate and route sections using the existing unrounded value rules. Negative
   conditional values retain the existing conservative fallback. Ordinary
   negative sections use their existing magnitude/sign behavior.
2. In the existing private precision-340, ROUND_HALF_UP Decimal context, quantize
   `Decimal(str(value))` to the number of decimal placeholders.
3. For an all-optional core, compare the rounded number with its integral value.
   Equality means fallback, before any affix or zero suppression is emitted.
4. Otherwise reuse fixed formatting and remove trailing zero digits, at most the
   number of optional placeholders. A nonzero fractional digit remains, so no
   special decimal-point deletion rule is required.

Examples: `0.##` maps `1.2` to `1.2`, `1.236` to `1.24`, and `-1.236` to `-1.24`.
`#,##0.##` maps `1234.5` to `1,234.5`. `0.##` with `1`, `0`, `-0.0`, `.004`, or
`9.999` falls back. An explicit zero literal in a third section can still display
`zero`, because that selected section has no ambiguous decimal core.

The rounding policy is the existing shortest-round-trip Decimal policy, not
universal Excel binary-rounding equivalence. The original 64-character mask
bound and 15-decimal-place bound remain. Output and decoded format text are
charged to the existing cumulative budget; no display is truncated. Numeric
NUMBER/FORMULA results preserve float bits, including negative zero. Integer
RK/MULRK results preserve integer types on fallback. Nonfinite public XLS values
remain invalid. No formula expression is evaluated.

Text-section helpers still apply their existing three-sign validation probes.
Because optional cores can reject integral results, this stage does not promise
new fourth-section text expansion/hiding support for every newly recognized mask.

## Independent oracle and tests

`tests/test_xls_optional_decimals.py` contains original synthetic public XLS tests
and literal expected strings. The live test reuses `_xls_format_oracle`:
unique harmless seed masks are exported to XLS, then exact-length FORMAT strings
are replaced with the intended masks. FORMAT/XF/cell ownership is verified before
LibreOffice independently exports CSV with formatted text. Input XLS bytes must
remain unchanged. Parser output never generates the oracle's expectations.

The live suite checks 28 authored cases: signs, trimming, rounding, grouping,
1 through 15-place representative masks, literal affixes and escapes, colors,
parenthesized negative sections, explicit zero literals, and empty zero sections.
The converter is test-only, with private profiles, resource limits and a bounded
process-group timeout. No private files are involved.

Commands:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_xls_optional_decimals.py
PYTHONDONTWRITEBYTECODE=1 XLS_OPTIONAL_DECIMALS_LO=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_xls_optional_decimals.py -k preserved_source
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_xls*.py
```

The following results were obtained in the isolated optional-decimal copy,
before merging the independent variable-fraction changes. They establish the
optional-decimal subset's validation scope, not a combined main-stage result.

Focused verification: **142 passed, 1 skipped** (opt-in live oracle).
Live verification: **1 passed**, checking all **28 cases**, LibreOffice 7.4.7.2.
Ruff passed. A separate read-only comparison against the copied baseline ran
**5,160 identical-output checks** on existing fixed, scientific, fixed-fraction,
color, literal, scaling, currency, conditional, and section combinations.

## Combined validation

The combined 0.24 suite, including variable fractions, passes 6,437 tests with
71 optional skips. Both preserved-source XLS oracle checks pass. Negative syntax
cases continue to assert rejection of an unsupported branch even when that branch
is not selected; selected integral ambiguity remains a value-dependent fallback.
