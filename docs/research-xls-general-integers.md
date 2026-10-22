# XLS General: whole-number text

## Problem and boundary

BIFF NUMBER and numeric FORMULA caches are binary64 values. Python therefore
represents a stored whole number as `1.0`. Passing `str(value)` directly into
cell text incorrectly preserved the `.0` in ordinary General displays.

For a selected General section, finite integral values with absolute value less
than 100,000,000,000 now produce decimal integer text without a fractional suffix.
This also displays either signed zero as `0`; the raw value retains its sign.
Built-in format 0 and explicit custom General formats share this path.
NUMBER, RK, MULRK and numeric FORMULA caches use the existing number formatter.
Explicit decimal masks such as `0.0`, missing XF metadata, and unsupported masks
retain their own existing behavior. No input value or formula cache is rewritten.

[Microsoft's number-format guidance](https://support.microsoft.com/en-us/excel/get-started/available-number-formats-in-excel?re=true)
describes General as the default display and specifies scientific notation for
numbers with twelve or more digits. This change deliberately stops below that
boundary. Fractional and larger values retain the existing raw text projection;
complete width-dependent General rounding and scientific formatting are not
implemented or claimed. Column width is not inferred.

## Formula caches

The reader does not calculate formulas. A numeric cached zero stays zero even
when an independent office application's recalculation produces a month name or
an empty result. String caches use their existing separate BIFF STRING record
path. Reference conversion can recalculate and must not silently replace the
stored-value oracle. Source-cache comparisons and display comparisons are
separate checks.

## Validation

`tests/test_xls_general_integers.py` uses original synthetic BIFF records and
literal expected strings. It covers numeric record paths, typed-value retention,
signed zero, near-integer fractions, large values, explicit decimal and unsupported
formats, and existing section-selection constraints. Two prior signed-zero
General expectations were updated to `0`; their raw-bit checks remain intact.

The optional `XLS_GENERAL_LO=1` test uses the existing preserved-source FORMAT
oracle on nine literal cases. It verifies small integers, signed zero, both signs
at the eleven-digit boundary, a fractional control, and an explicit-decimal
control. The live test passed with the focused suite: 62 passed. It does not
use formulas, so recalculation cannot substitute for the stored display inputs.
No private file is part of these tests.
