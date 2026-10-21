# XLS: sign-based numeric sections

## Contract

Ordinary sections for positive, negative, and zero values are supported.
One section applies to all numbers. Two mean “positive and zero; negative,”
while three mean “positive; negative; zero.” An optional fourth section is
allowed only as `@`, which does not change the original cell text.

The section is selected using the raw value before rounding. The negative
section receives the absolute value; its mask specifies the sign or parentheses.
Thus `0.00;(0.00);"zero"` displays -12.5 as `(12.50)`, -0.001 as `(0.00)`,
and zero as `zero`. The numeric `value` is retained unchanged, including its sign.
The text representation may hide the sign at the author's explicit direction:
`0.00;0.00` displays -12.5 as `12.50`. Use the raw value as well for analysis;
text does not replace typed data. `General` is also allowed as an entire section;
`General;General` produces `12.5` for -12.5, as separately confirmed by
LibreOffice. Otherwise, the existing `str(value)` contract is preserved.

Only an unescaped semicolon outside quotes acts as a separator.
All sections are validated before selection, including those unused for the
current number. The existing numeric cores and explicit labels are allowed;
plus, minus, and parentheses may be unescaped. Exponent signs remain part of
the numeric core. The zero section may contain a nonempty quoted/escaped label
without a number.

One standard color is allowed at the start of a numeric section: Black, Blue,
Cyan, Green, Magenta, Red, White, or Yellow (case-insensitive). Color is purely
formatting and is not included in the extracted data. Color indices, other
bracketed directives, and comparisons such as `[>100]` are not interpreted.

## Limitations

The overall mask limit remains 64 characters, with no more than four sections.
Empty/hiding sections, an arbitrary text section in the fourth position, locales,
conditions, accounting, comma-scaled formats, and fraction formats remain
unsupported: the raw number is returned with a warning. An ambiguous format
cannot be accepted even in an unselected section. Formulas are not evaluated;
only their stored numeric results are used. Date-format support is unchanged.
All output text counts toward the limits.

## Basis and validation

[Microsoft: number format sections](https://support.microsoft.com/en-us/excel/review-guidelines-for-customizing-a-number-format)
describes section order, quotes, escaping, and standard colors. The implementation
is independent; no formatting libraries were added.

The authored `tests/fixtures/xls_sections/sign_sections.xlsx` specifies exact masks
and values independently of the parser. It is used only to prepare tests and does
not add XLSX runtime support. LibreOffice 7.4.7.2 exported the XLS; a separate CSV
run checks nine expected rows, including a formula, parentheses, percentages,
a USD label, zero, and a semicolon within a label. The source OOXML is reproducible;
binary metadata in the exported XLS may differ between runs. The API and CLI are
tested separately from the formatter.
