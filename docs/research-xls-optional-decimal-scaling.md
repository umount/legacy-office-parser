# XLS optional decimals with percentage or scaling

## Primary evidence

[MS-XLS FORMAT, section 2.4.126](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/300280fd-e4fe-4675-a924-4d383af48d3b)
permits decimal/group separators and optional digit placeholders in numeric
formats, permits percent tokens, and delegates interpretation to ECMA-376
18.8.31. Its grammar is locale-specific; this implementation retains the existing
en-US subset.

[Microsoft custom-number-format guidelines](https://support.microsoft.com/en-us/excel/review-guidelines-for-customizing-a-number-format)
describe optional zero suppression, fractional-place rounding, percent scaling
by 100, and trailing-comma scaling by thousands. Its table demonstrates
12200000 displayed as 12.2M using `0.0,,"M"`. Nearby prose for `#.0,,` instead
gives 12200.0, contradicting that table. The prose example is therefore not
independent confirmation of repeated-comma arithmetic.

Combining optional placeholders with scaling is an inference from these
composable rules, not a claim that Microsoft demonstrates every accepted mask.
LibreOffice provides an independent implementation check, not normative Excel
semantics. This extends the percent/scaling exclusions recorded in
`research-xls-optional-decimals.md`; its integral-result limitation still applies.

## Supported subset

An integer core of `0` or `#,##0`, a decimal point, and 1–15 consecutive `#`
placeholders may now have either one trailing percent sign or trailing scaling
commas. Existing literal affixes, colors and section routing remain available.
The complete format is limited to 64 characters.

Examples:

- `0.##%`, 0.12345: `12.35%`.
- `0.##%`, 0.125: `12.5%`.
- `0.##,`, 1234.5: `1.23`.
- `#,##0.##,`, 1234567: `1,234.57`.
- `0.###,,"M"`, 1234000: `1.234M`.

The selected result must remain nonintegral after scaling and rounding. Thus
`0.##%` with 0.01 and `0.##,` with 1000 still fall back to raw-value text with
the existing unsupported-format warning. Zero, signed zero, tiny results rounded
to zero, and whole-number carry retain the same fallback. No decimal-point
suppression rule is inferred from Calc.

Percent-plus-scaling combinations, repeated percent signs, optional-decimal
currency/locale tokens, and mixed mandatory/optional percent cores such as
`0.0#%` remain unsupported. Negative conditional values remain unsupported;
ordinary negative sections retain their existing sign/magnitude rules. General
scientific display is unchanged. Fourth-section text helpers explicitly reject
optional-only decimal cores containing scaling commas or an operative percent
sign, even when numeric probes for -1, 0 and 1 now succeed. This preserves their
previous acceptance boundary: stored strings remain visible and unmodified for
these masks, whether the fourth section is empty, an affixed `@`, or a literal.
The guard applies to every numeric branch, including unselected branches;
ordinary numeric rendering still accepts the new supported cores. Existing
mandatory-decimal scaling masks retain their text-helper behavior.
Every section is syntactically validated, including unselected branches.

## Algorithm and resource contracts

Numeric grammar guards admit the new cores. The existing renderer routes sections on
the unscaled value, scales in its private precision-340 Decimal context, rounds
to the available places, checks the optional-decimal integral-result boundary,
then trims insignificant fractional zeros. Percent signs are appended only for
operative percent tokens; quoted or escaped signs remain literal text.

The established Decimal(str(value))/ROUND_HALF_UP policy remains; this does not
claim universal Excel binary-rounding parity. Runtime work stays bounded by the
64-character format and 15-place limits. No new dependencies or record routing
are introduced. Raw values, numeric storage types and formula-cache metadata
are preserved. Retained display text uses the existing cumulative text budget.

## Independent tests

`tests/test_xls_optional_decimal_scaling.py` supplies 23 original literal cases
for NUMBER and numeric FORMULA caches, and a preserved-source LibreOffice oracle.
The oracle patches exact original FORMAT strings into synthetic XLS, verifies
FORMAT/XF ownership, exports formatted CSV independently, and verifies source
XLS bytes remain unchanged. Expectations are literal strings; neither parser
output nor exporter-normalized FORMAT strings generate the expected results.

An additional 51 regressions check text-helper isolation: 48 combinations of
numeric masks, empty/affixed/literal/identity fourth sections, and LABEL or cached
FORMULA strings retain `retained` in public text and serialization. They cover
colors, grouping, repeated scaling commas, percent, and an optional-scaling core
in an otherwise unselected zero branch. Three positive controls verify that
mandatory-decimal scaling still permits hiding, affixes, and literal replacement.

Negative tests cover scaled integral results and carry, signed zero, subnormals,
maximum finite inputs, combined masks, unsupported unused branches, negative
conditions, and mask/precision limits. Further tests cover RK/MULRK integer
preservation, midpoint neighbors, hostile Decimal context, and exact public
text-budget boundaries. Existing unsupported-syntax sentinels for the newly
supported grammar are replaced with still-unsupported combined/mixed masks.

Validation:

- Focused optional-decimal suites: 292 passed, 2 opt-in skips.
- Existing and new XLS suites: 2573 passed, 14 opt-in skips.
- Preserved-source LibreOffice oracle: 1 passed, checking all 23 literal cases.
- Ruff: passed for the formatter and both affected test files.

Commands:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_xls_optional_decimal_scaling.py tests/test_xls_optional_decimals.py
PYTHONDONTWRITEBYTECODE=1 XLS_OPTIONAL_SCALING_LO=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_xls_optional_decimal_scaling.py -k literal_preserved
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_xls*.py
.venv/bin/ruff check --no-cache src/legacy_office_parser/_xls_formats.py tests/test_xls_optional_decimal_scaling.py tests/test_xls_optional_decimals.py
```
