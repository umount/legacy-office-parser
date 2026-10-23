# XLS General display: retained boundary

## Decision

Retain the existing General extraction projection. No runtime change or wider
format grammar is justified by this investigation. In particular, do not replace
Python's raw numeric spelling with a guessed Excel scientific display, strip
fractional tails from nearly integral values, or impose a generic 15-digit
rounding step on stored binary64 data.

## Primary evidence

[MS-XLS FORMAT 2.4.126](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/300280fd-e4fe-4675-a924-4d383af48d3b)
delegates number-format interpretation to ECMA-376 section 18.8.31.

[Microsoft's NumberingFormat documentation](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.spreadsheet.numberingformat)
reproduces ISO/IEC 29500-1 remarks for General. It describes an attempt to show
up to eleven digits including the decimal point, exponential alternatives, and
selection based on available cell width. Negative-exponent decisions also depend
on which significant digits fit. Consequently, the exponent comparison in that
text does not establish a universal small-number threshold independent of width.

[Microsoft's available number formats](https://support.microsoft.com/en-us/excel/get-started/available-number-formats-in-excel)
describes decimal rounding when a General cell is too narrow and scientific
notation for large values with twelve or more digits.

[Microsoft's Format Cells explanation](https://learn.microsoft.com/en-us/troubleshoot/microsoft-365-apps/excel/format-cells-settings)
also gives a narrow-column example where 123456789 can display as 1.2E+08 while
remaining General. Thus twelve digits is not the only possible switch criterion.
Its explicit scientific example instead specifies `0.00E+00` and a result of
1.22E+07 for 12200000.

[Microsoft's scientific-notation guidance](https://support.microsoft.com/en-us/excel/display-numbers-in-scientific-exponential-notation)
distinguishes explicit scientific decimal-place settings from General, documents
the twelve-digit large-number behavior and mentions fifteen-digit numeric
precision. That precision statement is not a General display algorithm or
permission to rewrite already-stored numeric caches.

## Actual implementation and concrete gaps

`render_number` receives a value and format string, not cell width or font
metrics. For General it removes the floating-point `.0` only from integral
values with magnitude below 100000000000. Other values use `str(value)` after
existing section routing. This is a deterministic extraction policy, not a
claim of width-independent Excel display parity, even for small integers.

Examples of retained limitations:

- 100000000000.0 remains `100000000000.0`; the documented General large-number
  behavior would use scientific notation. The sources do not fix a single
  mantissa precision for this width-free extraction interface.
- 0.00001 remains `1e-05`, reflecting Python's spelling rather than a proven
  Excel small-number threshold, exponent case, or padding rule.
- 1.0000000000000002 remains `1.0000000000000002`. Removing its fractional
  component would silently round a distinct stored value to an integer.
- 99999999999.99998 remains fractional even though it lies just below the
  integer-display boundary; no tolerant integer comparison is introduced.

General's raw projection returns a string successfully and currently emits no
unsupported-format warning. It must not be described as the warning-bearing
fallback used for rejected custom masks. This investigation changes neither
that diagnostic behavior nor the model. NUMBER and numeric FORMULA cache bits
remain authoritative; no formula is calculated or its cache inferred.

An explicit scientific mask supplies the missing decimal-place instruction.
The existing renderer already passes the documented 0.00E+00 examples; no
concrete bug was reproduced in that bounded path. A future General display
change needs an explicit width-independent extraction policy or a deliberately
scoped layout model, with primary evidence and tests for precision and switch
boundaries. LibreOffice behavior alone would not settle Excel's policy.

## Original synthetic validation

`tests/test_xls_general_boundaries.py` characterizes extraction, not Excel
rendering. Fourteen literal cases cover both sides of the large-number boundary,
nearly integral values, Python's small-exponent spelling, subnormal values and
the largest finite binary64 value. Public tests cover built-in/custom General,
NUMBER/numeric FORMULA caches, raw bits, serialization, and current warnings.
An exact text-budget test prevents silently shortening fractional data to fit.

Three explicit scientific cases have separate literal expectations, two from
Microsoft's examples. The live oracle preserves original XLS FORMAT strings and
XF ownership before independently producing formatted CSV; it does not normalize
source formats or use formulas. It is not used as proof of General semantics.

Results: focused General suites 121 passed / 2 opt-in skips; all XLS suites
2633 passed / 15 opt-in skips; preserved-source scientific oracle 1 passed
(three cases); Ruff passed for the new test module.

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_xls_general_boundaries.py tests/test_xls_general_integers.py
PYTHONDONTWRITEBYTECODE=1 XLS_GENERAL_BOUNDARIES_LO=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_xls_general_boundaries.py -k preserved
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_xls*.py
.venv/bin/ruff check --no-cache tests/test_xls_general_boundaries.py
```
